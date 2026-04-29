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

# Daily posting limits — bumped 12→24 (2x) per user directive 2026-04-26 PM
# "post 2 times more" — bot stagnating at 260 followers, 2-week mission
# targeting 1k. News format also converted to meme-hot-take + URL (see
# agent.py PROMPT_TEMPLATE). Quality stays gated by impact filter +
# first-derivative rule. This is a CEILING lift so the bot can fire
# through both EU and EST peaks without choking.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "24"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "24"))
# Quote-tweet cap — bumped 8 → 12. Different distribution surface than
# replies (lands in followers' feed AND notifies original author),
# so additive growth, not redundant volume.
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "12"))
# Reply cap per cycle — 3→5→7 over user directives 2026-04-26.
# User flagged stagnation at 260 followers; bumping volume + pruning dead
# sources (Frandroid/Boursorama/CoinTribuneFR) to make every cycle land more.
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "12"))

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

# Models
NEWS_MODEL = os.environ.get("NEWS_MODEL", "claude-sonnet-4-6")
REPLY_MODEL = os.environ.get("REPLY_MODEL", "claude-sonnet-4-6")
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", "claude-sonnet-4-6")
# Roast + quote-tweet meme-gen don't need Sonnet — they're one-liners off a
# fixed pattern. Haiku is plenty and frees Sonnet/Opus budget for the
# news/reply/hotake paths where the model actually matters.
ROAST_MODEL = os.environ.get("ROAST_MODEL", "claude-haiku-4-5-20251001")
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", "claude-haiku-4-5-20251001")

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
