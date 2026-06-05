import json
import os
from datetime import datetime, timedelta
from .config import HISTORY_FILE


def load_history() -> list[dict]:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_tweet(tweet: str):
    history = load_history()
    # Idempotent: both the generating bot AND the twitter_client chokepoint
    # record posts (2026-06-05 — chokepoint recording added so EVERY surface
    # lands in the dedup corpus). Skip if this exact text is already recent.
    tweet_norm = (tweet or "").strip()
    for entry in history[-10:]:
        if isinstance(entry, dict) and (entry.get("text") or "").strip() == tweet_norm:
            return
    history.append({"text": tweet, "timestamp": datetime.now().isoformat()})
    # Keep only the last 500 entries to avoid file bloat
    history = history[-500:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


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
