import os

# Bot identity
BOT_HANDLE = "kzer_ai"
BOT_PROFILE_URL = f"https://x.com/{BOT_HANDLE}"

# Data file paths
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
REPLIED_FILE = os.path.join(_PROJECT_ROOT, "replied_tweets.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")

# Daily posting limits
MAX_NEWS_PER_DAY = 70
MAX_HOTAKES_PER_DAY = 20

# Models
NEWS_MODEL = "claude-opus-4-6"
REPLY_MODEL = "claude-sonnet-4-6"
HOTAKE_MODEL = "claude-sonnet-4-6"
