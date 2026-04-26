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

# Daily posting limits — bumped 5→8 each (+50%) on user directive
# 2026-04-26: more presence = more touchpoints with the FR audience.
# Floor remains 5 if quality drops; this is a ceiling lift, not a quota.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "8"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "8"))
# Quote-tweet cap (used by quote_tweet_bot) — bumped 5 → 8.
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "8"))
# Reply cap per cycle (reply_bot path) — bumped 3→5 (+50%) on user directive 2026-04-26.
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "5"))

# Accounts we never reply to (lowercase handles, no @)
BLOCKLIST = {"pgm_pm"}

# Discovered accounts file (autonomous influencer discovery)
DISCOVERED_ACCOUNTS_FILE = os.path.join(_PROJECT_ROOT, "discovered_accounts.json")

# Models
NEWS_MODEL = os.environ.get("NEWS_MODEL", "claude-opus-4-6")
REPLY_MODEL = os.environ.get("REPLY_MODEL", "claude-sonnet-4-6")
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", "claude-sonnet-4-6")

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
