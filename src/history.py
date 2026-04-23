import json
import os
from datetime import datetime, timedelta

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "tweet_history.json")


def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_tweet(tweet: str, topic: str = "ai"):
    history = load_history()
    history.append({"text": tweet, "timestamp": datetime.now().isoformat(), "topic": topic})
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def get_recent_tweets(hours: int = 24) -> list[str]:
    """Return tweet texts from the last N hours."""
    history = load_history()
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    for entry in history:
        ts = datetime.fromisoformat(entry["timestamp"])
        if ts > cutoff:
            recent.append(entry["text"])
    return recent


def get_last_topic() -> str:
    """Return the topic of the most recent tweet ('ai' or 'crypto')."""
    history = load_history()
    if not history:
        return "crypto"  # so first post will be AI
    return history[-1].get("topic", "ai")
