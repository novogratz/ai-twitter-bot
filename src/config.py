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

# Daily posting limits — news cut from 10 to 5 (quality > volume).
# Mediocre news posts at low engagement train the algo against us; better to
# ship 5 bangers + extra hot takes / quote-tweets than 10 fillers.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "5"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "5"))
# Quote-tweet cap (used by quote_tweet_bot) — bumped 5 → 8.
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "8"))
# Reply cap per cycle (read by reply_bot if it imports this)
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "3"))

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
