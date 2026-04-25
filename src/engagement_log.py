import csv
import os
from datetime import datetime
from .config import ENGAGEMENT_LOG_FILE


def _ensure_header():
    """Create CSV with 5-column header if it doesn't exist.

    Existing 4-column files are left as-is; analysis code reads positionally and
    treats a missing 5th column as an empty source string (backwards compatible).
    """
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        with open(ENGAGEMENT_LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "type", "text", "target_url", "source"])


def log_post(text: str, source: str = ""):
    """Log a posted tweet."""
    _ensure_header()
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), "post", text[:280], "", source])


def log_reply(target_url: str, reply_text: str, action_type: str = "reply", source: str = ""):
    """Log a reply or quote tweet.

    `source` is a short tag identifying which path produced this reply
    (e.g., "PROFILE-FR/MathieuL1", "SEARCH-FR-HOT/Bitcoin lang:fr"). The
    strategy agent uses this to compute per-source ROI and propose changes.
    """
    _ensure_header()
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), action_type, reply_text[:280], target_url, source])


def log_hotake(text: str, source: str = ""):
    """Log a hot take."""
    _ensure_header()
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), "hotake", text[:280], "", source])
