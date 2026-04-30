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

# Daily posting limits — RECUT 2026-04-30 PM. User: "yo news are trash...
# All you have to do is to take the biggest news in AI/crypto/bourse from
# last 36h or biggest tweets from france or english and retweet with
# sarcastic french messages.... thats all I want from you push it". So:
# standalone news/hotake is no longer the news surface — the news strategy
# IS retweet (retweet_bot, cap 16) + quote-tweet with sarcastic FR commentary
# (quote_tweet_bot, cap raised to 18). Standalone news drops to a trickle —
# only ships when a story is so big neither path can carry the joke alone.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "4"))
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

# Models — 2026-04-29 user directive ("just use opus normal 4.6 for now"):
# all generation surfaces upgraded to claude-opus-4-6. Replies are where
# we win, and the model choice matters for nuanced FR humor. News/hotake
# also benefit (better recency + reasoning) even though we cap volume hard.
NEWS_MODEL = os.environ.get("NEWS_MODEL", "claude-opus-4-6")
REPLY_MODEL = os.environ.get("REPLY_MODEL", "claude-opus-4-6")
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", "claude-opus-4-6")
# Roast + quote-tweet meme-gen don't need Sonnet — they're one-liners off a
# fixed pattern. Haiku is plenty and frees Sonnet/Opus budget for the
# news/reply/hotake paths where the model actually matters.
ROAST_MODEL = os.environ.get("ROAST_MODEL", "claude-haiku-4-5-20251001")
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", "claude-haiku-4-5-20251001")

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
