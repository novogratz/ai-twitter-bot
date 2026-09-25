"""Engine settings: each declared once, typed, bounded, read once at startup.

A setting is declared below with its name, type, default, optional floor or
ceiling, and a one-line description. `load()` reads `.env` once and resolves
every setting through these layers, the later one winning:

    declared default -> Account -> .env

The Account is accounts/<BOT_ACCOUNT>/account.toml (src/core/account.py): its
handle and language, the handle lists of its `[network]` that settings serve,
and the bounded settings its `[limits]` tightens. The process environment
still wins over `.env`, as it always has. Bounds are
applied once, after the merge, and to the Account's own values, so an Account
can only tighten a bound: a value past its floor or ceiling is brought back to
it and listed in `startup_warnings()`, which `main.py` logs. A `.env` key this
module does not know, or a value its type rejects, stops the start with a
`SettingsError` naming the key; so does a missing Account, or an unknown key
or badly typed value in its account.toml. Changing a setting needs a restart.

`main.py` calls `load()` before any other project import, so every module and
every model call sees `.env` whatever it imports first; a script or a test
that reads a setting before that loads it on that first read.

Read a setting when it is used, inside the function: `settings.get("X")`, or
`config.X` for a name src/core/config.py already serves, which it reads on
every access. Never copy one at module level, `X = settings.get("X")` or
`from ..core.config import X`: the copy keeps its import-time value and no
`settings_override` reaches it. A side-effect switch is a function that calls
`get` when it runs, like `config.dry_run()` or `config.follow_growth_mode()`.
Tests change settings only through the `settings_override` fixture
(tests/conftest.py), which restores them.

No module reads the environment but this one and `config.dry_run()`
(tests/core/test_settings.py). docs/CONFIGURATION.md carries a reference
generated from the declarations below: after changing one, run
`uv run python bin/configuration_doc.py --write`.

Layout: one section per lot of #187, opened by a header comment and kept
apart from the next by a blank line.
"""
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")


class SettingsError(SystemExit):
    """A `.env` the bot must not start with."""


@dataclass(frozen=True)
class Setting:
    name: str
    type: type
    default: object
    description: str
    floor: float | None = None
    ceiling: float | None = None


DECLARED: dict[str, Setting] = {}
# Declared settings no code reads any more: accepted so a `.env` that still
# sets them starts, documented as to remove from it.
UNUSED: set[str] = set()
# Keys the shell scripts outside the engine read after sourcing `.env`.
SCRIPT_KEYS: set[str] = set()

_values: dict | None = None
_warnings: list[str] = []
_overrides: dict = {}


def _kind(setting: Setting) -> str:
    return "0 or 1" if setting.type is bool else setting.type.__name__


def _check(setting: Setting, value):
    """A Python value for `setting`, or TypeError."""
    if value is None and setting.default is None:
        return value
    if setting.type is float and type(value) is int:
        return float(value)
    if type(value) is not setting.type:
        raise TypeError(f"{setting.name} takes {_kind(setting)}, not {value!r}")
    return value


def _bound(setting: Setting, value):
    """`value` brought back within the bounds, and a warning if it moved."""
    if setting.ceiling is not None and value > setting.ceiling:
        return setting.ceiling, f"{setting.name}={value} is above its ceiling: using {setting.ceiling}."
    if setting.floor is not None and value < setting.floor:
        return setting.floor, f"{setting.name}={value} is below its floor: using {setting.floor}."
    return value, None


def _declare(name, type_, default, description, *, floor=None, ceiling=None):
    if name in DECLARED:
        raise ValueError(f"setting {name} is declared twice")
    setting = Setting(name, type_, default, description, floor, ceiling)
    if _bound(setting, _check(setting, default))[1]:
        raise ValueError(f"setting {name}: default {default!r} is out of its bounds")
    DECLARED[name] = setting


def _declare_unused(name, type_, default):
    _declare(name, type_, default, "No effect: remove it from .env.")
    UNUSED.add(name)


def _script_keys(*names):
    SCRIPT_KEYS.update(names)


# ── #195 · src/core/config.py, and keys several lots share ──────────────────
_declare("BOT_ACCOUNT", str, "theaishrink", "Account the bot runs: the folder accounts/<name>/ holding its account.toml.")
_declare("BOT_HANDLE", str, "TheAIShrink", "X handle the bot runs, without @; the Account's handle unless set.")
_declare("MAX_REPLIES_PER_CYCLE", int, 5, "Replies one reply cycle may ship.")
_declare("AI_CLI", str, "ollama", "Primary LLM provider: ollama, codex, gemini, opencode or claude.")
_declare("NEWS_MODEL", str, None, "CLI model for Originals; unset or blank, the default of the CLI called (MODEL_DEFAULTS).")
_declare("REPLY_MODEL", str, None, "CLI model for Replies; unset or blank, the default of the CLI called (MODEL_DEFAULTS).")
_declare("PRIORITY_REPLY_MODEL", str, None, "CLI model for priority Replies; unset or blank, the default of the CLI called (MODEL_DEFAULTS).")
# The model the primary CLI runs for a model setting above left unset or
# blank. Ollama never reads them, it runs the call profile's model; nor does
# OpenCode, its own; nor a fallback, its *_FALLBACK_MODEL.
MODEL_DEFAULTS = {
    "NEWS_MODEL": {"codex": "gpt-5.4-mini", "claude": "claude-opus-4-8", "gemini": "gemini-2.0-flash"},
    "REPLY_MODEL": {"codex": "gpt-5.4-mini", "claude": "claude-haiku-4-5-20251001",
                    "gemini": "gemini-1.5-flash"},
    "PRIORITY_REPLY_MODEL": {"codex": "gpt-5.4-mini", "claude": "claude-haiku-4-5-20251001",
                             "gemini": "gemini-2.0-flash"},
}
_declare("PROFILE_LLM_PROVIDER", str, "ollama", "Provider for profile surfaces; blank means none.")
_declare("REPLY_LLM_PROVIDER", str, "ollama", "Provider for Replies; blank means none.")
_declare("DRY_RUN", bool, False, "1 logs every write instead of doing it; config.dry_run() reads it at call time.")
_declare("MAX_ORIGINALS_PER_DAY", int, 8, "Originals per Toronto day.", ceiling=8)
_declare("MIN_SECONDS_BETWEEN_POSTS", int, 1200, "Minimum gap between two Profile publications.", floor=1200)
_declare("POST_JITTER_SECONDS", int, 0, "Random delay added to the post spacing.", floor=0)
_declare("MIN_SECONDS_BETWEEN_REPLIES", int, 8, "Minimum gap between two Replies.")
_declare("REPLY_JITTER_SECONDS", int, 7, "Random delay added to the Reply spacing.")
_declare("FOLLOW_WHITELIST_ONLY", bool, True, "Follow only whitelisted accounts.")
_declare("FOLLOWBACK_BYPASS_WHITELIST", bool, True, "Let Follow-backs past the whitelist.")
_declare("FOLLOW_ENFORCE_RATIO", bool, False, "Keep following under FOLLOW_RATIO_CEILING x followers.")
_declare("FOLLOW_RATIO_CEILING", float, 0.8, "Following-to-followers ratio when the ratio is enforced.")
_declare("FOLLOW_TOTAL_CAP", int, 300, "Accounts followed in total.")
_declare("FOLLOW_GROWTH_MODE", bool, False, "Untie the following ceiling from the followers count.")
_declare("FOLLOW_LOW_PHASE_CEILING", int, 150, "Following ceiling while followers are under FOLLOW_LOW_PHASE_FOLLOWERS.")
_declare("FOLLOW_LOW_PHASE_FOLLOWERS", int, 300, "Followers count that ends the low phase.")
_declare("MIN_SECONDS_BETWEEN_FOLLOWS", int, 600, "Minimum gap between two follows.")
_declare("FOLLOW_SPACING_JITTER_SECONDS", int, 300, "Random delay added to the follow spacing.")
_declare("MAX_FOLLOWS_PER_DAY", int, 20, "Follows per day.")
_declare("CHURN_COOLDOWN_DAYS", int, 30, "Days before an account followed or unfollowed may be touched again.")
_declare("FOLLOW_ACTION_JITTER_SECONDS", int, 45, "Random pause around a follow action.")
_declare("BAN_SHORT_TERM_PRICE_TARGETS", bool, True, "Refuse text carrying a short-term price target.")
_declare("ENABLE_REPLY_SEARCH", bool, False, "Schedule the search reply job (main.py, src/replies/reply_bot.py).")
_declare("CONTENT_LANG_PRIMARY", str, "en", "Primary content language, en or fr (content_guard, editorial_bot); the Account's language unless set.")

# ── Shell scripts that source .env: operator_cycle.sh, bot_watchdog.sh ──────
_script_keys(
    "QUOTE_MODEL",
    "ROAST_MODEL",
    "LLM_MIN_SECONDS_BETWEEN_CALLS",
    "LLM_MAX_CALLS_PER_HOUR",
    "LLM_MAX_CALLS_PER_DAY",
    "ENABLE_AI_MAINTENANCE",
    "ENABLE_CODEX_OPERATOR",
    "OPERATOR_MODEL",
    "CODEX_BIN",
)

# ── #196 · src/guards, src/x ────────────────────────────────────────────────
_declare("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", int, 4, "Debate turns per Engager per Toronto day.")
_declare("DUP_JACCARD_THRESHOLD", float, 0.45, "Content-word Jaccard that makes an Original a duplicate.")
_declare("DUP_CONTAINMENT_THRESHOLD", float, 0.6, "Content-word containment that makes an Original a duplicate.")
_declare("DUP_SHARED_BIGRAMS", int, 3, "Shared content bigrams that make an Original a duplicate.")
_declare("DUP_TOPIC_WINDOW_HOURS", float, 24.0, "Hours a post counts for the same-story check.")
_declare("DUP_TOPIC_SHARED_WORDS", int, 3, "Content words shared with a same-entity post that make a same story.")
_declare("DUP_TEXT_WINDOW_HOURS", float, 48.0, "Hours a post counts for the text-similarity checks.")
_declare("REPLY_MIN_CHARS", int, 25, "Shortest Reply content_guard accepts.")
_declare("RATIONED_SHAPE_WINDOW_HOURS", int, 6, "Hours a rationed opener shape blocks its reuse.")
_declare("FOLLOWING_COUNT_OVERRIDE", str, None, "Following count the ceiling uses instead of following_count.json; digits only.")
_declare("FOLLOW_MIN_FOLLOWERS", int, 2000, "Followers a non-Engager needs to pass the follow quality gate.")
_declare("FOLLOW_REQUIRE_ENGLISH", bool, True, "Refuse to follow a profile that does not read English.")
_declare("FOLLOW_REQUIRE_NICHE", bool, True, "Refuse to follow a non-Engager whose bio is off-niche.")
_declare("HUMAN_TYPO_HANDLES", str, "", "Comma-separated handles whose Replies get a human typo.")
_declare("BLANK_GRACE_AFTER_RESTART_SECONDS", int, 120, "Seconds after a Safari restart when blank pages do not count.")
_declare("PROFILE_VISIT_ALLOWLIST", str, "", "Comma-separated profiles the scraper may visit, besides our own; the Account's network.profile_visits unless set.")
_declare("REPLY_LIKE_PARENT_PROB", float, 0.12, "Chance to like the post a Reply answers; 0 or less never.")
_declare("NOTIFY_LIKE_REPLIES_COUNT", int, 3, "Replies under our latest post the notify job likes.")

# ── #197 · src/core ─────────────────────────────────────────────────────────
_declare("OLLAMA_MODEL", str, "qwen3.6:35b-a3b", "Ollama model of a call profile that names none; bin/run.sh pre-warms it.")
_declare("OLLAMA_BASE_URL", str, "http://localhost:11434", "Ollama HTTP endpoint; bin/run.sh pre-warms there.")
_declare("OLLAMA_NUM_CTX", int, 32768, "Ollama context window, in tokens.")
_declare("OLLAMA_NUM_PREDICT", int, 1800, "Tokens Ollama may generate per call.")
_declare("LLM_TIMEOUT_SECONDS", int, 180, "Default model-call timeout, and Ollama's floor.")
_declare("LLM_FALLBACK_CLI", str, "", "Fallback provider: codex, gemini or ollama; blank means none.")
_declare("LLM_DISABLE_FALLBACK", bool, False, "1 turns the fallback off whatever LLM_FALLBACK_CLI says.")
_declare("LLM_FALLBACK_MODEL", str, "", "Model of every fallback call; blank, the fallback CLI's own below.")
_declare("CODEX_FALLBACK_MODEL", str, "gpt-5.4-mini", "Codex model as the fallback; blank means this default.")
_declare("GEMINI_FALLBACK_MODEL", str, "gemini-2.0-flash", "Gemini model as the fallback; blank means this default.")
_declare_unused("OPENCODE_FALLBACK_MODEL", str, "opencode/big-pickle")
_declare("FR_FORCED_REPLY_HANDLES", str, "Graphseo", "Comma-separated handles whose posts always get French Replies.")

# ── #198 · src/replies, src/editorial ───────────────────────────────────────
_declare("EDITORIAL_OLLAMA_MODEL", str, "gemma4:31b", "Ollama model that drafts and reviews Originals.")
_declare("EDITORIAL_LLM_TIMEOUT_SECONDS", int, 300, "Minimum timeout of an editorial model call.")
_declare("DIRECT_REPLY_MAX_AGE_MINUTES", int, 7200, "Oldest post the search and feed-sweep Replies answer.")
_declare("BESTIE_HANDLE", str, "TheBTCTherapist", "VIP account whose posts get the bestie prompt.")
_declare("VIP_SCAN_HANDLES", str, "", "Comma-separated accounts the direct_reply VIP scan answers; the Account's network.vip_scan unless set.")
_declare("DIRECT_REPLY_MAX_PER_CYCLE", int, 3, "Replies one direct_reply cycle may ship.")
_declare("DIRECT_REPLY_QUERIES_PER_CYCLE", int, 8, "Search queries one direct_reply cycle scrapes; below 1 reads as 1.")
_declare_unused("DIRECT_REPLY_MAX_EN_PER_CYCLE", int, 9999)
_declare_unused("DIRECT_REPLY_FEED_SCAN_LIMIT", int, 150)
_declare_unused("DIRECT_REPLY_PROFILE_SCAN_LIMIT", int, 25)
_declare_unused("DIRECT_REPLY_HOT_QUERY_LIMIT", int, 20)
_declare_unused("DIRECT_REPLY_LIVE_QUERY_LIMIT", int, 20)
_declare("ENABLE_DEBATES", bool, True, "Let the debate job answer mentions; read at each cycle.")
_declare("DEBATE_MAX_PER_CYCLE", int, 3, "Debate Replies one debate cycle may ship.")
_declare("DEBATE_MAX_AGE_HOURS", float, 24.0, "Oldest mention the debate job answers.")
_declare("BABYSIT_WINDOW_MINUTES", float, 60.0, "Age of the latest post under which the babysitter sweeps replybacks.")
_declare("FEED_SWEEP_SCAN_LIMIT", int, 80, "Posts the feed sweep scrapes per feed.")
_declare("FEED_SWEEP_MAX_REPLIES_PER_CYCLE", int, 8, "Reply generations one feed sweep may run per feed.")
_declare("FEED_SWEEP_HARVEST_MIN_LIKES", int, 100, "Likes that add a feed post's author to dynamic_accounts.json.")

# ── #199 · src/account ──────────────────────────────────────────────────────
_declare("PINNED_TRACKED_HANDLES", str, "",
         "Comma-separated handles the curator always tracks first (account_curator); the Account's network.pinned_tracked unless set.")
_declare("CURATOR_WINDOW_DAYS", int, 14, "Days of engagement log the curator scores.")
_declare("CURATOR_TRACKED_MAX", int, 40, "Earned accounts the curator tracks, pinned ones aside.")
_declare("CURATOR_MIN_ENGAGEMENTS", int, 3, "On-lane engagements an author needs to be tracked.")
_declare("CURATOR_DISCOVERED_PER_DAY", int, 3, "Accounts the curator may add to the whitelist discovered tier per day.")
_declare("CURATOR_DISCOVERED_MAX", int, 50, "Accounts the whitelist discovered tier holds at most.")
_declare("CURATOR_PROMOTE_MIN_ENGAGEMENTS", int, 5, "On-lane engagements an author needs to be promoted to the whitelist.")
_declare("PIN_MIN_LIKES", int, 2, "Likes an own post needs before pin_job may pin it.")
_declare("PIN_MAX_AGE_DAYS", int, 7, "Days after which a pin no longer defends its slot with the 1.3x rule.")
_declare("LIKE_TOP_TAB_PROBABILITY", float, 0.55, "Probability like_job searches the Top tab instead of Live.")
_declare("LIKE_BOT_PER_CYCLE", int, 10, "Search posts like_job hands to like_tweet per cycle.")
_declare("LIKE_BOT_DAILY_CAP", int, 500, "Likes like_job clicks per Toronto day, LIKED and UNCONFIRMED.")
_declare("LIKE_BOT_CYCLE_SECONDS", float, 30.0, "Seconds after taking the Safari lock past which like_job starts no like.")
_declare("FOLLOWBACK_CAP", int, 8, "Follow-back attempts per followback_job cycle.")
_declare("ENABLE_FOLLOW_ENGAGERS", bool, True, "Run follow_engagers_job.")
_declare("FOLLOW_ENGAGERS_PER_DAY", int, 10, "Engagers follow_engagers_job follows per Toronto day.")
_declare("FOLLOW_ENGAGERS_PER_CYCLE", int, 2, "Engagers follow_engagers_job follows per cycle.")

# ── End of declarations ─────────────────────────────────────────────────────


# Credentials and endpoints the model CLIs read from their own environment:
# `.env` may carry them for the subprocesses, the bot itself never reads them.
_CLI_PASSTHROUGH = re.compile(r"^(?:[A-Z0-9_]+_API_KEY|OLLAMA_HOST|(?:ANTHROPIC|OPENAI|GEMINI|GOOGLE|CODEX|OPENCODE)_[A-Z0-9_]+)$")


def known_keys() -> set[str]:
    return set(DECLARED) | SCRIPT_KEYS


def _is_known(key: str) -> bool:
    return key in known_keys() or bool(_CLI_PASSTHROUGH.match(key))


def load(env_file: str | None = None, environ=None) -> None:
    """Read `.env` once, check it, resolve every setting. Later calls do nothing.

    Keys in `.env` also reach `environ` (os.environ by default) unless it
    already holds them, for `config.dry_run()` and the model CLIs, which
    read it.
    """
    global _values, _warnings
    if _values is not None:
        return
    environ = os.environ if environ is None else environ
    from_file = _read_env_file(ENV_FILE if env_file is None else env_file)
    unknown = sorted(k for k in from_file if not _is_known(k))
    if unknown:
        raise SettingsError(f"Unknown key in .env: {', '.join(unknown)}. Remove it, or declare it "
                            "in src/core/settings.py.")
    raw = {**from_file, **environ}
    account, warnings = _account_layer(raw.get("BOT_ACCOUNT", DECLARED["BOT_ACCOUNT"].default))
    values, problems = {}, []
    for name, setting in DECLARED.items():
        value = account.get(name, setting.default)
        if name in raw:
            try:
                value = _parse(setting, raw[name])
            except ValueError:
                problems.append(f"{name}={raw[name]!r} (expected {_kind(setting)})")
        values[name] = value
    if problems:
        raise SettingsError(f"Bad value in .env or the environment: {'; '.join(problems)}.")
    for name, value in values.items():
        values[name], warning = _bound(DECLARED[name], value)
        if warning:
            warnings.append(warning)
    for key, value in from_file.items():
        environ.setdefault(key, value)
    _values, _warnings = values, warnings


def get(name: str):
    """The effective value of a declared setting."""
    setting = _declared(name)
    if name in _overrides:
        return _overrides[name]
    if _values is None:
        load()
    return _values[setting.name]


def is_overridden(name: str) -> bool:
    """Whether a `settings_override` holds `name`, for a setting read at call
    time from the environment, like `config.dry_run()`."""
    return _declared(name).name in _overrides


def startup_warnings() -> list[str]:
    """The values `load()` brought back to a bound."""
    return list(_warnings)


@contextmanager
def overriding():
    """Yield `override(NAME=value, ...)`; every override ends with the block.

    A value is checked against its type and bound like a `.env` value; the
    `settings_override` fixture wraps this for tests.
    """
    saved = dict(_overrides)

    def override(**values):
        for name, value in values.items():
            setting = _declared(name)
            _overrides[name] = _bound(setting, _check(setting, value))[0]

    try:
        yield override
    finally:
        _overrides.clear()
        _overrides.update(saved)


def _account_layer(name: str) -> tuple[dict, list[str]]:
    """The settings the Account `name` sets, each within its bound, and a
    warning for each value brought back to it."""
    from . import account
    loaded = account.load(name)
    layer = {"BOT_HANDLE": loaded.handle, "CONTENT_LANG_PRIMARY": loaded.language}
    # The Account's network lists, as the comma-separated settings read them.
    layer.update({"PROFILE_VISIT_ALLOWLIST": ",".join(loaded.network.profile_visits),
                  "VIP_SCAN_HANDLES": ",".join(loaded.network.vip_scan),
                  "PINNED_TRACKED_HANDLES": ",".join(loaded.network.pinned_tracked)})
    warnings = []
    for key, value in loaded.limits.items():
        setting = DECLARED.get(key)
        if setting is None or (setting.floor is None and setting.ceiling is None):
            raise account.AccountError(f"{loaded.file}: limits.{key} is not an engine setting "
                                       "with a floor or a ceiling.")
        try:
            value = _check(setting, value)
        except TypeError as exc:
            raise account.AccountError(f"{loaded.file}: limits.{exc}.") from None
        layer[key], warning = _bound(setting, value)
        if warning:
            warnings.append(f"{loaded.file}: {warning}")
    return layer, warnings


def _declared(name: str) -> Setting:
    try:
        return DECLARED[name]
    except KeyError:
        raise KeyError(f"{name} is not a declared setting") from None


def _read_env_file(path: str) -> dict:
    """KEY=VALUE lines, the first occurrence of a key winning."""
    values = {}
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key:
                    values.setdefault(key, value.strip().strip('"').strip("'"))
    except OSError:
        pass
    return values


def _parse(setting: Setting, raw: str):
    if setting.type is bool:
        if raw not in ("0", "1"):
            raise ValueError(raw)
        return raw == "1"
    return setting.type(raw)
