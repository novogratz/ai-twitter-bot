"""Central configuration for the @kzer_ai Twitter bot."""
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
BOT_HANDLE = "kzer_ai"
BOT_PROFILE_URL = f"https://x.com/{BOT_HANDLE}"

# Data file paths
HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
REPLIED_FILE = os.path.join(_PROJECT_ROOT, "replied_tweets.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
DAILY_STATE_FILE = os.path.join(_PROJECT_ROOT, "daily_state.json")

# Daily posting limits. Defaults are tuned for ChatGPT Plus / Codex usage:
# spend model calls on content that ships, not on background analysis.
MAX_NEWS_PER_DAY = int(os.environ.get("MAX_NEWS_PER_DAY", "6"))
MAX_HOTAKES_PER_DAY = int(os.environ.get("MAX_HOTAKES_PER_DAY", "1"))
MAX_QUOTES_PER_DAY = int(os.environ.get("MAX_QUOTES_PER_DAY", "2"))
MAX_REPLIES_PER_CYCLE = int(os.environ.get("MAX_REPLIES_PER_CYCLE", "6"))

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

# CLI/provider selection. Default is Codex for ChatGPT Plus compatibility.
# Set AI_CLI=claude to run the exact same bot via Claude Code.
AI_CLI = os.environ.get("AI_CLI", "codex").strip().lower()

def _default_model(codex_model: str, claude_model: str) -> str:
    return codex_model if AI_CLI == "codex" else claude_model

# Models. Codex defaults use the Mini model to fit a $20 Plus plan.
# Claude defaults stay mid/cheap tier, not Opus.
NEWS_MODEL = os.environ.get("NEWS_MODEL", _default_model("gpt-5.4", "claude-sonnet-4-6"))
REPLY_MODEL = os.environ.get("REPLY_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6"))
PRIORITY_REPLY_MODEL = os.environ.get("PRIORITY_REPLY_MODEL", _default_model("gpt-5.4", "claude-sonnet-4-6"))
HOTAKE_MODEL = os.environ.get("HOTAKE_MODEL", _default_model("gpt-5.4-mini", "claude-sonnet-4-6"))
ROAST_MODEL = os.environ.get("ROAST_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001"))
QUOTE_MODEL = os.environ.get("QUOTE_MODEL", _default_model("gpt-5.4-mini", "claude-haiku-4-5-20251001"))

# Local guardrail against scheduler bursts and provider rate limits. The
# wrapper spaces model calls and refuses new ones once the hourly budget is hit.
LLM_MIN_SECONDS_BETWEEN_CALLS = int(os.environ.get("LLM_MIN_SECONDS_BETWEEN_CALLS", "60"))
LLM_MAX_CALLS_PER_HOUR = int(os.environ.get("LLM_MAX_CALLS_PER_HOUR", "30"))

# Plus-safe mode: no AI for scoring, scouting, reflection, evolution, or
# account discovery unless explicitly enabled.
ENABLE_AI_MAINTENANCE = os.environ.get("ENABLE_AI_MAINTENANCE", "0") == "1"
ENABLE_AI_DISCOVERY = os.environ.get("ENABLE_AI_DISCOVERY", "0") == "1"

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
