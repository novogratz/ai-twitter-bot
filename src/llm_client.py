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
DEFAULT_LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "180"))


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
    provider: Optional[str] = None,
) -> list[str]:
    provider = provider or _provider()
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


def _fallback_provider(primary_provider: str) -> Optional[str]:
    default_fallback = "codex" if primary_provider == "opencode" else "opencode"
    fallback = os.environ.get("LLM_FALLBACK_CLI", default_fallback).strip().lower()
    if os.environ.get("LLM_DISABLE_FALLBACK", "0") == "1":
        return None
    if not fallback or fallback == primary_provider:
        return None
    if fallback not in {"claude", "codex", "gemini", "opencode"}:
        return None
    if not shutil.which(fallback):
        return None
    return fallback


def _fallback_model(primary_model: str, fallback_provider: str) -> str:
    env_model = os.environ.get("LLM_FALLBACK_MODEL", "").strip()
    if env_model:
        return env_model
    if fallback_provider == "codex":
        return os.environ.get("CODEX_FALLBACK_MODEL", "").strip() or "gpt-5.4-mini"
    if fallback_provider == "gemini":
        return os.environ.get("GEMINI_FALLBACK_MODEL", "").strip() or "gemini-2.0-flash"
    if fallback_provider == "claude":
        return os.environ.get("CLAUDE_FALLBACK_MODEL", "").strip() or "claude-sonnet-4-6"
    if fallback_provider == "opencode":
        return os.environ.get("OPENCODE_FALLBACK_MODEL", "").strip() or "opencode/ring-2.6-1t-free"
    return primary_model


def _run_cmd(
    cmd: list[str],
    *,
    label: str,
    timeout: Optional[int],
    cwd: Optional[str],
) -> LLMResult:
    effective_timeout = timeout if timeout is not None else DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        return LLMResult(127, "", f"{label} command not found: {exc.filename}")
    except subprocess.TimeoutExpired:
        return LLMResult(124, "", f"{label} timed out after {effective_timeout}s")
    return LLMResult(result.returncode, result.stdout or "", result.stderr or "")


_CODEX_LIMIT_PATTERNS = (
    "context length exceeded",
    "context_length_exceeded",
    "maximum context",
    "max tokens",
    "token limit",
    "too many tokens",
    "input is too long",
    "rate limit",
    "rate_limit",
    "quota exceeded",
    "no output",
)


def _should_fallback(result: LLMResult) -> bool:
    if result.returncode != 0 or result.returncode == LLM_RATE_LIMIT_CODE:
        return True
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    if not combined.strip():
        return True
    # Catch token/context-limit and rate-limit errors returned with exit 0
    if any(pat in combined for pat in _CODEX_LIMIT_PATTERNS):
        return True
    # Empty useful content in stdout
    if not (result.stdout or "").strip():
        return True
    return False


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
    provider = _provider()
    cmd = _build_cmd(prompt, model, output_json, allowed_tools, permission_mode, provider)
    result = _run_cmd(cmd, label=label, timeout=timeout, cwd=cwd)
    if not _should_fallback(result):
        return result

    fallback_provider = _fallback_provider(provider)
    if not fallback_provider:
        return result

    fallback_model = _fallback_model(model, fallback_provider)
    fallback_cmd = _build_cmd(
        prompt,
        fallback_model,
        output_json,
        allowed_tools,
        permission_mode,
        fallback_provider,
    )
    fallback_result = _run_cmd(fallback_cmd, label=f"{label} fallback", timeout=timeout, cwd=cwd)
    fallback_note = (
        f"{label} primary {provider}/{model} failed "
        f"(exit {result.returncode}); tried {fallback_provider}/{fallback_model}."
    )
    combined_stderr = "\n".join(
        part for part in [result.stderr.strip(), fallback_note, fallback_result.stderr.strip()] if part
    )
    return LLMResult(fallback_result.returncode, fallback_result.stdout, combined_stderr)


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
