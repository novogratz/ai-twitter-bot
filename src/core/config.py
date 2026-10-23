"""Central configuration for the X bot of the Account BOT_ACCOUNT names.

The engine settings of src/core/settings.py keep their names here, but are
no module globals: the module `__getattr__` (PEP 562) reads each one on
every access, so a `settings_override` reaches `config.X`. Constants no
setting drives stay plain globals. A module that copies a setting with
`from config import X` keeps the value it read at import: read `config.X`
inside the function instead.

Each side-effect switch is a function read at call time, `dry_run()` and
the ones below (`follow_whitelist_only()`, `reply_llm_provider()`...); the
two provider switches also keep a constant of the same name, which calls it.
"""
import os

from . import settings, state_store

_PROJECT_ROOT = settings.PROJECT_ROOT

# dry_run() reads DRY_RUN from the environment, which `.env` reaches only
# once loaded: whoever imports this module can call it at once.
settings.load()

_READ_AT_ACCESS = {}


def _served(*names):
    for name in names:
        _READ_AT_ACCESS[name] = lambda name=name: settings.get(name)


def _served_as(name):
    def register(read):
        _READ_AT_ACCESS[name] = read
        return read
    return register


def __getattr__(name):
    try:
        read = _READ_AT_ACCESS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return read()


# Bot identity
_served("BOT_HANDLE")
_served_as("BOT_PROFILE_URL")(lambda: f"https://x.com/{settings.get('BOT_HANDLE')}")

# State files outside the state store, under state/<BOT_ACCOUNT>/
# (src/core/state_store.py)
REPLIED_FILE = state_store.StatePath("replied_tweets.json")
ENGAGEMENT_LOG_FILE = state_store.StatePath("engagement_log.csv")

# Operator policy (2026-09-23): at least three editorial posts targeted, up
# to eight profile publications per Toronto day, and uncapped replies while awake. These
# ceilings cannot be raised by stale .env files.
BOT_TIMEZONE = "America/Toronto"
MIN_TARGET_POSTS_PER_DAY = 3
TARGET_POSTS_PER_DAY = 6
MAX_PROFILE_POSTS_PER_DAY = 8
_served("MAX_REPLIES_PER_CYCLE")

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
@_served_as("AI_CLI")
def _ai_cli() -> str:
    return settings.get("AI_CLI").strip().lower()

# The CLI model of each surface is resolved by the call, for the provider it
# runs: an `llm_client.ModelSetting`, whose defaults sit in
# `settings.MODEL_DEFAULTS`. 2026-06-08 (operator): the profile surfaces get
# Opus on Claude, the reply firehose Haiku.
def _served_model(name):
    def read():
        from .llm_client import ModelSetting
        return ModelSetting(name)
    _served_as(name)(read)

_served_model("NEWS_MODEL")
_served_model("REPLY_MODEL")
_served_model("PRIORITY_REPLY_MODEL")

# Profile and reply provider overrides. Default both to Ollama, with no
# fallback: only LLM_FALLBACK_CLI (codex, say) adds one. Claude is not used by
# default. Blank means none.
@_served_as("PROFILE_LLM_PROVIDER")
def profile_llm_provider() -> str | None:
    return settings.get("PROFILE_LLM_PROVIDER").strip() or None

@_served_as("REPLY_LLM_PROVIDER")
def reply_llm_provider() -> str | None:
    return settings.get("REPLY_LLM_PROVIDER").strip() or None

# No budget limits — the bot calls the LLM freely.

# Retry settings
RETRY_DELAY_SECONDS = 5


# ---------------------------------------------------------------------------
# 2026-06-02 pivot tunables — French-language AI + Space + Stocks niche.
# Everything here is config, not hardcoded logic (per the revision mandate).
# Enforced centrally at the write chokepoints (twitter_client.post_tweet /
# reply_to_tweet / follow_account) via
# src/guards/action_guard.py + src/guards/content_guard.py. NOTE: this bot is
# Safari + AppleScript driven (no X API), so "API rate-limit / 429 backoff" maps to
# Safari write-pacing here — same intent (no bursts), different mechanism.
# ---------------------------------------------------------------------------

# Kill switch / dry-run. When 1, every write action (post, reply, follow,
# unfollow, like, quote, retweet) is LOGGED but NOT executed — run this first
# to verify the new behavior before any live writes, then set DRY_RUN=0.
# A side-effect switch, so it is read on every call, never frozen at import:
# the process environment, which `.env` reached at load, unless a test
# overrides the setting.
def dry_run() -> bool:
    if settings.is_overridden("DRY_RUN"):
        return settings.get("DRY_RUN")
    return os.environ.get("DRY_RUN", "0") == "1"

# All original surfaces share the same ceiling and at least twenty minutes
# of spacing (operator, 2026-09-23): the 09:30 and 10:00 slots sit thirty
# minutes apart and the Startup post can land next to any slot.
_served("MAX_ORIGINALS_PER_DAY", "MIN_SECONDS_BETWEEN_POSTS")

def posts_ceiling() -> int:
    """The day's ceiling of profile publications: the policy's eight, or
    MAX_ORIGINALS_PER_DAY when an Account or .env sets it lower."""
    return min(MAX_PROFILE_POSTS_PER_DAY, settings.get("MAX_ORIGINALS_PER_DAY"))

def post_targets() -> tuple[int, int]:
    """The minimum and the planned Originals of a day, neither above
    `posts_ceiling()`."""
    ceiling = posts_ceiling()
    return min(MIN_TARGET_POSTS_PER_DAY, ceiling), min(TARGET_POSTS_PER_DAY, ceiling)

# Floored at 0 in settings: a negative jitter would shorten the floor above.
_served("POST_JITTER_SECONDS")

# Replies have no daily cap. Keep browser pacing and URL dedup.
_served("MIN_SECONDS_BETWEEN_REPLIES", "REPLY_JITTER_SECONDS")

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
def follow_whitelist_only() -> bool:
    return settings.get("FOLLOW_WHITELIST_ONLY")

# Let RECIPROCAL follow-backs (people who already engage with us) through the
# whitelist-only gate (self-improve loop #3, 2026-06-24). Followback is the
# safest follower-growth loop — these are pre-qualified by engaging us, not
# random strangers — but whitelist-only was silently blocking ALL of them
# ("not on whitelist" refusals). All other gates (anti-churn, daily cap,
# spacing, following ceiling) still apply. Set 0 to re-block.
def followback_bypass_whitelist() -> bool:
    return settings.get("FOLLOWBACK_BYPASS_WHITELIST")

def follow_enforce_ratio() -> bool:
    return settings.get("FOLLOW_ENFORCE_RATIO")

_served("FOLLOW_RATIO_CEILING")  # following < 0.8 * followers
_served("FOLLOW_TOTAL_CAP")
# 2026-06-11 operator: "go back on following people and following back to
# increase viewers/likes/followers". Growth mode unties the ceiling from the
# followers count (the 06-07 following<=followers invariant would block ALL
# follows while the manual purge is mid-flight: 2485 following vs 1423
# followers). FOLLOW_TOTAL_CAP stays the hard ceiling; daily cap, jittered
# spacing, and 30-day anti-churn are untouched.
def follow_growth_mode() -> bool:
    return settings.get("FOLLOW_GROWTH_MODE")

_served("FOLLOW_LOW_PHASE_CEILING", "FOLLOW_LOW_PHASE_FOLLOWERS")
_served("MIN_SECONDS_BETWEEN_FOLLOWS", "FOLLOW_SPACING_JITTER_SECONDS", "MAX_FOLLOWS_PER_DAY")
# Anti-churn / TOS safety: never re-touch (follow↔unfollow) the same account
# within this window. Follow/unfollow cycling is a fast path to suspension.
_served("CHURN_COOLDOWN_DAYS", "FOLLOW_ACTION_JITTER_SECONDS")

# Content rules — ban short-term price targets; theses are multi-year.
def ban_short_term_price_targets() -> bool:
    return settings.get("BAN_SHORT_TERM_PRICE_TARGETS")

# Persistent, timestamped ledger of every write action (anti-churn + audit).
ACTION_LEDGER_FILE = state_store.StatePath("action_ledger.json")
