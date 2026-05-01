"""Small CLI adapter for generation calls.

The bot can run against either Claude Code or Codex CLI. Keep provider
differences and local rate limiting here so agents only ask for text.
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

from .config import _PROJECT_ROOT
from .logger import log


@dataclass
class LLMResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


_LOCK = threading.Lock()
_STATE_FILE = Path(_PROJECT_ROOT) / ".llm_rate_state.json"


def _provider() -> str:
    requested = os.environ.get("AI_CLI", "codex").strip().lower()
    if requested in {"claude", "codex"}:
        return requested
    if shutil.which("claude"):
        return "claude"
    if shutil.which("codex"):
        return "codex"
    return "claude"


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


def _wait_for_slot(label: str):
    """Throttle all local CLI calls across bot threads.

    This does not replace provider limits, but it prevents bursty scheduler
    overlap from firing 5-10 model calls at once.
    """
    min_gap = float(os.environ.get("LLM_MIN_SECONDS_BETWEEN_CALLS", "25"))
    max_hour = int(os.environ.get("LLM_MAX_CALLS_PER_HOUR", "40"))
    now = time.time()

    with _LOCK:
        state = _load_state()
        calls = [t for t in state.get("calls", []) if now - float(t) < 3600]
        if len(calls) >= max_hour:
            msg = f"local LLM rate limit reached ({len(calls)}/{max_hour} calls in 1h)"
            log.info(f"[LLM] {label}: {msg}")
            return LLMResult(75, "", msg)

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
            "exec",
            "--model", model,
            "--sandbox", "read-only",
            "--ask-for-approval", "never",
            "--ephemeral",
        ]
        if allowed_tools and any(t.lower() in {"websearch", "webfetch"} for t in allowed_tools):
            cmd.append("--search")
        cmd.append("-")
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
    input_text = prompt if _provider() == "codex" else None
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return LLMResult(124, "", f"{label} timed out after {timeout}s")
    return LLMResult(result.returncode, result.stdout or "", result.stderr or "")


def unwrap_text(stdout: str) -> str:
    """Return model text from Claude JSON envelopes or raw Codex output."""
    raw = (stdout or "").strip()
    if not raw:
        return ""
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict):
            return str(envelope.get("result", raw)).strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return raw
