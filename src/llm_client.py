"""Small CLI adapter for generation calls.

The bot can run against Claude Code, Codex CLI, Gemini CLI, or OpenCode CLI.
Keep provider differences and local rate limiting here so agents only ask for text.
"""
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .config import (
    LLM_MAX_CALLS_PER_DAY,
    LLM_MAX_CALLS_PER_HOUR,
    LLM_MIN_SECONDS_BETWEEN_CALLS,
    _PROJECT_ROOT,
)
from .logger import log


@dataclass
class LLMResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


LLM_RATE_LIMIT_CODE = 75
_LOCK = threading.Lock()
_STATE_FILE = Path(_PROJECT_ROOT) / ".llm_rate_state.json"


def _provider() -> str:
    requested = os.environ.get("AI_CLI", "opencode").strip().lower()
    if requested in {"claude", "codex", "gemini", "opencode"}:
        return requested
    if shutil.which("opencode"):
        return "opencode"
    if shutil.which("gemini"):
        return "gemini"
    if shutil.which("claude"):
        return "claude"
    if shutil.which("codex"):
        return "codex"
    return "opencode"


def _load_state() -> dict:
    try:
        with _STATE_FILE.open("r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        with _STATE_FILE.open("w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _rate_limits() -> tuple[float, int]:
    min_gap = float(os.environ.get("LLM_MIN_SECONDS_BETWEEN_CALLS", str(LLM_MIN_SECONDS_BETWEEN_CALLS)))
    max_hour = int(os.environ.get("LLM_MAX_CALLS_PER_HOUR", str(LLM_MAX_CALLS_PER_HOUR)))
    max_day = int(os.environ.get("LLM_MAX_CALLS_PER_DAY", str(LLM_MAX_CALLS_PER_DAY)))
    return min_gap, max_hour, max_day


def _enforce_budget() -> bool:
    """Hard-stop local LLM calls only when explicitly requested.

    Default is soft accounting: production content can keep shipping, while
    high-waste paths should be controlled by scheduling and feature flags.
    """
    return os.environ.get("LLM_ENFORCE_BUDGET", "0") == "1"


def llm_hourly_limit_status() -> tuple[bool, int, int, int]:
    """Return (limited, used, max_hour, seconds_until_oldest_hourly_call_expires)."""
    now = time.time()
    _, max_hour, max_day = _rate_limits()
    with _LOCK:
        state = _load_state()
        raw_calls = state.get("calls", [])
        hour_calls = sorted(float(t) for t in raw_calls if now - float(t) < 3600)
        day_calls = sorted(float(t) for t in raw_calls if now - float(t) < 86400)
    if not _enforce_budget():
        return False, len(hour_calls), max_hour, 0
    if len(day_calls) >= max_day:
        reset_seconds = max(1, int(86400 - (now - day_calls[0]))) if day_calls else 86400
        return True, len(day_calls), max_day, reset_seconds
    if len(hour_calls) >= max_hour:
        reset_seconds = max(1, int(3600 - (now - hour_calls[0]))) if hour_calls else 3600
        return True, len(hour_calls), max_hour, reset_seconds
    return False, len(hour_calls), max_hour, 0


def _wait_for_slot(label: str):
    """Throttle all local CLI calls across bot threads.

    This does not replace provider limits, but it prevents bursty scheduler
    overlap from firing 5-10 model calls at once.
    """
    min_gap, max_hour, max_day = _rate_limits()
    now = time.time()

    with _LOCK:
        state = _load_state()
        calls = [t for t in state.get("calls", []) if now - float(t) < 86400]
        hour_calls = [t for t in calls if now - float(t) < 3600]
        over_day = len(calls) >= max_day
        over_hour = len(hour_calls) >= max_hour
        if _enforce_budget():
            if over_day:
                msg = f"local LLM daily budget reached ({len(calls)}/{max_day} calls in 24h)"
                log.info(f"[LLM] {label}: {msg}")
                return LLMResult(LLM_RATE_LIMIT_CODE, "", msg)
            if over_hour:
                msg = f"local LLM hourly budget reached ({len(hour_calls)}/{max_hour} calls in 1h)"
                log.info(f"[LLM] {label}: {msg}")
                return LLMResult(LLM_RATE_LIMIT_CODE, "", msg)
        elif over_day or over_hour:
            log.info(
                f"[LLM] {label}: soft budget exceeded "
                f"(hour={len(hour_calls)}/{max_hour}, day={len(calls)}/{max_day}); continuing."
            )

        last_call = float(state.get("last_call", 0) or 0)
        sleep_for = max(0.0, min_gap - (now - last_call))
        if sleep_for > 0:
            log.info(f"[LLM] {label}: spacing call by {sleep_for:.1f}s")
            time.sleep(sleep_for)
            now = time.time()

        calls.append(now)
        state["calls"] = calls
        state["last_call"] = now
        _save_state(state)
    return None


def _build_cmd(
    prompt: str,
    model: str,
    output_json: bool,
    allowed_tools: Optional[Sequence[str]],
    permission_mode: Optional[str],
) -> list[str]:
    provider = _provider()
    if provider == "codex":
        cmd = [
            "codex",
        ]
        if allowed_tools and any(t.lower() in {"websearch", "webfetch"} for t in allowed_tools):
            cmd.append("--search")
        cmd.extend([
            "exec",
            "--model", model,
            "--sandbox", "read-only",
            "--ephemeral",
            prompt,
        ])
        return cmd

    if provider == "gemini":
        cmd = ["gemini", "-p", prompt, "--model", model, "--skip-trust"]
        if output_json:
            cmd.extend(["--output-format", "json"])
        if permission_mode:
            # gemini uses --approval-mode: default, auto_edit, yolo, plan
            # map 'read-only' (claude) to 'plan' (gemini)
            mode = "plan" if permission_mode == "read-only" else permission_mode
            cmd.extend(["--approval-mode", mode])
        elif allowed_tools:
            # If tools are requested but no explicit mode, use yolo for headless automation
            cmd.extend(["--approval-mode", "yolo"])
        return cmd

    if provider == "opencode":
        cmd = [
            "opencode", "run",
            "--model", model,
        ]
        if allowed_tools or permission_mode:
            cmd.append("--dangerously-skip-permissions")
        if output_json:
            cmd.extend(["--format", "json"])
        cmd.append(prompt)
        return cmd

    cmd = ["claude", "-p", prompt, "--model", model, "--no-session-persistence"]
    if output_json:
        cmd.extend(["--output-format", "json"])
    if allowed_tools:
        cmd.extend(["--allowedTools", *allowed_tools])
    if permission_mode:
        cmd.extend(["--permission-mode", permission_mode])
    return cmd


def run_llm(
    prompt: str,
    model: str,
    *,
    label: str,
    output_json: bool = True,
    allowed_tools: Optional[Sequence[str]] = None,
    permission_mode: Optional[str] = None,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
) -> LLMResult:
    gate = _wait_for_slot(label)
    if gate:
        return gate

    cmd = _build_cmd(prompt, model, output_json, allowed_tools, permission_mode)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return LLMResult(124, "", f"{label} timed out after {timeout}s")
    return LLMResult(result.returncode, result.stdout or "", result.stderr or "")


def _unwrap_ndjson(raw: str) -> str | None:
    """Try parsing NDJSON (opencode --format json) and return concatenated text."""
    lines = raw.strip().splitlines()
    if len(lines) < 2:
        return None
    parts: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        if obj.get("type") == "text":
            text = obj.get("part", {}).get("text", "")
            if text:
                parts.append(text)
    if parts:
        return "".join(parts)
    return None


def unwrap_text(stdout: str) -> str:
    """Return model text from provider CLI output.

    Handles NDJSON (opencode --format json), JSON envelopes
    (Gemini --output-format json, Claude --output-format json),
    and raw text (Codex, opencode default, pipe-through).
    """
    raw = (stdout or "").strip()
    if not raw:
        return ""

    ndjson_result = _unwrap_ndjson(raw)
    if ndjson_result is not None:
        return ndjson_result

    try:
        if "{" in raw:
            json_start = raw.find("{")
            json_data = raw[json_start:]
            envelope = json.loads(json_data)
        else:
            envelope = json.loads(raw)

        if isinstance(envelope, dict):
            return str(envelope.get("response") or envelope.get("result") or raw).strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return raw
