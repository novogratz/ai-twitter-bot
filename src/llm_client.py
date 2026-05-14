"""Small CLI adapter for generation calls.

The bot can run against Claude Code, Codex CLI, Gemini CLI, or OpenCode CLI.
Keep provider differences and local rate limiting here so agents only ask for text.
"""
import json
import os
import re
import signal
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence


# Tool-call markup that codex (and occasionally other CLIs) leak into raw
# stdout when the model attempts to call an unauthorized tool. Example seen
# in prod 2026-05-13:
#   <function=bash>
#   <parameter=command>
#   curl -s https://api.github.com/...
#   </parameter>
#   </function>
# Stripping aggressively because a leaked <function=...> block once cost
# us a posted tweet that read "<function=bash>\n<parameter=command>...".
_TOOL_CALL_BLOCK = re.compile(
    r"<\s*function\s*=[^>]*>.*?<\s*/\s*function\s*>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_CALL_OPEN = re.compile(
    r"<\s*function\s*=[^>]*>.*",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_BLOCK = re.compile(
    r"<\s*parameter\s*=[^>]*>.*?<\s*/\s*parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_OPEN = re.compile(
    r"<\s*parameter\s*=[^>]*>.*",
    re.IGNORECASE | re.DOTALL,
)


def strip_tool_calls(text: str) -> str:
    """Remove leaked <function=...>...</function> and <parameter=...>...</parameter>
    blocks from model output. Strips unterminated openers too — codex
    sometimes truncates mid-tool-call when the sandbox refuses execution.

    Idempotent. Safe to call on already-clean text.
    """
    if not text or "<" not in text:
        return text
    cleaned = _TOOL_CALL_BLOCK.sub("", text)
    cleaned = _PARAMETER_BLOCK.sub("", cleaned)
    cleaned = _TOOL_CALL_OPEN.sub("", cleaned)
    cleaned = _PARAMETER_OPEN.sub("", cleaned)
    return cleaned.strip()


def contains_tool_call_leak(text: str) -> bool:
    """Returns True if the text looks like it still contains tool-call markup.

    Use as a post-scrub guard — if this returns True after strip_tool_calls,
    the safest action is to reject the post entirely rather than ship
    half-stripped garbage.
    """
    if not text:
        return False
    lower = text.lower()
    return any(
        marker in lower
        for marker in ("<function=", "</function>", "<parameter=", "</parameter>")
    )


# OpenCode/Claude NDJSON envelope leaks. These never appear in a real tweet,
# only in raw provider stdout when the CLI got killed mid-stream and the
# downstream parser fell back to returning raw. Seen in prod 2026-05-14:
# a hot take shipped as literally `{"type":"step_start","timestamp":...`.
_STREAM_ENVELOPE_MARKERS = (
    '"type":"step_',
    '"sessionID":',
    '"messageID":',
    '"part":{"id":',
    '"step_start"',
    '"step_finish"',
    'tool_call_id',
    '"tool_use_id"',
)


def contains_post_unsafe_leak(text: str) -> bool:
    """Pre-flight post check. True if text contains ANY leak shape — tool-call
    XML, NDJSON envelope keys, or starts with a raw JSON object/array. Tweets
    never legitimately match these. Rejecting is always safer than posting.
    """
    if not text:
        return False
    if contains_tool_call_leak(text):
        return True
    stripped = text.strip()
    # A tweet that opens with `{` or `[{` is a JSON shape, not a tweet.
    if stripped.startswith("{") or stripped.startswith("[{"):
        return True
    low = stripped.lower()
    if any(marker.lower() in low for marker in _STREAM_ENVELOPE_MARKERS):
        return True
    return False

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
    env_fallback = os.environ.get("LLM_FALLBACK_CLI", "").strip().lower()
    fallback = env_fallback or default_fallback
    if os.environ.get("LLM_DISABLE_FALLBACK", "0") == "1":
        return None
    if not fallback:
        return None
    if fallback not in {"claude", "codex", "gemini", "opencode"}:
        return None
    if not shutil.which(fallback):
        return None
    # Same-provider fallback only allowed when explicitly requested via env
    # (different model, e.g. opencode/big-pickle → opencode/qwen)
    if fallback == primary_provider and not env_fallback:
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
        return os.environ.get("OPENCODE_FALLBACK_MODEL", "").strip() or "opencode/big-pickle"
    return primary_model


def _fallback_model2(fallback_provider: str) -> Optional[str]:
    """Second-level fallback model — used when the first fallback also fails."""
    if fallback_provider == "opencode":
        return os.environ.get("OPENCODE_FALLBACK2_MODEL", "").strip() or "ollama/qwen3-coder"
    return None


def _run_cmd(
    cmd: list[str],
    *,
    label: str,
    timeout: Optional[int],
    cwd: Optional[str],
) -> LLMResult:
    effective_timeout = timeout if timeout is not None else DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            start_new_session=True,  # isolate process group so children can be reaped
        )
        try:
            stdout, stderr = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group (catches search/child workers that hold pipes)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.communicate()
            return LLMResult(124, "", f"{label} timed out after {effective_timeout}s")
    except FileNotFoundError as exc:
        return LLMResult(127, "", f"{label} command not found: {exc.filename}")
    return LLMResult(proc.returncode, stdout or "", stderr or "")


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
    "usage limit",
    "hit your usage",
    "upgrade to pro",
    "no output",
)

# Soft-failure markers: exit 0 but the model returned meta-commentary
# instead of doing the task (refusing WebSearch, narrating instead of
# producing a tweet). 2026-05-13: opencode/big-pickle started emitting
# "[no need to search for external sources...]" — exit 0, but useless.
# These trip the same fallback ladder as hard failures.
_REFUSAL_PATTERNS = (
    "no need to search",
    "no need to look up",
    "as the user has provided",
    "as you have provided",
    "i don't need to search",
    "i do not need to search",
    "i cannot search",
    "i'm unable to search",
    "i am unable to search",
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
    # Soft refusal: model returned meta-commentary instead of doing the task.
    stdout_low = (result.stdout or "").lower()
    if any(pat in stdout_low for pat in _REFUSAL_PATTERNS):
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
    if not _should_fallback(fallback_result):
        combined_stderr = "\n".join(
            part for part in [result.stderr.strip(), fallback_note, fallback_result.stderr.strip()] if part
        )
        return LLMResult(fallback_result.returncode, fallback_result.stdout, combined_stderr)

    # Second fallback — opencode safety net (qwen)
    model2 = _fallback_model2(fallback_provider)
    if not model2:
        combined_stderr = "\n".join(
            part for part in [result.stderr.strip(), fallback_note, fallback_result.stderr.strip()] if part
        )
        return LLMResult(fallback_result.returncode, fallback_result.stdout, combined_stderr)

    fallback2_cmd = _build_cmd(prompt, model2, output_json, allowed_tools, permission_mode, fallback_provider)
    fallback2_result = _run_cmd(fallback2_cmd, label=f"{label} fallback2", timeout=timeout, cwd=cwd)
    fallback2_note = (
        f"{fallback_note} {fallback_provider}/{fallback_model} also failed "
        f"(exit {fallback_result.returncode}); tried {fallback_provider}/{model2}."
    )
    combined_stderr = "\n".join(
        part for part in [result.stderr.strip(), fallback2_note, fallback2_result.stderr.strip()] if part
    )
    return LLMResult(fallback2_result.returncode, fallback2_result.stdout, combined_stderr)


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
    """Try parsing OpenCode JSON events and return concatenated text.

    Tolerant of truncated tails: if the stream was cut mid-line (provider
    killed by timeout), drop the partial line and return whatever text the
    earlier valid events produced — never fall back to raw JSON.
    """
    lines = raw.strip().splitlines()
    parts: list[str] = []
    saw_any_json = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not (line.startswith("{") or line.startswith("[")):
            # First non-JSON line means this isn't NDJSON at all.
            if not saw_any_json:
                return None
            # Otherwise: data after JSON events, just skip it (codex tail).
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # Truncated last line — stop parsing but keep what we got.
            if saw_any_json:
                break
            return None
        saw_any_json = True
        if not isinstance(obj, dict):
            continue
        text = _text_from_event(obj)
        if text:
            parts.append(text)
    if saw_any_json:
        return "".join(parts)
    return None


def unwrap_text(stdout: str) -> str:
    """Return model text from provider CLI output.

    Handles NDJSON (opencode --format json), JSON envelopes
    (Gemini --output-format json, Claude --output-format json),
    and raw text (Codex, opencode default, pipe-through).

    Always runs strip_tool_calls() before returning so codex tool-use
    XML never leaks downstream into tweets.
    """
    raw = (stdout or "").strip()
    if not raw:
        return ""

    ndjson_result = _unwrap_ndjson(raw)
    if ndjson_result is not None:
        return strip_tool_calls(ndjson_result)

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
                return strip_tool_calls(event_text.strip())
            return strip_tool_calls(
                str(envelope.get("response") or envelope.get("result") or raw).strip()
            )
    except (json.JSONDecodeError, TypeError):
        pass
    cleaned = strip_tool_calls(raw)
    # Final guard: if the raw looks like a stream envelope or starts with
    # `{`/`[{`, refuse to return it — caller will treat as empty and skip
    # rather than ship `{"type":"step_start",...}` as a tweet.
    if contains_post_unsafe_leak(cleaned):
        return ""
    return cleaned
