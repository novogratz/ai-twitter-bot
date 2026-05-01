"""Central configuration for the @kzer_ai Twitter bot."""
import os

# Bot identity
BOT_HANDLE = "kzer_ai"
BOT_PROFILE_URL = f"https://x.com/{BOT_HANDLE}"

# Data file paths
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
REPLIED_FILE = os.path.join(_PROJECT_ROOT, "replied_tweets.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
DAILY_STATE_FILE = os.path.join(_PROJECT_ROOT, "daily_state.json")

# Daily posting limits — RECALIBRATED 2026-04-30 PM (second pass). User:
# "do more news and more retweet... 10 per day push it". After cutting news
# to 4/day earlier today the user wants more volume back on news AND retweet
# at a 10/day target. Standalone news goes 4 → 10. Retweet cap also moves
# to 10 (see retweet_bot.MAX_RETWEETS_PER_DAY). Quote-tweet stays at 18 (the
# primary news surface — biggest news + biggest viral tweets with FR
# sarcastic commentary on top).
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "10"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "6"))
# Quote-tweet cap — bumped 12 → 18. Now THE primary news surface (per user
# 2026-04-30 PM directive): biggest news from 36h or biggest viral tweets
# (FR or EN) get a sarcastic FR quote-tweet on top. Different distribution
# than replies (lands in followers' feed AND notifies original author).
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "18"))
# Reply cap per cycle — bumped 7→12→18 (2026-04-29). Replies are the ONLY
# surface earning likes/follows per user directive; volume is the move.
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "18"))

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

# CLI/provider selection. AI_CLI=auto tries Claude Code first, then Codex CLI.
AI_CLI = os.environ.get("AI_CLI", "auto")

# Models. Defaults avoid the biggest tier: Sonnet for core generation, Haiku
# for cheap one-liners/scoring. For Codex CLI, override with e.g.
# NEWS_MODEL=gpt-5.4 REPLY_MODEL=gpt-5.4 HOTAKE_MODEL=gpt-5.4 and
# QUOTE_MODEL=gpt-5.4-mini.
NEWS_MODEL = os.environ.get("NEWS_MODEL", "claude-sonnet-4-6")
REPLY_MODEL = os.environ.get("REPLY_MODEL", "claude-sonnet-4-6")
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", "claude-sonnet-4-6")
ROAST_MODEL = os.environ.get("ROAST_MODEL", "claude-haiku-4-5-20251001")
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", "claude-haiku-4-5-20251001")

# Local guardrail against scheduler bursts and provider rate limits. The
# wrapper spaces model calls and refuses new ones once the hourly budget is hit.
LLM_MIN_SECONDS_BETWEEN_CALLS = int(os.environ.get("LLM_MIN_SECONDS_BETWEEN_CALLS", "25"))
LLM_MAX_CALLS_PER_HOUR = int(os.environ.get("LLM_MAX_CALLS_PER_HOUR", "40"))

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
