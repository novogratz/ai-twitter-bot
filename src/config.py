"""Central configuration for the @kzer_ai Twitter bot."""
import os

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")

def _load_dotenv(path: str = os.path.join(_PROJECT_ROOT, ".env")) -> None:
    """Load simple KEY=VALUE pairs without adding a dependency."""
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass

_load_dotenv()

# Bot identity
BOT_HANDLE = "kzer_ai"
BOT_PROFILE_URL = f"https://x.com/{BOT_HANDLE}"

# Data file paths
HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
REPLIED_FILE = os.path.join(_PROJECT_ROOT, "replied_tweets.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
DAILY_STATE_FILE = os.path.join(_PROJECT_ROOT, "daily_state.json")

# Daily posting limits. Defaults are tuned for ChatGPT Plus / Codex usage:
# spend model calls on content that ships, not on background analysis.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "6"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "1"))
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "2"))
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "6"))

# Accounts we never reply to. Includes both @handles AND display-name
# variants so the blocklist still catches us when the scraper returns the
# display name (e.g. "la pique" / "La Pique") instead of the @handle.
# All lowercased, no @. The scraper's user-name field can be either form
# depending on which surface we're on (replies feed vs. profile vs. search).
BLOCKLIST = {
    "pgm_pm",
    "la pique",
    "lapique",
    "la_pique",
    "la-pique",
}

# Discovered accounts file (autonomous influencer discovery)
DISCOVERED_ACCOUNTS_FILE = os.path.join(_PROJECT_ROOT, "discovered_accounts.json")

# CLI/provider selection. Default is Codex (user 2026-05-08: "use codex for the
# bot content; I'll use claude for code"). Set AI_CLI=claude / AI_CLI=gemini to
# override at the env level. Setup is the same — `codex login` to authenticate.
AI_CLI = os.environ.get("AI_CLI", "codex").strip().lower()

def _default_model(codex_model: str, claude_model: str, gemini_model: str = "gemini-2.0-flash") -> str:
    if AI_CLI == "codex":
        return codex_model
    if AI_CLI == "gemini":
        return gemini_model
    return claude_model

# Models. Codex defaults use the Mini model to fit a $20 Plus plan.
# Claude defaults stay mid/cheap tier, not Opus.
NEWS_MODEL = os.environ.get("NEWS_MODEL", _default_model("gpt-5.4", "claude-sonnet-4-6", "gemini-2.0-flash"))
REPLY_MODEL = os.environ.get("REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6", "gemini-1.5-flash"))
PRIORITY_REPLY_MODEL = os.environ.get("PRIORITY_REPLY_MODEL", _default_model("gpt-5.4", "claude-sonnet-4-6", "gemini-2.0-flash"))
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6", "gemini-1.5-flash"))
ROAST_MODEL = os.environ.get("ROAST_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))

# Local guardrail against scheduler bursts and provider rate limits. The
# wrapper spaces model calls and refuses new ones once the hourly budget is hit.
LLM_MIN_SECONDS_BETWEEN_CALLS = int(os.environ.get("LLM_MIN_SECONDS_BETWEEN_CALLS", "60"))
LLM_MAX_CALLS_PER_HOUR = int(os.environ.get("LLM_MAX_CALLS_PER_HOUR", "30"))

# Plus-safe mode: no AI for scoring, scouting, reflection, evolution, or
# account discovery unless explicitly enabled.
ENABLE_AI_MAINTENANCE = os.environ.get("ENABLE_AI_MAINTENANCE", "0") == "1"
ENABLE_AI_DISCOVERY = os.environ.get("ENABLE_AI_DISCOVERY", "0") == "1"

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


# Live strategy reader — read dynamic caps written by meta_strategy_agent.
# Bots use get_live_cap(name) instead of the static env values so the
# agent's strategic decisions actually flex behavior.
_LIVE_STRATEGY_FILE = os.path.join(_PROJECT_ROOT, "live_strategy.json")


def get_live_cap(name: str, default: int) -> int:
    """Return the live cap for `name` from live_strategy.json, or `default`
    (from env / module-level constant) if the agent hasn't run yet or the
    file is malformed. Best-effort, never raises."""
    if not os.path.exists(_LIVE_STRATEGY_FILE):
        return default
    try:
        import json as _j
        with open(_LIVE_STRATEGY_FILE, "r") as f:
            d = _j.load(f) or {}
        v = (d.get("caps") or {}).get(name)
        return int(v) if v is not None else default
    except Exception:
        return default


def get_live_cadence_factor(default: float = 1.0) -> float:
    """Live cadence multiplier (1.0 = neutral). Bots multiply their
    sleep/interval by this. < 1 = faster, > 1 = slower."""
    if not os.path.exists(_LIVE_STRATEGY_FILE):
        return default
    try:
        import json as _j
        with open(_LIVE_STRATEGY_FILE, "r") as f:
            d = _j.load(f) or {}
        v = d.get("cadence_factor")
        return float(v) if v is not None else default
    except Exception:
        return default


def get_live_topic_focus() -> list:
    """Top topics the meta-strategy agent says we should lean into.
    Empty list if agent hasn't run yet."""
    if not os.path.exists(_LIVE_STRATEGY_FILE):
        return []
    try:
        import json as _j
        with open(_LIVE_STRATEGY_FILE, "r") as f:
            d = _j.load(f) or {}
        v = d.get("topic_focus") or []
        return [str(t) for t in v][:5]
    except Exception:
        return []
