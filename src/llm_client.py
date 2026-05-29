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
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .logger import log


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
    "output —",
    "output:",
)


def contains_post_unsafe_leak(text: str) -> bool:
    """Pre-flight post check. True if text contains ANY leak shape — tool-call
    XML, NDJSON envelope keys, raw JSON object/array, or prompt-instruction
    text the model echoed. Tweets never legitimately match these.
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
    if any(marker in low for marker in _PROMPT_BLEED_MARKERS):
        return True
    return False

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.6:35b-a3b")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


_FUNNY_FORCER = (
    "TON DE SORTIE OBLIGATOIRE: drôle, mordant, irrévérencieux. "
    "Pas d'explication. Pas de mise en garde. Pas de 'mais ça dépend'. "
    "Un constat sec + une chute qui pique. "
    "Ne sois pas seulement pertinent: cherche le vrai rire, le truc qu'on "
    "envoie dans un groupe WhatsApp avec 'mdr'. "
    "Si la punchline ressemble à une analyse LinkedIn raccourcie, recommence. "
    "Si la phrase ne te ferait pas rire à voix haute, RÉÉCRIS. "
    "Aucune phrase neutre ou bilan-prudent. Aucune méta-instruction "
    "(pas de '⚠️', 'CRITIQUE:', 'OUTPUT:', 'PATTERN:'). "
    "Tu écris UNE ligne ou DEUX max, point.\n\n"
    "Exemples du niveau attendu:\n"
    "- \"Nvidia à 4000Md. C'est le mec en soirée qui a déjà bu tout le "
    "champagne et te dit qu'il est sobre.\"\n"
    "- \"Le S&P porté par 7 méga caps, c'est pas un marché. C'est un "
    "groupe WhatsApp qui se like tout seul.\"\n\n"
    "MAINTENANT, ta tâche:\n\n"
)


# Section banners that signal "dynamic data starts here". We split the
# bot's monolithic prompts at the first one and route everything before
# into the system role (so ollama caches its KV state across calls) and
# everything after into the user role (regenerated each cycle).
_DYNAMIC_PROMPT_MARKERS = (
    "APPRENDS DE TES PERFORMANCES",
    "Performance snapshot",
    "PERFORMANCE READ",
    "EXTERNAL SIGNAL",
    "FOLLOWER GROWTH SIGNAL",
    "COMEDY PATTERN SCOREBOARD",
    "DIRECTIVES AUTONOMES",
    "INTERDIT — sujets",
    "INTERDIT - sujets",
    "Tu as déjà fait des hot takes sur",
    "Tu as déjà fait des news sur",
    "Tweets que tu as déjà écrits",
    "STORIES FRESH",
    "FRESH STORIES",
)


def _split_for_chat(prompt: str) -> tuple[str, str]:
    """Split a monolithic prompt into (stable_system, dynamic_user).
    Stable system message gets KV-cached by ollama between calls so we
    only pay tokenization for the dynamic tail. Returns ('', prompt) if
    no marker found — caller treats whole thing as user.
    """
    earliest = -1
    for marker in _DYNAMIC_PROMPT_MARKERS:
        idx = prompt.find(marker)
        if idx > 0 and (earliest == -1 or idx < earliest):
            earliest = idx
    # Need at least 1KB of stable content for caching to be worth it.
    if earliest < 1024:
        return "", prompt
    # Back up to the start of the line containing the marker.
    nl = prompt.rfind("\n", 0, earliest)
    if nl >= 0:
        earliest = nl + 1
    # Skip over banner separator lines just before (e.g. ====== or ------).
    while earliest > 0:
        prev_nl = prompt.rfind("\n", 0, earliest - 1)
        line_start = prev_nl + 1 if prev_nl >= 0 else 0
        line_content = prompt[line_start:earliest - 1].strip()
        if line_content and len(line_content) >= 3 and all(c in "=-_*" for c in line_content):
            earliest = line_start
            continue
        break
    return prompt[:earliest].rstrip(), prompt[earliest:].lstrip()


def _run_ollama_http(prompt: str, label: str, timeout: int) -> "LLMResult":
    """Hit ollama's /api/generate directly — simple stateless single-shot.

    Previously used /api/chat with system+user split for KV cache reuse,
    but the uncensored qwen3.6 variant returned empty `message.content`
    via that path (80 tokens generated, all stripped — model doesn't
    speak the chat template correctly). /api/generate is reliable.

    Front-loaded comedy forcer + temperature 1.0 for sharper outputs.
    num_predict caps generation at ~600 chars so the model doesn't
    ramble for minutes when codex/claude are unavailable.
    """
    import urllib.request
    import urllib.error
    full_prompt = _FUNNY_FORCER + "/no_think\n\n" + prompt
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "keep_alive": "24h",
        # Disable thinking-mode (qwen3.6 uncensored variants stream their
        # chain-of-thought into a separate `thinking` field while leaving
        # `response` empty; with think:false ollama runs in standard
        # generation mode and the answer lands in `response`).
        "think": False,
        "options": {
            "temperature": 1.0,
            "top_p": 0.95,
            "repeat_penalty": 1.15,
            # The long Décode prompts are regularly 16k-24k chars before
            # generation. Ollama's default context is too small for that on
            # many models, which can produce empty responses after a long
            # wait. Keep the window explicit and overrideable.
            "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "32768")),
            # 2026-05-22: 256 → 1024 → 1800. Friday Top-5 Décode format
            # (5 numbered bullets with bold chiffre + acteur + insight +
            # chute + URL) needs more room. 1800 covers the long-form
            # path plus URL margin. SKIPs caused by mid-output truncation
            # were Décode #62 today.
            "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "1800")),
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
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


@dataclass
class LLMResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


LLM_RATE_LIMIT_CODE = 75
DEFAULT_LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "180"))


# Codex usage-limit lockout cache. When codex CLI returns
# "You've hit your usage limit ... try again at May 16th, 2026 9:22 PM",
# we cache that timestamp and skip codex entirely until it passes — going
# straight to the opencode fallback. Avoids paying the 6+ min ladder cost
# every cycle when codex is locked out for days.
_CODEX_LOCKOUT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "codex_lockout.json",
)
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
        with open(_CODEX_LOCKOUT_FILE) as f:
            data = json.load(f)
        end = datetime.fromisoformat(data.get("locked_until", ""))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if end > datetime.now():
        return end
    # Lockout window passed — clean up the stale file.
    try:
        os.remove(_CODEX_LOCKOUT_FILE)
    except OSError:
        pass
    return None


def _write_codex_lockout(end: datetime, reason: str = "usage_limit") -> None:
    try:
        with open(_CODEX_LOCKOUT_FILE, "w") as f:
            json.dump(
                {
                    "locked_until": end.isoformat(),
                    "reason": reason,
                    "stamped_at": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )
    except OSError:
        pass


def _detect_codex_lockout(result: "LLMResult") -> Optional[datetime]:
    """Return the lockout-end datetime if the codex response contains a usage-limit error."""
    blob = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    if "hit your usage limit" not in blob:
        return None
    parsed = _parse_codex_lockout_end((result.stdout or "") + "\n" + (result.stderr or ""))
    if parsed:
        return parsed
    # Couldn't parse the precise date — assume 24h lockout as a safety floor.
    return datetime.now() + timedelta(hours=24)


# Claude usage-limit lockout cache, symmetric to codex. When Anthropic
# 429s us during a 2-week unattended run, retrying Claude every cycle
# burns ~30s before the fallback fires. Cache the lockout for 1 hour and
# skip Claude entirely → straight to ollama. Self-cleaning when expired.
_CLAUDE_LOCKOUT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "claude_lockout.json",
)
_CLAUDE_RATE_LIMIT_MARKERS = (
    "rate limit",
    "ratelimit",
    "rate_limit",
    "429",
    "too many requests",
    "quota exceeded",
    "anthropic usage limit",
    "you've reached your usage limit",
    "monthly usage limit",
)


def _read_claude_lockout() -> Optional[datetime]:
    try:
        with open(_CLAUDE_LOCKOUT_FILE) as f:
            data = json.load(f)
        end = datetime.fromisoformat(data.get("locked_until", ""))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if end > datetime.now():
        return end
    try:
        os.remove(_CLAUDE_LOCKOUT_FILE)
    except OSError:
        pass
    return None


def _write_claude_lockout(end: datetime, reason: str = "rate_limit") -> None:
    try:
        with open(_CLAUDE_LOCKOUT_FILE, "w") as f:
            json.dump(
                {
                    "locked_until": end.isoformat(),
                    "reason": reason,
                    "stamped_at": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )
    except OSError:
        pass


def _detect_claude_lockout(result: "LLMResult") -> Optional[datetime]:
    """If Claude returned a rate-limit / quota error, return a lockout window."""
    blob = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    if not any(m in blob for m in _CLAUDE_RATE_LIMIT_MARKERS):
        return None
    # Conservative 1h cache — Anthropic limits typically reset on the hour.
    return datetime.now() + timedelta(hours=1)


def llm_hourly_limit_status() -> tuple[bool, int, int, int]:
    """Compatibility shim: LLM budget limits are disabled."""
    return False, 0, 0, 0


def _provider() -> str:
    requested = os.environ.get("AI_CLI", "ollama").strip().lower()
    if requested in {"ollama", "opencode"}:
        return "ollama"
    if requested in {"claude", "codex", "gemini"}:
        if shutil.which(requested):
            return requested
        log.info(f"[LLM] Requested AI_CLI={requested!r} is not installed; selecting an available CLI.")
    if shutil.which("codex"):
        return "codex"
    if shutil.which("gemini"):
        return "gemini"
    if shutil.which("claude"):
        return "claude"
    return "ollama"


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
        # User mandate 2026-05-15: never pass --model to opencode. Let
        # opencode use the user's locally-configured default (qwen via
        # ollama). The `model` arg is preserved for logging upstream but
        # is intentionally ignored here.
        cmd = ["opencode", "run"]
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
    env_fallback = os.environ.get("LLM_FALLBACK_CLI", "").strip().lower()
    # Local-first content generation: when Ollama is the configured provider,
    # do not route failed generations to Codex/Claude/Gemini unless explicitly
    # allowed. This also protects older .env files with LLM_FALLBACK_CLI=codex.
    if (
        primary_provider == "ollama"
        and env_fallback not in {"", "ollama", "opencode"}
        and os.environ.get("LLM_ALLOW_REMOTE_FALLBACK", "0") != "1"
    ):
        return None
    if primary_provider == "ollama" and not env_fallback:
        return None
    default_fallback = "ollama" if primary_provider == "codex" else "codex"
    fallback = env_fallback or default_fallback
    if os.environ.get("LLM_DISABLE_FALLBACK", "0") == "1":
        return None
    if not fallback:
        return None
    if fallback == "opencode":
        fallback = "ollama"
    if fallback not in {"ollama", "claude", "codex", "gemini"}:
        return None
    if fallback != "ollama" and not shutil.which(fallback):
        return None
    # Avoid retrying the same provider as its own fallback unless the caller
    # explicitly configured a different fallback model.
    if fallback == primary_provider and not os.environ.get("LLM_FALLBACK_MODEL", "").strip():
        fallback = default_fallback
        if fallback == "opencode":
            fallback = "ollama"
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
    if fallback_provider in {"ollama", "opencode"}:
        return os.environ.get("OPENCODE_FALLBACK_MODEL", "").strip() or "opencode/big-pickle"
    return primary_model


def _fallback_model2(fallback_provider: str) -> Optional[str]:
    """Second-level fallback model — used when the first fallback also fails."""
    if fallback_provider in {"ollama", "opencode"}:
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
    force_provider: Optional[str] = None,
    structured_output: bool = False,
) -> LLMResult:
    provider = force_provider or _provider()

    # When the user has set AI_CLI=ollama/opencode, route everything through
    # the local Ollama HTTP path. The old opencode CLI subprocess path hung
    # after generation, so opencode is now just a legacy alias for Ollama.
    if provider == "ollama":
        # Caller-side timeouts (e.g. direct_reply passes 45s for VIP, 30s
        # for regular) were tuned for codex's ~5s response time and KILL
        # the local model mid-generation. Floor at DEFAULT so qwen3.6 has
        # enough room to actually finish. 2026-05-15: 26 replies generated,
        # 0 posted in one hour because every call hit the 45s wall.
        effective_timeout = max(timeout or 0, DEFAULT_LLM_TIMEOUT_SECONDS)
        log.info(
            f"[LLM] {label}: ollama primary → ollama HTTP / "
            f"{OLLAMA_MODEL} (timeout {effective_timeout}s)."
        )
        ollama_result = _run_ollama_http(prompt, label=label, timeout=effective_timeout)
        if not _should_fallback(ollama_result):
            usable = unwrap_text(ollama_result.stdout, structured_output=structured_output)
            if usable.strip():
                return LLMResult(0, usable, ollama_result.stderr)
            raw_preview = re.sub(r"\s+", " ", (ollama_result.stdout or "").strip())[:240]
            ollama_result = LLMResult(
                1,
                "",
                f"{label}: ollama output became empty after safety unwrap; raw_preview={raw_preview!r}",
            )
        # Ollama failed (empty response, timeout, error). Try the configured
        # fallback so we don't lose the cycle.
        fb_provider = _fallback_provider(provider)
        if fb_provider and fb_provider != "ollama":
            fb_model = _fallback_model(model, fb_provider)
            log.info(
                f"[LLM] {label}: ollama failed (rc={ollama_result.returncode}) → "
                f"falling back to {fb_provider}/{fb_model}."
            )
            # Cloud fallback gets the standard 150s cap (already enforced
            # for claude/codex/gemini in the cmd-runner branch below).
            fb_cmd = _build_cmd(prompt, fb_model, output_json, allowed_tools, permission_mode, fb_provider)
            fb_timeout = min(timeout or DEFAULT_LLM_TIMEOUT_SECONDS, 150)
            fb_result = _run_cmd(fb_cmd, label=f"{label} ({fb_provider} fallback)", timeout=fb_timeout, cwd=cwd)
            if not _should_fallback(fb_result):
                return fb_result
            combined_stderr = "\n".join(
                part for part in [
                    ollama_result.stderr.strip(),
                    f"{label}: ollama failed; tried {fb_provider}/{fb_model}.",
                    fb_result.stderr.strip(),
                ] if part
            )
            return LLMResult(fb_result.returncode or 1, fb_result.stdout, combined_stderr)
        return ollama_result

    # Codex usage-limit bypass: if a prior cycle cached a lockout window,
    # go straight to local Ollama HTTP.
    if provider == "codex":
        lockout = _read_codex_lockout()
        if lockout is not None:
            # Floor at DEFAULT — same reason as the opencode branch above.
            effective_timeout = max(timeout or 0, DEFAULT_LLM_TIMEOUT_SECONDS)
            log.info(
                f"[LLM] {label}: codex locked until "
                f"{lockout.isoformat(timespec='minutes')} — "
                f"using ollama HTTP / {OLLAMA_MODEL} (timeout {effective_timeout}s)."
            )
            return _run_ollama_http(prompt, label=label, timeout=effective_timeout)

    # Claude rate-limit bypass — symmetric to codex. When Anthropic 429s
    # for an extended window, skip retrying Claude every cycle and route
    # straight to ollama. Self-cleans on expiry.
    if provider == "claude":
        lockout = _read_claude_lockout()
        if lockout is not None:
            effective_timeout = max(timeout or 0, DEFAULT_LLM_TIMEOUT_SECONDS)
            log.info(
                f"[LLM] {label}: claude locked until "
                f"{lockout.isoformat(timespec='minutes')} — "
                f"using ollama HTTP / {OLLAMA_MODEL} (timeout {effective_timeout}s)."
            )
            return _run_ollama_http(prompt, label=label, timeout=effective_timeout)

    # Per-provider timeout cap — 2026-05-22 PM (durable): 360s (6 min).
    # User: "im ok to wait more bro... I just want it to work". The bot's
    # big NEWS prompt needs real headroom. 6 min lets Claude finish.
    # Ollama fallback at 30-90s catches the truly-stuck cases.
    if provider in ("claude", "codex", "gemini"):
        provider_timeout = min(timeout or DEFAULT_LLM_TIMEOUT_SECONDS, 360)
    else:
        provider_timeout = timeout
    cmd = _build_cmd(prompt, model, output_json, allowed_tools, permission_mode, provider)
    result = _run_cmd(cmd, label=label, timeout=provider_timeout, cwd=cwd)

    # If we actually ran codex this cycle and it returned a usage-limit
    # error, cache the lockout window AND collapse this cycle to a single
    # Ollama fallback call.
    if provider == "codex":
        end = _detect_codex_lockout(result)
        if end is not None:
            _write_codex_lockout(end)
            log.info(
                f"[LLM] Codex usage limit detected — locking out until "
                f"{end.isoformat(timespec='minutes')}."
            )
            fb = _fallback_provider(provider)
            if fb in {"ollama", "opencode"}:
                effective_timeout = max(timeout or 0, DEFAULT_LLM_TIMEOUT_SECONDS)
                return _run_ollama_http(prompt, label=f"{label} (codex locked)", timeout=effective_timeout)
            if fb:
                fb_model = _fallback_model(model, fb)
                fb_cmd = _build_cmd(prompt, fb_model, output_json, allowed_tools, permission_mode, fb)
                return _run_cmd(fb_cmd, label=f"{label} (codex locked)", timeout=timeout, cwd=cwd)

    # Same treatment for Claude: detect 429 / quota errors, cache a 1h
    # lockout, and immediately fall over so the cycle doesn't burn time.
    if provider == "claude":
        end = _detect_claude_lockout(result)
        if end is not None:
            _write_claude_lockout(end)
            log.info(
                f"[LLM] Claude rate-limit detected — locking out until "
                f"{end.isoformat(timespec='minutes')}."
            )
            effective_timeout = max(timeout or 0, DEFAULT_LLM_TIMEOUT_SECONDS)
            return _run_ollama_http(prompt, label=f"{label} (claude locked)", timeout=effective_timeout)

    if not _should_fallback(result):
        return result

    fallback_provider = _fallback_provider(provider)
    if not fallback_provider:
        return result

    # Ollama fallback uses the direct local HTTP path.
    if fallback_provider in {"ollama", "opencode"}:
        effective_timeout = max(timeout or 0, DEFAULT_LLM_TIMEOUT_SECONDS)
        log.info(
            f"[LLM] {label}: primary {provider}/{model} failed "
            f"(exit {result.returncode}) — falling back to ollama HTTP / "
            f"{OLLAMA_MODEL} (timeout {effective_timeout}s)."
        )
        return _run_ollama_http(prompt, label=f"{label} (fallback)", timeout=effective_timeout)

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


def unwrap_text(stdout: str, structured_output: bool = False) -> str:
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
    # Skip this guard when the caller expects structured JSON (e.g. REPLY_SEARCH).
    if not structured_output and contains_post_unsafe_leak(cleaned):
        return ""
    return cleaned
