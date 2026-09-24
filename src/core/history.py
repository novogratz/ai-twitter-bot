from datetime import datetime, timedelta
from .state_store import GUARDED, StateFile

# The dedup corpus of published originals: losing it lets a repeat through.
HISTORY = StateFile("tweet_history.json", [], GUARDED)


def load_history() -> list[dict]:
    return HISTORY.read()


def save_tweet(tweet: str):
    # Idempotent: both the generating bot AND the twitter_client chokepoint
    # record posts (2026-06-05 — chokepoint recording added so EVERY surface
    # lands in the dedup corpus). Skip if this exact text is already recent.
    tweet_norm = (tweet or "").strip()

    def append(history):
        for entry in history[-10:]:
            if isinstance(entry, dict) and (entry.get("text") or "").strip() == tweet_norm:
                return None
        history.append({"text": tweet, "timestamp": datetime.now().isoformat()})
        # Keep only the last 500 entries to avoid file bloat
        return history[-500:]
    HISTORY.update(append)


def get_recent_tweets(hours: int = 24) -> list[str]:
    """Return tweet texts from the last N hours."""
    history = load_history()
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    for entry in history:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts > cutoff:
                recent.append(entry["text"])
        except (KeyError, ValueError):
            continue
    return recent
