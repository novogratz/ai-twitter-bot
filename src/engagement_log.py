import csv
import os
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "engagement_log.csv")


def _ensure_header():
    """Create CSV with header if it doesn't exist."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "type", "text", "target_url"])


def log_post(text: str):
    """Log a posted tweet."""
    _ensure_header()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), "post", text[:280], ""])


def log_reply(target_url: str, reply_text: str, action_type: str = "reply"):
    """Log a reply or quote tweet."""
    _ensure_header()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), action_type, reply_text[:280], target_url])


def log_hotake(text: str):
    """Log a hot take."""
    _ensure_header()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), "hotake", text[:280], ""])
