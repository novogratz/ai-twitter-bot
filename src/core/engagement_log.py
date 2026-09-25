import csv
import os
import re
from datetime import datetime
from .config import ENGAGEMENT_LOG_FILE
from .pattern_tags import normalize as _normalize_pattern
from .pillar_tags import classify as _classify_pillar


def _extract_author(target_url: str) -> str:
    """Pull @handle from a tweet URL like https://x.com/<author>/status/<id>."""
    if not target_url:
        return ""
    m = re.search(r"x\.com/([^/]+)/status/", target_url)
    return m.group(1) if m else ""


def _ensure_header():
    """Create CSV with 8-column header if it doesn't exist.

    Existing 4- to 7-column files are left as-is; analysis code reads
    positionally and treats missing trailing columns as empty strings
    (backwards compatible).
    Column 6 = pattern_id (REPETITION / DIALOGUE / METAPHOR / RENAME /
    FR_ANCHOR / UNDERSTATEMENT / OTHER) — drives the evolution agent's
    bandit loop. Column 7 = pillar (2026-06-07 spec content pillars, see
    pillar_tags.py) — drives the weekly mix review. Column 8 = provider
    (2026-07-19): the LLM provider configured for that surface at write
    time, so provider switches (e.g. the all-ollama move) can be judged on
    likes-per-post data instead of vibes.
    """
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        with open(ENGAGEMENT_LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "type", "text", "target_url",
                             "source", "pattern_id", "pillar", "provider"])


def _provider_for(action_type: str) -> str:
    """Best-effort provider tag, read from env at call time (the same
    call-time contract as every side-effect env). Profile surfaces run on
    PROFILE_LLM_PROVIDER; replies and everything else on the AI_CLI default.
    Config-level, not per-call — sufficient to compare eras around a switch.
    """
    profile_kinds = {"post", "hotake", "quote", "quote_gif", "breakout", "spicy"}
    if action_type in profile_kinds:
        return os.environ.get("PROFILE_LLM_PROVIDER", "claude").strip()
    return os.environ.get("AI_CLI", "ollama").strip()


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
    with open(ENGAGEMENT_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(), action_type, reply_text[:280],
            target_url, source, _normalize_pattern(pattern_id),
            _classify_pillar(reply_text, action_type, source),
            _provider_for(action_type),
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
