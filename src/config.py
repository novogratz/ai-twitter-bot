"""Central configuration for the @TheAIShrink Twitter bot."""
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
BOT_HANDLE = os.environ.get("BOT_HANDLE", "TheAIShrink")
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

# Haiku for all reply surfaces (volume, speed) — Sonnet for content creation.
# 2026-06-08 (operator): the PROFILE surfaces — new posts + quote-RTs —
# get OPUS. They're low-volume + high-stakes (they show on the profile and
# must earn the like), so the best model is worth it. The reply firehose
# (1000+/day) stays on fast/cheap haiku — it's already converting well.
# NEWS_MODEL also drives breakout_bot; HOTAKE_MODEL drives spicy_bot.
NEWS_MODEL = os.environ.get("NEWS_MODEL", _default_model("gpt-5.4-mini", "claude-opus-4-8", "gemini-2.0-flash"))
REPLY_MODEL = os.environ.get("REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))
PRIORITY_REPLY_MODEL = os.environ.get("PRIORITY_REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-2.0-flash"))
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", _default_model("gpt-5.4-mini", "claude-opus-4-8", "gemini-2.0-flash"))
ROAST_MODEL = os.environ.get("ROAST_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001", "gemini-1.5-flash"))
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", _default_model("gpt-5.4-mini", "claude-opus-4-8", "gemini-1.5-flash"))

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
# 2026-06-07 AGENT SPEC (Part 2 — Content): originals are the CONVERSION
# layer, 3-4/day anchored to US market slots (~9:30am / 12:30pm / 4-5pm /
# 8pm ET). One post per slot — never two originals within ~10-15 min (they
# cannibalize each other's reach). 2.5h+jitter spacing approximates the
# slot rhythm across all original surfaces at the chokepoint.
MAX_ORIGINALS_PER_DAY = int(os.environ.get("MAX_ORIGINALS_PER_DAY", "4"))
MIN_SECONDS_BETWEEN_POSTS = int(os.environ.get("MIN_SECONDS_BETWEEN_POSTS", str(150 * 60)))
POST_JITTER_SECONDS = int(os.environ.get("POST_JITTER_SECONDS", str(30 * 60)))

# Quote-reposts (quote-tweet-with-comment on big news) — operator-confirmed
# 2026-06-02 as the highest-ROI surface ("this works a lot"). Run it HOT:
# high daily cap + short, jittered spacing so the 4-min quote cycle actually
# produces quotes instead of getting capped out.
# 2026-06-03: GO CRAZY on quote-reposts. 30→80/day, spacing 8→3 min.
# 2026-06-05: 180s+jitter120 made the 3-min quote job miss its spacing window
# on most fires (part of the 28/day-actual vs cap gap). 120s+jitter60 lets a
# 3-min cadence mostly clear while staying jittered (no bursts). Cap 80→100.
# 2026-06-05 PM (operator: "do more quote retweet, it was extremely
# successful — abuse a bit of it for the next few weeks"): cap 100→150,
# spacing 120→90s+jitter45. Still jittered, still no bursts.
# 2026-06-07 PM-2 QRT SURGE (operator: "QRTs of relative large accounts get
# thousands of views — abuse those", measured on his own data; supersedes
# the spec's 1-2/day). High cap, 5-min jittered spacing, 300-like floor =
# large-account targeting. Quality gates (niche, dedup, 24h age, voice)
# stay absolute.
# PM-4/5: quality barbell at 60/day (operator: "totally cool if we do more
# than 40") — replies carry quantity, QRTs carry craft; SKIP gate does the
# quality work.
MAX_QUOTE_REPOSTS_PER_DAY = int(os.environ.get("MAX_QUOTE_REPOSTS_PER_DAY", "100"))
MIN_SECONDS_BETWEEN_QUOTES = int(os.environ.get("MIN_SECONDS_BETWEEN_QUOTES", "300"))
QUOTE_JITTER_SECONDS = int(os.environ.get("QUOTE_JITTER_SECONDS", "180"))
# Mega-viral carve-out (learning 2026-06-08): a 1,459-like AI viral got
# blocked purely by the daily quote cap at night. Genuinely huge AI posts
# are the highest-ROI quote targets — give them BONUS slots beyond the cap
# so the cap never blocks a top-tier viral again. Spacing still applies.
QUOTE_MEGA_VIRAL_LIKES = int(os.environ.get("QUOTE_MEGA_VIRAL_LIKES", "1000"))
QUOTE_MEGA_VIRAL_BONUS_SLOTS = int(os.environ.get("QUOTE_MEGA_VIRAL_BONUS_SLOTS", "25"))

# 2026-06-07 AGENT SPEC: the reply machine is the core engine — no volume
# cap, no daily limit. Minimum spacing kept at 8s+jitter for ban safety
# (absolute floor — X shadow-bans accounts that burst with 0s spacing; a
# Safari-driven account physically serializes anyway). Only a hard
# rate-limit pauses replies — then resume at full throttle.
MAX_REPLIES_PER_DAY = int(os.environ.get("MAX_REPLIES_PER_DAY", "999999"))
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
ENABLE_FOLLOW_BLAST = os.environ.get("ENABLE_FOLLOW_BLAST", "0") == "1"
FOLLOW_ENFORCE_RATIO = os.environ.get("FOLLOW_ENFORCE_RATIO", "0") == "1"
FOLLOW_RATIO_CEILING = float(os.environ.get("FOLLOW_RATIO_CEILING", "0.8"))  # following < 0.8 * followers
FOLLOWING_STEADY_STATE = int(os.environ.get("FOLLOWING_STEADY_STATE", "150"))
FOLLOW_TOTAL_CAP = int(os.environ.get("FOLLOW_TOTAL_CAP", "300"))
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
