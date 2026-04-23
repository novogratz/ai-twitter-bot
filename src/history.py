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


TOPIC_ROTATION = ["ai", "crypto", "invest", "gambling"]


def get_next_topic() -> str:
    """Return the next topic in the rotation: ai -> crypto -> invest -> gambling -> ai..."""
    history = load_history()
    if not history:
        return "ai"
    last = history[-1].get("topic", "ai")
    try:
        idx = TOPIC_ROTATION.index(last)
        return TOPIC_ROTATION[(idx + 1) % len(TOPIC_ROTATION)]
    except ValueError:
        return "ai"
