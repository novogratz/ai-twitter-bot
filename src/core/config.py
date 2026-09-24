"""Central configuration for the @TheAIShrink Twitter bot."""
import os

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

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
BOT_HANDLE = os.environ.get("BOT_HANDLE", "TheAIShrink")
BOT_PROFILE_URL = f"https://x.com/{BOT_HANDLE}"

# Data file paths outside the state store (src/core/state_store.py)
REPLIED_FILE = os.path.join(_PROJECT_ROOT, "replied_tweets.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")

# Operator policy (2026-09-23): at least three editorial posts targeted, up
# to eight profile publications per Toronto day, and uncapped replies while awake. These
# ceilings cannot be raised by stale .env files or autonomous strategy data.
BOT_TIMEZONE = "America/Toronto"
MIN_TARGET_POSTS_PER_DAY = 3
TARGET_POSTS_PER_DAY = 6
MAX_PROFILE_POSTS_PER_DAY = 8
MAX_NEWS_PER_DAY = 8
MAX_HOTAKES_PER_DAY = 8
MAX_QUOTES_PER_DAY = 0
MAX_RETWEETS_PER_DAY = 0
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

# CLI/provider selection. Default is local Ollama; set AI_CLI=codex / gemini /
# opencode at the env level to switch. Claude is no longer a default route.
AI_CLI = os.environ.get("AI_CLI", "ollama").strip().lower()

def _default_model(
    codex_model: str,
    claude_model: str,
    gemini_model: str = "gemini-2.0-flash",
    opencode_model: str = "opencode/big-pickle",
) -> str:
    if AI_CLI == "codex":
        return codex_model
    if AI_CLI == "gemini":
        return gemini_model
    if AI_CLI in {"ollama", "opencode"}:
        return opencode_model
    return codex_model

# Haiku for all reply surfaces (volume, speed) — Sonnet for content creation.
# 2026-06-08 (operator): the PROFILE surfaces — new posts + quote-RTs —
# get OPUS. They're low-volume + high-stakes (they show on the profile and
# must earn the like), so the best model is worth it. The reply firehose
# (1000+/day) stays on fast/cheap haiku — it's already converting well.
NEWS_MODEL = os.environ.get("NEWS_MODEL", _default_model("gpt-5.4-mini", "claude-opus-4-8", "gemini-2.0-flash"))
REPLY_MODEL = os.environ.get("REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))
PRIORITY_REPLY_MODEL = os.environ.get("PRIORITY_REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-2.0-flash"))
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", _default_model("gpt-5.4-mini", "claude-opus-4-8", "gemini-2.0-flash"))

# Profile and reply provider overrides. Default both to Ollama; Codex is the
# cloud fallback when explicitly enabled. Claude is not used by default.
PROFILE_LLM_PROVIDER = os.environ.get("PROFILE_LLM_PROVIDER", "ollama").strip() or None
REPLY_LLM_PROVIDER = os.environ.get("REPLY_LLM_PROVIDER", "ollama").strip() or None

# No budget limits — the bot calls the LLM freely.

# Autonomous self-modification — OFF by default (operator 2026-06-21:
# "disactivate the self improvement stuff, keep it static"). These drive the
# meta_strategy / evolution / reflection / scout agents that rewrite caps,
# prompts, personality, and the tracked-account list. Static = no drift.
# Re-enable per-flag via .env only if explicitly wanted.
ENABLE_AI_MAINTENANCE = os.environ.get("ENABLE_AI_MAINTENANCE", "0") == "1"
ENABLE_AI_DISCOVERY = os.environ.get("ENABLE_AI_DISCOVERY", "0") == "1"
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
# reply_* / follow_account / unfollow_account) via
# src/guards/action_guard.py + src/guards/content_guard.py. NOTE: this bot is
# Safari + AppleScript driven (no X API), so "API rate-limit / 429 backoff" maps to
# Safari write-pacing here — same intent (no bursts), different mechanism.
# ---------------------------------------------------------------------------

# Kill switch / dry-run. When 1, every write action (post, reply, follow,
# unfollow, like, quote, retweet) is LOGGED but NOT executed — run this first
# to verify the new behavior before any live writes, then set DRY_RUN=0.
# A side-effect switch, so it is read on every call, never frozen at import.
def dry_run() -> bool:
    return os.environ.get("DRY_RUN", "0") == "1"

# All original surfaces share the same ceiling and at least twenty minutes
# of spacing (operator, 2026-09-23): the 09:30 and 10:00 slots sit thirty
# minutes apart and the Startup post can land next to any slot.
MAX_ORIGINALS_PER_DAY = min(8, int(os.environ.get("MAX_ORIGINALS_PER_DAY", "8")))
MIN_SECONDS_BETWEEN_POSTS = max(1200, int(os.environ.get("MIN_SECONDS_BETWEEN_POSTS", "1200")))
# A negative jitter would shorten the floor above.
POST_JITTER_SECONDS = max(0, int(os.environ.get("POST_JITTER_SECONDS", "0")))

# Automatic quotes, reposts and recycling are retired. Legacy callers still
# encounter these hard limits, including urgent/mega-viral bypass attempts.
MAX_QUOTE_REPOSTS_PER_DAY = 0
MIN_SECONDS_BETWEEN_QUOTES = 3600
QUOTE_JITTER_SECONDS = 0
QUOTE_MEGA_VIRAL_LIKES = 1000
QUOTE_MEGA_VIRAL_BONUS_SLOTS = 0

# 0 explicitly means unlimited replies. Keep browser pacing and URL dedup.
MAX_REPLIES_PER_DAY = 0
MIN_SECONDS_BETWEEN_REPLIES = int(os.environ.get("MIN_SECONDS_BETWEEN_REPLIES", "8"))
REPLY_JITTER_SECONDS = int(os.environ.get("REPLY_JITTER_SECONDS", "7"))
REPLY_LANGUAGE_MATCH = os.environ.get("REPLY_LANGUAGE_MATCH", "1") == "1"

# Following policy (2026-06-07 AGENT SPEC, Part 1 — rebuild from near-zero
# after the full purge). Following is a tool for exactly two things: curating
# reply targets and signaling the lane. Hard constraints, never violated:
#   - Total following cap 300 (FOLLOW_TOTAL_CAP); steady-state ~120-150.
#   - While followers < FOLLOW_LOW_PHASE_FOLLOWERS (300), stay under the
#     credible ~150 following (FOLLOW_LOW_PHASE_CEILING). Once followers
#     exceed it, keep following <= followers.
#   - Max 20 follows/day, randomized gaps >= 10 min (MIN_SECONDS_BETWEEN_
#     FOLLOWS + FOLLOW_SPACING_JITTER_SECONDS). Never burst-follow.
#   - Whitelist-only: the tiered seed list in whitelist.json (tier1 foils →
#     tier4 crypto/markets). Discovery candidates go to suggestions[] for
#     human approval — the bot never auto-adds.
#   - 30-day anti-churn stays ON; no follow→unfollow cycles.
FOLLOW_WHITELIST_ONLY = os.environ.get("FOLLOW_WHITELIST_ONLY", "1") == "1"
# Let RECIPROCAL follow-backs (people who already engage with us) through the
# whitelist-only gate (self-improve loop #3, 2026-06-24). Followback is the
# safest follower-growth loop — these are pre-qualified by engaging us, not
# random strangers — but whitelist-only was silently blocking ALL of them
# ("not on whitelist" refusals). All other gates (anti-churn, daily cap,
# spacing, following ceiling) still apply. Set 0 to re-block.
FOLLOWBACK_BYPASS_WHITELIST = os.environ.get("FOLLOWBACK_BYPASS_WHITELIST", "1") == "1"
FOLLOW_ENFORCE_RATIO = os.environ.get("FOLLOW_ENFORCE_RATIO", "0") == "1"
FOLLOW_RATIO_CEILING = float(os.environ.get("FOLLOW_RATIO_CEILING", "0.8"))  # following < 0.8 * followers
FOLLOWING_STEADY_STATE = int(os.environ.get("FOLLOWING_STEADY_STATE", "150"))
FOLLOW_TOTAL_CAP = int(os.environ.get("FOLLOW_TOTAL_CAP", "300"))
# 2026-06-11 operator: "go back on following people and following back to
# increase viewers/likes/followers". Growth mode unties the ceiling from the
# followers count (the 06-07 following<=followers invariant would block ALL
# follows while the manual purge is mid-flight: 2485 following vs 1423
# followers). FOLLOW_TOTAL_CAP stays the hard ceiling; daily cap, jittered
# spacing, and 30-day anti-churn are untouched.
FOLLOW_GROWTH_MODE = os.environ.get("FOLLOW_GROWTH_MODE", "0") == "1"
FOLLOW_LOW_PHASE_CEILING = int(os.environ.get("FOLLOW_LOW_PHASE_CEILING", "150"))
FOLLOW_LOW_PHASE_FOLLOWERS = int(os.environ.get("FOLLOW_LOW_PHASE_FOLLOWERS", "300"))
MIN_SECONDS_BETWEEN_FOLLOWS = int(os.environ.get("MIN_SECONDS_BETWEEN_FOLLOWS", "600"))
FOLLOW_SPACING_JITTER_SECONDS = int(os.environ.get("FOLLOW_SPACING_JITTER_SECONDS", "300"))
MAX_FOLLOWS_PER_DAY = int(os.environ.get("MAX_FOLLOWS_PER_DAY", "20"))
# 0 = unfollowing OFF in the bot (operator 2026-06-07: manual unfollows only).
MAX_UNFOLLOWS_PER_DAY = int(os.environ.get("MAX_UNFOLLOWS_PER_DAY", "0"))
# Anti-churn / TOS safety: never re-touch (follow↔unfollow) the same account
# within this window. Follow/unfollow cycling is a fast path to suspension.
CHURN_COOLDOWN_DAYS = int(os.environ.get("CHURN_COOLDOWN_DAYS", "30"))
FOLLOW_ACTION_JITTER_SECONDS = int(os.environ.get("FOLLOW_ACTION_JITTER_SECONDS", "45"))

# Content rules — ban short-term price targets; theses are multi-year.
BAN_SHORT_TERM_PRICE_TARGETS = os.environ.get("BAN_SHORT_TERM_PRICE_TARGETS", "1") == "1"
CONTENT_VALIDATION_RETRIES = int(os.environ.get("CONTENT_VALIDATION_RETRIES", "3"))

# ⛔ HARD FRESHNESS RULE — operator mandate 2026-06-02, NEVER CHANGE THIS,
# not even via autonomous maintenance. We NEVER reshare (retweet) or
# quote-repost content older than 48h. The value is CLAMPED to 48: even if an
# env var or an agent tries to set it higher, it can never exceed 48h. Any
# candidate whose age can't be determined is treated as STALE and skipped.
# Enforced in retweet_bot (feed + trusted-handle paths) and quote_tweet_bot.
REPOST_MAX_AGE_HOURS = min(48, int(os.environ.get("REPOST_MAX_AGE_HOURS", "48")))

# Whitelist of curated accounts (tiered). Seeded manually / from curated
# lists; the bot may SUGGEST additions for human approval but must NEVER
# auto-add. Also the source list for quote-reposts + engagement targeting.
WHITELIST_FILE = os.path.join(_PROJECT_ROOT, "whitelist.json")
# Persistent, timestamped ledger of every write action (anti-churn + audit).
ACTION_LEDGER_FILE = os.path.join(_PROJECT_ROOT, "action_ledger.json")


# Live strategy reader — read dynamic caps written by meta_strategy_agent.
# Bots use get_live_cap(name) instead of the static env values so the
# agent's strategic decisions actually flex behavior.
def _live_strategy() -> dict:
    from .live_strategy import LIVE_STRATEGY
    return LIVE_STRATEGY.read()


def get_live_cap(name: str, default: int) -> int:
    """Return the live cap for `name` from live_strategy.json, or `default`
    (from env / module-level constant) if the agent hasn't run yet or the
    file is malformed. Best-effort, never raises."""
    fixed = {
        "MAX_QUOTES_PER_DAY": 0, "MAX_QUOTE_REPOSTS_PER_DAY": 0,
        "MAX_RETWEETS_PER_DAY": 0, "MAX_REPLIES_PER_DAY": 0,
        "MAX_ORIGINALS_PER_DAY": MAX_ORIGINALS_PER_DAY,
        "MAX_NEWS_PER_DAY": 8, "MAX_HOTAKES_PER_DAY": 8,
    }
    if name in fixed:
        return fixed[name]
    try:
        v = (_live_strategy().get("caps") or {}).get(name)
        return int(v) if v is not None else default
    except Exception:
        return default


def get_live_cadence_factor(default: float = 1.0) -> float:
    """Live cadence multiplier (1.0 = neutral). Bots multiply their
    sleep/interval by this. < 1 = faster, > 1 = slower."""
    try:
        v = _live_strategy().get("cadence_factor")
        return float(v) if v is not None else default
    except Exception:
        return default


def get_live_topic_focus() -> list:
    """Top topics the meta-strategy agent says we should lean into.
    Empty list if agent hasn't run yet."""
    try:
        v = _live_strategy().get("topic_focus") or []
        return [str(t) for t in v][:5]
    except Exception:
        return []
