"""Small CLI adapter for generation calls.

The bot can run against Claude Code, Codex CLI, Gemini CLI, or OpenCode CLI.
Keep provider differences and local rate limiting here so agents only ask for text.
"""
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

@dataclass
class LLMResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


LLM_RATE_LIMIT_CODE = 75


def llm_hourly_limit_status() -> tuple[bool, int, int, int]:
    """Compatibility shim: LLM budget limits are disabled."""
    return False, 0, 0, 0


def _provider() -> str:
    requested = os.environ.get("AI_CLI", "codex").strip().lower()
    if requested in {"claude", "codex", "gemini", "opencode"}:
        return requested
    if shutil.which("codex"):
        return "codex"
    if shutil.which("opencode"):
        return "opencode"
    if shutil.which("gemini"):
        return "gemini"
    if shutil.which("claude"):
        return "claude"
    return "codex"


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


def _text_from_event(obj: dict) -> str:
    if obj.get("type") == "text":
        part = obj.get("part")
        if isinstance(part, dict):
            return str(part.get("text") or "")
        return str(obj.get("text") or "")

    # Some OpenCode versions emit assistant/message-style JSON events instead
    # of the older {type:"text", part:{text:"..."}} shape.
    message = obj.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            return "".join(parts)

    content = obj.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or item.get("content") or "") for item in content if isinstance(item, dict))

    return ""


def _unwrap_ndjson(raw: str) -> str | None:
    """Try parsing OpenCode JSON events and return concatenated text."""
    lines = raw.strip().splitlines()
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
        text = _text_from_event(obj)
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
            event_text = _text_from_event(envelope)
            if event_text:
                return event_text.strip()
            return str(envelope.get("response") or envelope.get("result") or raw).strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return raw
