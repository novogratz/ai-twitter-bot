import csv
import os
import re
from datetime import datetime
from .config import ENGAGEMENT_LOG_FILE


def _extract_author(target_url: str) -> str:
    """Pull @handle from a tweet URL like https://x.com/<author>/status/<id>."""
    if not target_url:
        return ""
    m = re.search(r"x\.com/([^/]+)/status/", target_url)
    return m.group(1) if m else ""


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

    # Bump personality dossier so the bot grows a relationship with each
    # account it engages. Best-effort — never block the engagement log write.
    try:
        author = _extract_author(target_url)
        if author:
            from . import personality_store
            personality_store.record_interaction(author, kind=action_type)
    except Exception:
        pass


def log_hotake(text: str, source: str = ""):
    """Log a hot take."""
    _ensure_header()
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), "hotake", text[:280], "", source])
