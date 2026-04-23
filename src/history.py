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


# 2 AI posts for every 1 crypto/invest/gambling post
TOPIC_ROTATION = ["ai", "ai", "crypto", "ai", "ai", "invest", "ai", "ai", "gambling"]


def get_next_topic() -> str:
    """Return the next topic in the rotation. AI appears 2x more than other topics."""
    history = load_history()
    if not history:
        return "ai"
    # Count total posts to determine position in rotation
    count = len(history)
    return TOPIC_ROTATION[count % len(TOPIC_ROTATION)]
