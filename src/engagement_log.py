import csv
import os
import re
from datetime import datetime
from .config import ENGAGEMENT_LOG_FILE
from .pattern_tags import normalize as _normalize_pattern
from .pillar_tags import classify as _classify_pillar


# The only legitimate values for the `type` column written via log_reply.
# Anything else (pattern ids like METAPHOR/RENAME, or a leaked LLM JSON
# "type" field) corrupts the per-action ROI math that the analyzer, bandit
# and engine-health watchdog all read positionally — see memory
# reply-bot-type-field-leak. Sanitize at this single chokepoint so no caller
# can pollute the column, regardless of a positional-arg mistake upstream.
_KNOWN_REPLY_ACTIONS = {"reply", "quote", "retweet", "quote_gif", "repost"}


def _sanitize_action_type(action_type: str) -> str:
    """Coerce an unknown/leaked action type back to the safe default."""
    at = (action_type or "").strip()
    return at if at in _KNOWN_REPLY_ACTIONS else "reply"


def _extract_author(target_url: str) -> str:
    """Pull @handle from a tweet URL like https://x.com/<author>/status/<id>."""
    if not target_url:
        return ""
    m = re.search(r"x\.com/([^/]+)/status/", target_url)
    return m.group(1) if m else ""


def _ensure_header():
    """Create CSV with 7-column header if it doesn't exist.

    Existing 4-, 5- or 6-column files are left as-is; analysis code reads
    positionally and treats missing trailing columns as empty strings
    (backwards compatible).
    Column 6 = pattern_id (REPETITION / DIALOGUE / METAPHOR / RENAME /
    FR_ANCHOR / UNDERSTATEMENT / OTHER) — drives the evolution agent's
    bandit loop. Column 7 = pillar (2026-06-07 spec content pillars, see
    pillar_tags.py) — drives the weekly mix review.
    """
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        with open(ENGAGEMENT_LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "type", "text", "target_url",
                             "source", "pattern_id", "pillar"])


def log_post(text: str, source: str = "", pattern_id: str = ""):
    """Log a posted tweet."""
    _ensure_header()
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(), "post", text[:280], "",
            source, _normalize_pattern(pattern_id),
            _classify_pillar(text, "post", source),
        ])


def log_reply(target_url: str, reply_text: str, action_type: str = "reply",
              source: str = "", pattern_id: str = ""):
    """Log a reply or quote tweet.

    `source` is a short tag identifying which path produced this reply
    (e.g., "PROFILE-FR/MathieuL1", "SEARCH-FR-HOT/Bitcoin lang:fr"). The
    strategy agent uses this to compute per-source ROI and propose changes.
    `pattern_id` is the comedy-pattern bucket (see pattern_tags.py) — drives
    the per-pattern ROI signal the evolution agent uses to rewrite its
    style guide.
    """
    _ensure_header()
    action_type = _sanitize_action_type(action_type)
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(), action_type, reply_text[:280],
            target_url, source, _normalize_pattern(pattern_id),
            _classify_pillar(reply_text, action_type, source),
        ])

    # Bump personality dossier so the bot grows a relationship with each
    # account it engages. Best-effort — never block the engagement log write.
    try:
        author = _extract_author(target_url)
        if author:
            from . import personality_store
            personality_store.record_interaction(author, kind=action_type)
    except Exception:
        pass


def log_hotake(text: str, source: str = "", pattern_id: str = ""):
    """Log a hot take."""
    _ensure_header()
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(), "hotake", text[:280], "",
            source, _normalize_pattern(pattern_id),
            _classify_pillar(text, "hotake", source),
        ])
