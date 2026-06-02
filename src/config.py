"""Central configuration for the @AISpaceDecoder Twitter bot."""
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
BOT_HANDLE = os.environ.get("BOT_HANDLE", "AISpaceDecoder")
BOT_PROFILE_URL = f"https://x.com/{BOT_HANDLE}"

# Data file paths
HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
REPLIED_FILE = os.path.join(_PROJECT_ROOT, "replied_tweets.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
DAILY_STATE_FILE = os.path.join(_PROJECT_ROOT, "daily_state.json")

# Daily posting limits. Defaults enforce the 2026 growth mix:
# 3-5+ original posts/day minimum, led by "Le Décode" insight posts, with
# quick news takes as the secondary original surface.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "6"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "8"))
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "10"))
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "5"))

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
    "matthiasbaccino",
    "ncheron_bourse",
    "capetlevrai",
    "mathieul1",
}

# Discovered accounts file (autonomous influencer discovery)
DISCOVERED_ACCOUNTS_FILE = os.path.join(_PROJECT_ROOT, "discovered_accounts.json")

# CLI/provider selection. Default is local Ollama; set AI_CLI=codex / claude /
# gemini / opencode at the env level to switch. Claude stays supported but is
# never reached by default.
AI_CLI = os.environ.get("AI_CLI", "ollama").strip().lower()

def _default_model(codex_model: str, claude_model: str, gemini_model: str = "gemini-2.0-flash", opencode_model: str = "opencode/big-pickle") -> str:
    if AI_CLI == "codex":
        return codex_model
    if AI_CLI == "gemini":
        return gemini_model
    if AI_CLI in {"ollama", "opencode"}:
        return opencode_model
    return claude_model

# Models. Codex defaults use the Mini model across every routine surface to
# fit a Plus-plan style budget. Override NEWS_MODEL / PRIORITY_REPLY_MODEL when
# a specific cycle genuinely needs the heavier model.
# Claude defaults stay mid/cheap tier, not Opus.
NEWS_MODEL = os.environ.get("NEWS_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6", "gemini-2.0-flash"))
REPLY_MODEL = os.environ.get("REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6", "gemini-1.5-flash"))
PRIORITY_REPLY_MODEL = os.environ.get("PRIORITY_REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6", "gemini-2.0-flash"))
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6", "gemini-1.5-flash"))
ROAST_MODEL = os.environ.get("ROAST_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))

# No budget limits — the bot calls the LLM freely.

ENABLE_AI_MAINTENANCE = True
ENABLE_AI_DISCOVERY = True
ENABLE_CODEX_OPERATOR = False

# Growth optimization settings
GROWTH_ENHANCEMENT = os.environ.get("GROWTH_ENHANCEMENT", "0") == "1"
FOLLOW_BACK_RATIO = float(os.environ.get("FOLLOW_BACK_RATIO", "0.3"))
RETWEET_ENGAGEMENT_THRESHOLD = int(os.environ.get("RETWEET_ENGAGEMENT_THRESHOLD", "5"))
BOOST_ENGAGEMENT_POSTS = int(os.environ.get("BOOST_ENGAGEMENT_POSTS", "1"))

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


# ---------------------------------------------------------------------------
# 2026-06-02 pivot tunables — French-language AI + Space + Stocks niche.
# Everything here is config, not hardcoded logic (per the revision mandate).
# Enforced centrally at the write chokepoints (twitter_client.post_tweet /
# quote_tweet / reply_* / follow_account / unfollow_account) via
# src/action_guard.py + src/content_guard.py. NOTE: this bot is Safari +
# AppleScript driven (no X API), so "API rate-limit / 429 backoff" maps to
# Safari write-pacing here — same intent (no bursts), different mechanism.
# ---------------------------------------------------------------------------

# Kill switch / dry-run. When 1, every write action (post, reply, follow,
# unfollow, like, quote, retweet) is LOGGED but NOT executed — run this first
# to verify the new behavior before any live writes, then set DRY_RUN=0.
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

# Posting caps + spacing (originals = post_tweet; quotes = quote_tweet).
MAX_ORIGINALS_PER_DAY = int(os.environ.get("MAX_ORIGINALS_PER_DAY", "3"))
MAX_QUOTE_REPOSTS_PER_DAY = int(os.environ.get("MAX_QUOTE_REPOSTS_PER_DAY", "3"))
MIN_SECONDS_BETWEEN_POSTS = int(os.environ.get("MIN_SECONDS_BETWEEN_POSTS", str(45 * 60)))
POST_JITTER_SECONDS = int(os.environ.get("POST_JITTER_SECONDS", str(15 * 60)))

# Reply caps + spacing. Replies are the primary growth lever — quality over
# volume, language-matched to the parent post.
MAX_REPLIES_PER_DAY = int(os.environ.get("MAX_REPLIES_PER_DAY", "30"))
MIN_SECONDS_BETWEEN_REPLIES = int(os.environ.get("MIN_SECONDS_BETWEEN_REPLIES", "90"))
REPLY_JITTER_SECONDS = int(os.environ.get("REPLY_JITTER_SECONDS", "180"))
REPLY_LANGUAGE_MATCH = os.environ.get("REPLY_LANGUAGE_MATCH", "1") == "1"

# Following policy — whitelist-only, no reciprocity, no strangers.
# Core invariant: following must trend toward and stay BELOW followers.
FOLLOW_WHITELIST_ONLY = os.environ.get("FOLLOW_WHITELIST_ONLY", "1") == "1"
FOLLOW_RATIO_CEILING = float(os.environ.get("FOLLOW_RATIO_CEILING", "0.8"))  # following < 0.8 * followers
FOLLOWING_STEADY_STATE = int(os.environ.get("FOLLOWING_STEADY_STATE", "300"))
MAX_FOLLOWS_PER_DAY = int(os.environ.get("MAX_FOLLOWS_PER_DAY", "5"))
MAX_UNFOLLOWS_PER_DAY = int(os.environ.get("MAX_UNFOLLOWS_PER_DAY", "25"))
# Anti-churn / TOS safety: never re-touch (follow↔unfollow) the same account
# within this window. Follow/unfollow cycling is a fast path to suspension.
CHURN_COOLDOWN_DAYS = int(os.environ.get("CHURN_COOLDOWN_DAYS", "30"))
FOLLOW_ACTION_JITTER_SECONDS = int(os.environ.get("FOLLOW_ACTION_JITTER_SECONDS", "45"))

# Content rules — ban short-term price targets; theses are multi-year.
BAN_SHORT_TERM_PRICE_TARGETS = os.environ.get("BAN_SHORT_TERM_PRICE_TARGETS", "1") == "1"
CONTENT_VALIDATION_RETRIES = int(os.environ.get("CONTENT_VALIDATION_RETRIES", "3"))

# Whitelist of curated accounts (tiered). Seeded manually / from curated
# lists; the bot may SUGGEST additions for human approval but must NEVER
# auto-add. Also the source list for quote-reposts + engagement targeting.
WHITELIST_FILE = os.path.join(_PROJECT_ROOT, "whitelist.json")
# Persistent, timestamped ledger of every write action (anti-churn + audit).
ACTION_LEDGER_FILE = os.path.join(_PROJECT_ROOT, "action_ledger.json")


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
