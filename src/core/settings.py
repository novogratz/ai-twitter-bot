"""Engine settings: each declared once, typed, bounded, read once at startup.

A setting is declared below with its name, type, default, optional floor or
ceiling, and a one-line description. `load()` reads `.env` once and resolves
every setting through these layers, the later one winning:

    declared default -> account (#202, empty until then) -> .env

The process environment still wins over `.env`, as it always has. Bounds are
applied once, after the merge: a value past its floor or ceiling is brought
back to it and listed in `startup_warnings()`, which `main.py` logs. A `.env`
key this module does not know, or a value its type rejects, stops the start
with a `SettingsError` naming the key. Changing a setting needs a restart.

`main.py` calls `load()` before any other project import, so every module and
every model call sees `.env` whatever it imports first; a script or a test
that reads a setting before that loads it on that first read.

Read a setting with `get(name)`. A side-effect switch is a function that calls
`get` when it runs, never a module constant, like `config.dry_run()`. Tests
change settings only through the `settings_override` fixture
(tests/conftest.py), which restores them.

Layout, for the migration lots of #187 working in parallel: one section per
lot, opened by a header comment and kept apart from the next by a blank line,
so no two lots edit the same hunk. A lot declares what it migrates in its own
section and drops those keys from its `_pending(...)` call there; #200 checks
nothing is left pending.
"""
import os
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
# Keys a module not migrated yet still reads from the environment itself:
# `.env` may carry them, unchecked, until their lot declares them.
PENDING: set[str] = set()
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


def _pending(*names):
    PENDING.update(names)


def _script_keys(*names):
    SCRIPT_KEYS.update(names)


# ── #195 · src/core/config.py, and keys several lots share ──────────────────
_declare("BOT_HANDLE", str, "TheAIShrink", "X handle the bot runs, without @.")
_declare("MAX_REPLIES_PER_CYCLE", int, 5, "Replies one reply cycle may ship.")
_declare("AI_CLI", str, "ollama", "Primary LLM provider: ollama, codex, gemini, opencode or claude.")
_declare("NEWS_MODEL", str, None, "Model for Originals; unset, derived from AI_CLI.")
_declare("REPLY_MODEL", str, None, "Model for Replies; unset, derived from AI_CLI.")
_declare("PRIORITY_REPLY_MODEL", str, None, "Model for priority Replies; unset, derived from AI_CLI.")
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
_declare("CONTENT_LANG_PRIMARY", str, "en", "Primary content language, en or fr (content_guard, editorial_bot).")

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
_pending(
    "DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY",
    "DUP_JACCARD_THRESHOLD",
    "DUP_CONTAINMENT_THRESHOLD",
    "DUP_SHARED_BIGRAMS",
    "DUP_TOPIC_WINDOW_HOURS",
    "DUP_TOPIC_SHARED_WORDS",
    "DUP_TEXT_WINDOW_HOURS",
    "REPLY_MIN_CHARS",
    "RATIONED_SHAPE_WINDOW_HOURS",
    "FOLLOWING_COUNT_OVERRIDE",
    "FOLLOW_MIN_FOLLOWERS",
    "FOLLOW_REQUIRE_ENGLISH",
    "FOLLOW_REQUIRE_NICHE",
    "HUMAN_TYPO_HANDLES",
    "BLANK_GRACE_AFTER_RESTART_SECONDS",
    "PROFILE_VISIT_ALLOWLIST",
    "REPLY_LIKE_PARENT_PROB",
    "NOTIFY_LIKE_REPLIES_COUNT",
)

# ── #197 · src/core ─────────────────────────────────────────────────────────
_pending(
    "OLLAMA_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_NUM_CTX",
    "OLLAMA_NUM_PREDICT",
    "LLM_TIMEOUT_SECONDS",
    "LLM_FALLBACK_CLI",
    "LLM_DISABLE_FALLBACK",
    "LLM_FALLBACK_MODEL",
    "CODEX_FALLBACK_MODEL",
    "GEMINI_FALLBACK_MODEL",
    "OPENCODE_FALLBACK_MODEL",
    "FR_FORCED_REPLY_HANDLES",
    "REPOST_MAX_AGE_HOURS",
)

# ── #198 · src/replies, src/editorial ───────────────────────────────────────
_pending(
    "EDITORIAL_OLLAMA_MODEL",
    "EDITORIAL_LLM_TIMEOUT_SECONDS",
    "DIRECT_REPLY_MAX_AGE_MINUTES",
    "BESTIE_HANDLE",
    "VIP_SCAN_HANDLES",
    "DIRECT_REPLY_MAX_PER_CYCLE",
    "DIRECT_REPLY_MAX_EN_PER_CYCLE",
    "DIRECT_REPLY_FEED_SCAN_LIMIT",
    "DIRECT_REPLY_PROFILE_SCAN_LIMIT",
    "DIRECT_REPLY_HOT_QUERY_LIMIT",
    "DIRECT_REPLY_LIVE_QUERY_LIMIT",
    "DIRECT_REPLY_QUERIES_PER_CYCLE",
    "ENABLE_DEBATES",
    "DEBATE_MAX_PER_CYCLE",
    "DEBATE_MAX_AGE_HOURS",
    "BABYSIT_WINDOW_MINUTES",
    "FEED_SWEEP_SCAN_LIMIT",
    "FEED_SWEEP_MAX_REPLIES_PER_CYCLE",
    "FEED_SWEEP_HARVEST_MIN_LIKES",
)

# ── #199 · src/account ──────────────────────────────────────────────────────
_pending(
    "PINNED_TRACKED_HANDLES",
    "CURATOR_WINDOW_DAYS",
    "CURATOR_TRACKED_MAX",
    "CURATOR_MIN_ENGAGEMENTS",
    "CURATOR_DISCOVERED_PER_DAY",
    "CURATOR_DISCOVERED_MAX",
    "CURATOR_PROMOTE_MIN_ENGAGEMENTS",
    "PIN_MIN_LIKES",
    "PIN_MAX_AGE_DAYS",
    "LIKE_TOP_TAB_PROBABILITY",
    "LIKE_BOT_PER_CYCLE",
    "LIKE_BOT_DAILY_CAP",
    "LIKE_BOT_CYCLE_SECONDS",
    "FOLLOWBACK_CAP",
    "ENABLE_FOLLOW_ENGAGERS",
    "FOLLOW_ENGAGERS_PER_DAY",
    "FOLLOW_ENGAGERS_PER_CYCLE",
)

# ── End of declarations ─────────────────────────────────────────────────────


def known_keys() -> set[str]:
    return set(DECLARED) | PENDING | SCRIPT_KEYS


def load(env_file: str | None = None, environ=None) -> None:
    """Read `.env` once, check it, resolve every setting. Later calls do nothing.

    Keys in `.env` also reach `environ` (os.environ by default) unless it
    already holds them, for the modules that still read it themselves.
    """
    global _values, _warnings
    if _values is not None:
        return
    environ = os.environ if environ is None else environ
    from_file = _read_env_file(ENV_FILE if env_file is None else env_file)
    unknown = sorted(set(from_file) - known_keys())
    if unknown:
        raise SettingsError(f"Unknown key in .env: {', '.join(unknown)}. Remove it, or declare it "
                            "in src/core/settings.py.")
    account = _account_layer()
    raw = {**from_file, **environ}
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
    warnings = []
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


def _account_layer() -> dict:
    # #202: the values of the Account's account.toml, checked like `.env`.
    return {}


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
