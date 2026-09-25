"""The one door to the models.

Ollama over HTTP and the Codex, Gemini, Claude and OpenCode CLIs are adapters
in `ADAPTERS`; `run_llm` puts them behind one fallback ladder and reads the
answer once, in the output mode the caller's `CallProfile` declares. Callers
get the model's text or its JSON, never a provider's output.
"""
import json
import os
import re
import signal
import shutil
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional, Sequence

from . import settings
from .logger import log
from .state_store import DISPOSABLE, StateFile


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


def _contains_tool_call_leak(text: str) -> bool:
    """Returns True if the text looks like it still contains tool-call markup.

    One of the shapes contains_post_unsafe_leak refuses: markup that survives
    strip_tool_calls rejects the whole post rather than ship it half-stripped.
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


# Prompt-instruction bleed — qwen3.6 echoed "⚠️ CRITIQUE: FR_ANCHOR" verbatim
# into a posted tweet on 2026-05-15. If any of these strings survive the
# scrubber, refuse to post rather than ship instruction text as content.
_PROMPT_BLEED_MARKERS = (
    "⚠️ critique",
    "⚠️critique",
    "critique:",
    "un_seul_id",
    "interdit:",
    "hard rule",
    "<un_seul",
    "<la hot take",
    "<la news",
    "<la reply",
    "<the hot take",
    "<the news",
    "<the reply",
    "<the tweet",
    "<url article",
    "<url>",
    "language dictated above",
    "langue dictée",
    "1-2 sentences in the language",
    "output —",
    "output:",
)

# Catch-all for ANY angle-bracket template placeholder the model echoed
# (e.g. "<the hot take, 1-2 sentences …>", "<URL article>", "<PATTERN: …>").
# Real tweets don't contain "<word …>" placeholder shapes.
_PLACEHOLDER_RE = re.compile(
    r"<\s*(?:the|la|le|les|un|une|votre|your|insert|ins[eè]re|topic|sujet|"
    r"hot\s*take|news|reply|tweet|url|pattern|chiffre|number|angle|source)\b[^>\n]*>",
    re.IGNORECASE,
)


def contains_post_unsafe_leak(text: str) -> bool:
    """Pre-flight post check. True if text contains ANY leak shape — tool-call
    XML, NDJSON envelope keys, raw JSON object/array, or prompt-instruction
    text the model echoed. Tweets never legitimately match these.
    """
    if not text:
        return False
    if _contains_tool_call_leak(text):
        return True
    stripped = text.strip()
    # A tweet that opens with `{` or `[{` is a JSON shape, not a tweet.
    if stripped.startswith("{") or stripped.startswith("[{"):
        return True
    low = stripped.lower()
    if any(marker.lower() in low for marker in _STREAM_ENVELOPE_MARKERS):
        return True
    if any(marker in low for marker in _PROMPT_BLEED_MARKERS):
        return True
    if _PLACEHOLDER_RE.search(stripped):
        return True
    return False

@dataclass(frozen=True)
class ModelSetting:
    """A model setting, passed to `run_llm` in place of a model name and
    read when the call runs, for the primary CLI: its value when set and not
    blank, else that CLI's default in `settings.MODEL_DEFAULTS`. A known
    fallback never reads it: it runs LLM_FALLBACK_MODEL or its own
    *_FALLBACK_MODEL. Deriving it from AI_CLI sent `opencode/big-pickle` to
    the Claude CLI a Relation's provider forces."""
    name: str

    def for_provider(self, provider: str) -> str:
        return (settings.get(self.name) or "").strip() or settings.MODEL_DEFAULTS[self.name].get(provider, "")


@dataclass(frozen=True)
class _ModelName:
    """A model named outright: every CLI runs it."""
    name: str

    def for_provider(self, provider: str) -> str:
        return self.name


class Output(Enum):
    """How `run_llm` reads the model's answer."""
    TEXT = "text"  # post text: the leak guard empties anything unsafe to post
    JSON = "json"  # a JSON value for json.loads, found inside prose or a code fence


@dataclass(frozen=True)
class CallProfile:
    """What one kind of call asks of the model, declared by its caller: the
    output mode on every provider, the rest on the local Ollama path. The
    label never selects any of it: it only names the call in logs, fallback
    suffixes included. The default is the free-text call the Replies make."""
    ollama_model: Optional[str] = None  # None: the OLLAMA_MODEL setting
    schema: Optional[dict] = None  # sent as Ollama's `format`
    temperature: float = 1.0
    min_timeout: int = 0  # floor on the requested timeout, still capped by bedtime
    output: Output = Output.TEXT


TEXT_PROFILE = CallProfile()


def _ollama_model(profile: CallProfile) -> str:
    return profile.ollama_model or settings.get("OLLAMA_MODEL")


def _run_ollama_http(prompt: str, label: str, timeout: int,
                     profile: CallProfile, model: str) -> "LLMResult":
    """Hit ollama's /api/generate directly — simple stateless single-shot.

    Previously used /api/chat with system+user split for KV cache reuse,
    but the uncensored qwen3.6 variant returned empty `message.content`
    via that path (80 tokens generated, all stripped — model doesn't
    speak the chat template correctly). /api/generate is reliable.

    `model` is the one `run_llm` resolved from the profile; the profile sets
    the schema and temperature, the default one 1.0 for sharper outputs.
    The caller's prompt goes out as written, after the /no_think directive:
    the Voice is the caller's to render. num_predict caps generation at ~600 chars so the model doesn't
    ramble for minutes when codex/claude are unavailable. `timeout` is final:
    `_timeout` computed it.
    """
    import urllib.request
    import urllib.error
    from ..guards.active_hours import require_active
    require_active()
    full_prompt = "/no_think\n\n" + prompt
    payload = json.dumps({
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        **({"format": profile.schema} if profile.schema is not None else {}),
        "keep_alive": "24h",
        # Disable thinking-mode (qwen3.6 uncensored variants stream their
        # chain-of-thought into a separate `thinking` field while leaving
        # `response` empty; with think:false ollama runs in standard
        # generation mode and the answer lands in `response`).
        "think": False,
        "options": {
            "temperature": profile.temperature,
            "top_p": 0.95,
            "repeat_penalty": 1.15,
            # The long Décode prompts are regularly 16k-24k chars before
            # generation. Ollama's default context is too small for that on
            # many models, which can produce empty responses after a long
            # wait. Keep the window explicit and overrideable.
            "num_ctx": settings.get("OLLAMA_NUM_CTX"),
            # 2026-05-22: 256 → 1024 → 1800. Friday Top-5 Décode format
            # (5 numbered bullets with bold chiffre + acteur + insight +
            # chute + URL) needs more room. 1800 covers the long-form
            # path plus URL margin. SKIPs caused by mid-output truncation
            # were Décode #62 today.
            "num_predict": settings.get("OLLAMA_NUM_PREDICT"),
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{settings.get('OLLAMA_BASE_URL')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except urllib.error.URLError as e:
        return LLMResult(1, "", f"{label}: ollama HTTP error: {e}")
    except (json.JSONDecodeError, ValueError) as e:
        return LLMResult(1, "", f"{label}: ollama returned non-JSON: {e}")
    except TimeoutError:
        return LLMResult(124, "", f"{label}: ollama HTTP timed out after {timeout}s")
    except Exception as e:
        return LLMResult(1, "", f"{label}: ollama unexpected error: {e}")
    # /api/generate returns {"response": "..."}
    text = (data.get("response") or "").strip()
    if not text:
        meta = {
            "done": data.get("done"),
            "done_reason": data.get("done_reason"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
            "thinking_chars": len(str(data.get("thinking") or "")),
            "error": data.get("error"),
        }
        msg = f"{label}: ollama returned empty response; meta={meta}"
        log.info(f"[LLM] {msg}")
        return LLMResult(1, "", msg)
    return LLMResult(0, text, "")


class LLMStatus(Enum):
    """What a model call came to."""
    ANSWERED = "answered"  # stdout holds the answer
    FAILED = "failed"  # no usable answer; a later call may get one
    EXHAUSTED = "exhausted"  # every provider tried hit its usage limit


@dataclass
class LLMResult:
    """An adapter's raw output, or `run_llm`'s answer. `run_llm` names the
    provider and model that answered, or failed last.

    `status` means something on `run_llm`'s answer only. On an adapter's raw
    output nobody has judged yet, the return code fills it with ANSWERED or
    FAILED, which says nothing of a usage limit or of an answer `run_llm`
    would refuse: read the return code and the output there instead."""
    returncode: int
    stdout: str = ""
    stderr: str = ""
    status: Optional[LLMStatus] = None
    provider: str = ""
    model: str = ""

    def __post_init__(self):
        if self.status is None:
            self.status = LLMStatus.ANSWERED if self.returncode == 0 else LLMStatus.FAILED


# Codex usage-limit lockout cache. When codex CLI returns
# "You've hit your usage limit ... try again at May 16th, 2026 9:22 PM",
# we cache that timestamp and skip codex entirely until it passes — going
# straight to the opencode fallback. Avoids paying the 6+ min ladder cost
# every cycle when codex is locked out for days.
_CODEX_LOCKOUT = StateFile("codex_lockout.json", {}, DISPOSABLE)
_CODEX_USAGE_LIMIT_RE = re.compile(
    r"try again at (\w+)\s+(\d+)\w*,\s+(\d{4})\s+(\d+):(\d+)\s*([APap][Mm])",
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_codex_lockout_end(text: str) -> Optional[datetime]:
    """Parse 'try again at May 16th, 2026 9:22 PM' → datetime."""
    m = _CODEX_USAGE_LIMIT_RE.search(text or "")
    if not m:
        return None
    month_name, day, year, hour, minute, ampm = m.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        h = int(hour)
        if ampm.upper() == "PM" and h != 12:
            h += 12
        elif ampm.upper() == "AM" and h == 12:
            h = 0
        return datetime(int(year), month, int(day), h, int(minute))
    except (ValueError, TypeError):
        return None


def _read_codex_lockout() -> Optional[datetime]:
    """Return datetime when codex lockout expires (future), or None."""
    try:
        end = datetime.fromisoformat(_CODEX_LOCKOUT.read().get("locked_until", ""))
    except (ValueError, TypeError):
        end = None
    if end is not None and end > datetime.now():
        return end
    # Lockout window passed, or the file is unreadable: it is disposable,
    # remove it so the next LLM call does not warn again.
    try:
        os.remove(_CODEX_LOCKOUT.path)
    except OSError:
        pass
    return None


def _write_codex_lockout(end: datetime, reason: str = "usage_limit") -> None:
    _CODEX_LOCKOUT.write({
        "locked_until": end.isoformat(),
        "reason": reason,
        "stamped_at": datetime.now().isoformat(),
    })


def _detect_codex_lockout(result: "LLMResult", prompt: str) -> Optional[datetime]:
    """Return the lockout-end datetime if codex reported a usage-limit error."""
    signal = _cli_signal(result, prompt)
    if "hit your usage limit" not in signal.lower():
        return None
    parsed = _parse_codex_lockout_end(signal)
    if parsed:
        return parsed
    # Couldn't parse the precise date — assume 24h lockout as a safety floor.
    return datetime.now() + timedelta(hours=24)


def _provider() -> str:
    """The provider AI_CLI names, opencode read as Ollama. An unknown or
    uninstalled one comes back as is: its call fails by name."""
    from . import config
    requested = config.AI_CLI or "ollama"
    return "ollama" if requested == "opencode" else requested


def _build_cmd(
    prompt: str,
    model: str,
    output_json: bool,
    allowed_tools: Optional[Sequence[str]],
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
        if allowed_tools:
            # Tools requested: use yolo for headless automation
            cmd.extend(["--approval-mode", "yolo"])
        return cmd

    if provider == "opencode":
        # User mandate 2026-05-15: never pass --model to opencode. Let
        # opencode use the user's locally-configured default (qwen via
        # ollama). The `model` arg is preserved for logging upstream but
        # is intentionally ignored here.
        cmd = ["opencode", "run"]
        if allowed_tools:
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
    return cmd


def _fallback(primary: str) -> tuple[Optional[str], str]:
    """The fallback LLM_FALLBACK_CLI names behind `primary`, opencode read
    as Ollama, or None: unset, a failed call fails. None also when the named
    one is ignored, with the reason; the start reports it. An unknown name
    comes back as is, and its adapter refuses the call."""
    fallback = settings.get("LLM_FALLBACK_CLI").strip().lower()
    if settings.get("LLM_DISABLE_FALLBACK") or not fallback:
        return None, ""
    if fallback == "opencode":
        fallback = "ollama"
    if fallback not in ADAPTERS:
        return fallback, ""
    if fallback not in FALLBACKS:
        return None, f"{fallback} is never a fallback"
    if fallback != "ollama" and not shutil.which(fallback):
        return None, f"{fallback} is not installed"
    if fallback == primary == "ollama":
        # Ollama's settings come from the profile: retrying it would ask the same.
        return None, "Ollama never falls back to itself"
    if fallback == primary and not settings.get("LLM_FALLBACK_MODEL").strip():
        return None, f"it names the primary, {primary}, without LLM_FALLBACK_MODEL"
    return fallback, ""


def _fallback_model(model: "ModelSetting | _ModelName", fallback_provider: str) -> "ModelSetting | _ModelName":
    """What a CLI fallback runs: LLM_FALLBACK_MODEL, else its own
    *_FALLBACK_MODEL, never the caller's model. Ollama runs the profile's."""
    env_model = settings.get("LLM_FALLBACK_MODEL").strip()
    if env_model:
        return _ModelName(env_model)
    if fallback_provider == "codex":
        return _ModelName(_model_or_default("CODEX_FALLBACK_MODEL"))
    if fallback_provider == "gemini":
        return _ModelName(_model_or_default("GEMINI_FALLBACK_MODEL"))
    return model


def _model_or_default(name: str) -> str:
    """A fallback model setting, its default when set blank."""
    return settings.get(name).strip() or settings.DECLARED[name].default


def _run_cmd(
    cmd: list[str],
    *,
    label: str,
    timeout: int,
    cwd: Optional[str],
) -> LLMResult:
    """Run a provider CLI. `timeout` is final: `_timeout` computed it."""
    from ..guards.active_hours import require_active
    require_active()
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
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group (catches search/child workers that hold pipes)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.communicate()
            return LLMResult(124, "", f"{label} timed out after {timeout}s")
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


# A usage limit: the provider will refuse every call until it resets, unlike
# the context and refusal markers above, which concern one prompt.
_USAGE_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "quota exceeded",
    "usage limit",
    "hit your usage",
    "upgrade to pro",
    "too many requests",
    "resource_exhausted",
)


def _envelope_error(stdout: str) -> str:
    """The error a CLI's JSON output reports, even on a zero exit: Claude's
    envelope flagged `is_error`, or an NDJSON error event."""
    errors = []
    for line in (stdout or "").strip().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("is_error"):
            errors.append(str(event.get("result") or event.get("subtype") or ""))
        elif event.get("type") in ("error", "turn.failed"):
            errors.append(json.dumps(event.get("error") or event.get("message") or ""))
    return "\n".join(errors)


def _cli_signal(raw: LLMResult, prompt: str) -> str:
    """What the CLI or the transport reported about a call, never the
    model's answer: the whole output of a call that exited non-zero, or the
    error a JSON envelope flags. A post about rate limits is a common
    answer, and a common parent post: the lines of the prompt are dropped,
    since `codex exec` echoes it on stderr."""
    if raw.returncode != 0:
        text = (raw.stdout or "") + "\n" + (raw.stderr or "")
    else:
        text = _envelope_error(raw.stdout)
    echoed = {line.strip() for line in prompt.splitlines() if line.strip()}
    return "\n".join(line for line in text.splitlines() if line.strip() not in echoed)


def _usage_limit(raw: LLMResult, prompt: str) -> bool:
    signal = _cli_signal(raw, prompt).lower()
    return any(pat in signal for pat in _USAGE_LIMIT_PATTERNS)


def _should_fallback(result: LLMResult) -> bool:
    if result.returncode != 0:
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


@dataclass(frozen=True)
class _Request:
    """One call as an adapter receives it. `timeout` is the caller's request
    until `_call` replaces it with the one `_timeout` computed."""
    prompt: str
    model: str  # the one the provider runs, `_model` resolved it
    label: str
    timeout: Optional[int]
    profile: CallProfile
    output_json: bool  # the CLI's own JSON envelope, not the Output mode
    allowed_tools: Optional[Sequence[str]]
    cwd: Optional[str]


def _ollama_adapter(request: _Request) -> LLMResult:
    return _run_ollama_http(request.prompt, request.label, request.timeout, request.profile, request.model)


def _cli_adapter(provider: str) -> Callable[[_Request], LLMResult]:
    def run(request: _Request) -> LLMResult:
        if not shutil.which(provider):
            return LLMResult(127, "", f"{request.label}: {provider} is not installed; nothing was run.")
        cmd = _build_cmd(request.prompt, request.model, request.output_json,
                         request.allowed_tools, provider)
        return _run_cmd(cmd, label=request.label, timeout=request.timeout, cwd=request.cwd)
    return run


# Each adapter returns the provider's raw output; `run_llm` alone judges and
# reads it. Tests swap entries for fakes.
ADAPTERS: dict[str, Callable[[_Request], LLMResult]] = {
    "ollama": _ollama_adapter,
    **{name: _cli_adapter(name) for name in ("codex", "gemini", "claude", "opencode")},
}

# What each provider may do: every one in ADAPTERS can be the primary, these
# alone the fallback. Claude never is, and LLM_FALLBACK_CLI reads opencode as
# Ollama.
FALLBACKS = frozenset({"ollama", "codex", "gemini"})


def _unknown_adapter(provider: str) -> Callable[[_Request], LLMResult]:
    def run(request: _Request) -> LLMResult:
        return LLMResult(1, "", f"{request.label}: unknown LLM provider {provider!r}; nothing was run.")
    return run


def _adapter(provider: str) -> Callable[[_Request], LLMResult]:
    # Never a CLI for an unknown name: `_build_cmd` would send it to Claude.
    return ADAPTERS.get(provider) or _unknown_adapter(provider)


def unknown_providers() -> list[str]:
    """The provider settings that name no adapter, as `NAME='value'`, for
    the start to report: every call they route fails."""
    from . import config
    named = {
        "AI_CLI": settings.get("AI_CLI"),
        "PROFILE_LLM_PROVIDER": config.PROFILE_LLM_PROVIDER or "",
        "REPLY_LLM_PROVIDER": config.REPLY_LLM_PROVIDER or "",
        "LLM_FALLBACK_CLI": settings.get("LLM_FALLBACK_CLI"),
    }
    return [f"{name}={value!r}" for name, value in named.items()
            if value.strip() and value.strip().lower() not in ADAPTERS]


def ignored_fallbacks() -> list[str]:
    """The fallback LLM_FALLBACK_CLI names when a configured primary ignores
    it, with the primaries and the reason, for the start to report: a call
    that fails there fails."""
    from . import config
    named = settings.get("LLM_FALLBACK_CLI").strip()
    primaries = {
        "AI_CLI": _provider(),
        "PROFILE_LLM_PROVIDER": config.PROFILE_LLM_PROVIDER or "",
        "REPLY_LLM_PROVIDER": config.REPLY_LLM_PROVIDER or "",
    }
    ignored: dict[str, list[str]] = {}
    for setting, primary in primaries.items():
        primary = primary.strip().lower()
        if primary not in ADAPTERS:
            continue  # unset, or unknown and reported by `unknown_providers`
        _, reason = _fallback(primary)
        if reason:
            ignored.setdefault(reason, []).append(f"{setting}={primary!r}")
    return [f"LLM_FALLBACK_CLI={named!r} behind {', '.join(behind)}: {reason}"
            for reason, behind in ignored.items()]


# A CLI's timeout ceiling as the primary (claude, codex and gemini only),
# and as the fallback after Ollama. Any other primary CLI, and a CLI tried
# after another CLI, keeps the caller's timeout: the historical ladder did,
# and #175 changed no timeout.
_CLI_PRIMARY_CAP = 360
_CAPPED_PRIMARY_CLIS = ("claude", "codex", "gemini")
_CLI_AFTER_OLLAMA_CAP = 150


def _timeout(provider: str, requested: Optional[int], profile: CallProfile,
             after: Optional[str] = None) -> int:
    """Every model call's timeout, computed here only. `after` names the
    provider that failed before this call, None for the first call.

    Ollama is floored at the default, then at the profile's floor: caller
    timeouts tuned for codex's ~5s answers killed qwen3.6 mid-generation
    (2026-05-15: 26 replies generated, 0 posted in an hour). Every timeout
    stops at the time left before bedtime."""
    from ..guards.active_hours import seconds_until_bedtime
    default = settings.get("LLM_TIMEOUT_SECONDS")
    if provider == "ollama":
        seconds = max(requested or 0, default, profile.min_timeout)
    elif after is None and provider in _CAPPED_PRIMARY_CLIS:
        seconds = min(requested or default, _CLI_PRIMARY_CAP)
    elif after == "ollama":
        seconds = min(requested or default, _CLI_AFTER_OLLAMA_CAP)
    else:
        seconds = requested or default
    return min(seconds, max(1, int(seconds_until_bedtime())))


def _call(provider: str, request: _Request, after: Optional[str] = None) -> LLMResult:
    timeout = _timeout(provider, request.timeout, request.profile, after)
    return _adapter(provider)(replace(request, timeout=timeout))


def _model(provider: str, model: "ModelSetting | _ModelName", profile: CallProfile) -> str:
    """The model `provider` runs for this call, resolved once for the call
    and its logs."""
    if provider == "ollama":
        return _ollama_model(profile)
    if provider == "opencode":
        return ""  # its local default: `_build_cmd` never passes --model
    return model.for_provider(provider)


def _answer(provider: str, request: _Request, raw: LLMResult) -> LLMResult:
    """One call's answer, named after its provider and model: the model's
    text read in the profile's mode, or a failure with a non-zero code and
    no text, EXHAUSTED when the CLI or transport reported a usage limit."""
    model = request.model
    if _should_fallback(raw):
        reason = (raw.stderr or "").strip() or f"{request.label}: {provider} gave no usable answer"
        status = LLMStatus.EXHAUSTED if _usage_limit(raw, request.prompt) else LLMStatus.FAILED
        return LLMResult(raw.returncode or 1, "", reason, status, provider, model)
    text = _read_answer(raw.stdout, request.profile.output)
    if not text.strip():
        raw_preview = re.sub(r"\s+", " ", (raw.stdout or "").strip())[:240]
        return LLMResult(1, "", f"{request.label}: {provider} output became empty after "
                                f"safety unwrap; raw_preview={raw_preview!r}",
                         LLMStatus.FAILED, provider, model)
    return LLMResult(0, text, raw.stderr, LLMStatus.ANSWERED, provider, model)


def _describe(provider: str, request: _Request) -> str:
    if provider == "ollama":
        return f"ollama HTTP / {request.model}"
    return f"{provider}/{request.model}" if request.model else f"{provider} (its own default model)"


def run_llm(
    prompt: str,
    model: "str | ModelSetting",
    *,
    label: str,
    output_json: bool = True,
    allowed_tools: Optional[Sequence[str]] = None,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    force_provider: Optional[str] = None,
    profile: CallProfile = TEXT_PROFILE,
) -> LLMResult:
    """The model's answer, read once in `profile.output` mode whichever
    provider gave it: post text, or a JSON value ready for json.loads. A
    failure has a non-zero return code and no text. The result names the
    provider and model that answered, or failed last.

    The ladder: the primary provider (`force_provider`, else AI_CLI), then
    the fallback LLM_FALLBACK_CLI names, if any and not ignored (`_fallback`).
    An unknown provider name fails the call without running anything, and so
    does, at its rank, a CLI that is not installed. A call fails when
    `_should_fallback` says so or when its answer reads empty. A codex usage
    limit seen on this call is cached and sends the call to the fallback; a
    cached one sends it to Ollama alone. When every provider tried hit its
    usage limit, a cached codex lockout counting as one, the result is
    EXHAUSTED. `output_json` asks a CLI for its JSON envelope; it does not
    set the output mode. `model` names the primary CLI's model, or is a
    `ModelSetting` read for it; a known fallback runs its own (`_fallback_model`),
    Ollama the profile's."""
    from ..guards.active_hours import require_active
    require_active()
    primary = (force_provider or _provider()).strip().lower()
    chosen = model if isinstance(model, ModelSetting) else _ModelName(model)
    request = _Request(prompt, _model(primary, chosen, profile), label, timeout, profile,
                       output_json, allowed_tools, cwd)

    if primary == "codex":
        lockout = _read_codex_lockout()
        if lockout is not None:
            local = replace(request, model=_model("ollama", chosen, profile))
            log.info(
                f"[LLM] {label}: codex locked until "
                f"{lockout.isoformat(timespec='minutes')} — using {_describe('ollama', local)}."
            )
            return _answer("ollama", local, _call("ollama", local))

    log.info(f"[LLM] {label}: {primary} primary → {_describe(primary, request)}.")
    raw = _call(primary, request)
    locked_until = _detect_codex_lockout(raw, prompt) if primary == "codex" else None
    if locked_until is not None:
        _write_codex_lockout(locked_until)
        log.info(
            f"[LLM] Codex usage limit detected — locking out until "
            f"{locked_until.isoformat(timespec='minutes')}."
        )
        first = LLMResult(raw.returncode or 1, "", f"{label}: codex usage limit.",
                          LLMStatus.EXHAUSTED, primary, request.model)
    else:
        first = _answer(primary, request, raw)
    if first.returncode == 0 or primary not in ADAPTERS:
        return first

    fallback, _ = _fallback(primary)
    if fallback is None:
        return first
    fallback_request = replace(
        request,
        model=_model(fallback, _fallback_model(chosen, fallback), profile),
        label=f"{label} ({'codex locked' if locked_until else f'{fallback} fallback'})",
    )
    log.info(
        f"[LLM] {label}: {primary} failed (rc={first.returncode}) → "
        f"falling back to {_describe(fallback, fallback_request)}."
    )
    second = _answer(fallback, fallback_request, _call(fallback, fallback_request, after=primary))
    if second.returncode == 0:
        return second
    exhausted = first.status is LLMStatus.EXHAUSTED and second.status is LLMStatus.EXHAUSTED
    if exhausted:
        log.info(f"[LLM] {label}: {primary} and {fallback} both hit their usage limit.")
    note = f"{label}: {_describe(primary, request)} failed; tried {_describe(fallback, fallback_request)}."
    return LLMResult(second.returncode, "",
                     "\n".join(part for part in (first.stderr, note, second.stderr) if part),
                     LLMStatus.EXHAUSTED if exhausted else LLMStatus.FAILED,
                     second.provider, second.model)


def _text_from_event(obj: dict) -> str:
    if obj.get("type") == "text":
        part = obj.get("part")
        if isinstance(part, dict):
            return str(part.get("text") or "")
        return str(obj.get("text") or "")

    # Claude CLI's --output-format json envelope: {"type":"result",
    # "subtype":"success", "result":"<the text>", ...}. Without this, the
    # NDJSON parser parses the envelope but finds no recognized text key
    # and returns empty string → news + hot take silently broke when we
    # switched primary to Claude on 2026-05-15.
    if obj.get("type") == "result":
        return str(obj.get("result") or "")

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


def _provider_text(raw: str) -> str:
    """The model's text inside a provider's output: NDJSON events (opencode
    --format json), a JSON envelope (Gemini and Claude --output-format json),
    or raw text (Codex, Ollama)."""
    ndjson_result = _unwrap_ndjson(raw)
    if ndjson_result is not None:
        return ndjson_result
    try:
        envelope = json.loads(raw[raw.find("{"):] if "{" in raw else raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(envelope, dict):
        event_text = _text_from_event(envelope)
        if event_text:
            return event_text.strip()
        return str(envelope.get("response") or envelope.get("result") or raw).strip()
    return raw


_ENVELOPE_KEYS = {"type", "result", "response", "choices", "content", "message"}
_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _json_span(text: str) -> str:
    """The JSON value in the model's text: all of it, a code fence's
    content, or the span from the first bracket to the last matching one.
    Unparsable JSON comes back as is, for the caller to refuse."""
    fence = _JSON_FENCE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return text
    start = min(starts)
    end = text.rfind("]" if text[start] == "[" else "}")
    return text[start:end + 1] if end > start else text


def _read_answer(stdout: str, output: Output) -> str:
    """The one reading of a provider's output. Tool-call markup is always
    stripped. TEXT refuses, as empty, anything `contains_post_unsafe_leak`
    flags: a stream envelope or JSON shipped as a tweet (2026-05-14). JSON
    returns the model's JSON value as it stands."""
    raw = (stdout or "").strip()
    if not raw:
        return ""
    if output is Output.JSON:
        # The model's own JSON, before the NDJSON reader mistakes it for
        # events: a compact array read as a stream came back empty
        # (2026-06-05, and the reply search again until #175).
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, list) or (isinstance(value, dict) and not _ENVELOPE_KEYS & value.keys()):
            return strip_tool_calls(raw)
        return strip_tool_calls(_json_span(_provider_text(raw).strip()))
    text = strip_tool_calls(_provider_text(raw))
    return "" if contains_post_unsafe_leak(text) else text
