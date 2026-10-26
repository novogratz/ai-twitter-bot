import csv
import os
import re
import threading
from collections import deque
from datetime import datetime
from . import config
from .pattern_tags import normalize as _normalize_pattern
from .pillar_tags import classify as _classify_pillar

_MEMORY_LOCK = threading.RLock()
_memory_key = None
_memory = deque(maxlen=40)


def _log_key():
    path = os.fspath(config.ENGAGEMENT_LOG_FILE)
    try:
        stat = os.stat(path)
        return path, stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return path, 0, 0


def recent_replies(limit: int = 20) -> list[str]:
    """Confirmed text only, oldest first. Old CSV headers may have four columns.

    Reload once on startup or an external append; our own appends update the
    small cache directly. A large history is not rescanned for every draft.
    """
    global _memory_key
    with _MEMORY_LOCK:
        key = _log_key()
        if key != _memory_key:
            _memory.clear()
            if key[2]:
                with open(key[0], newline="") as handle:
                    for row in csv.reader(handle):
                        if len(row) >= 4 and row[1] == "reply":
                            _memory.append(row[2])
            _memory_key = key
        return list(_memory)[-max(1, limit):]


def _extract_author(target_url: str) -> str:
    """Pull @handle from a tweet URL like https://x.com/<author>/status/<id>."""
    if not target_url:
        return ""
    m = re.search(r"x\.com/([^/]+)/status/", target_url)
    return m.group(1) if m else ""


def _ensure_header():
    """Create CSV with 10-column header if it doesn't exist.

    Existing 4- to 9-column files are left as-is; analysis code reads
    positionally and treats missing trailing columns as empty strings
    (backwards compatible).
    Column 6 = pattern_id (REPETITION / DIALOGUE / METAPHOR / RENAME /
    FR_ANCHOR / UNDERSTATEMENT / OTHER) — drives the evolution agent's
    bandit loop. Column 7 = pillar (2026-06-07 spec content pillars, see
    pillar_tags.py) — drives the weekly mix review. Columns 8 and 9 =
    provider and model (2026-07-19, model 2026-09-24): the ones that
    actually wrote the text, fallback included, as the model's answer names
    them, so provider switches (e.g. the all-ollama move) can be judged on
    likes-per-post data instead of vibes. Rows written before 2026-09-24
    tag the provider configured for the surface instead.
    """
    if not os.path.exists(config.ENGAGEMENT_LOG_FILE):
        with open(config.ENGAGEMENT_LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "type", "text", "target_url",
                             "source", "pattern_id", "pillar", "provider", "model", "published_url"])


def log_reply(target_url: str, reply_text: str, action_type: str = "reply",
              source: str = "", pattern_id: str = "", provider: str = "", model: str = "",
              parent_text: str = ""):
    """Log a reply or quote tweet.

    `source` is a short tag identifying which path produced this reply
    (e.g., "PROFILE-FR/MathieuL1", "SEARCH-FR-HOT/Bitcoin lang:fr"). The
    strategy agent uses this to compute per-source ROI and propose changes.
    `pattern_id` is the comedy-pattern bucket (see pattern_tags.py) — drives
    the per-pattern ROI signal the evolution agent uses to rewrite its
    style guide. `provider` and `model` name who wrote the reply, as the
    model's answer reported them.
    """
    global _memory_key
    from . import reply_feedback
    with _MEMORY_LOCK:
        recent_replies()
        _ensure_header()
        with open(config.ENGAGEMENT_LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(), action_type, reply_text[:280],
                target_url, source, _normalize_pattern(pattern_id),
                _classify_pillar(reply_text, action_type, source),
                provider, model, reply_feedback.publication_url(target_url) if action_type == "reply" else "",
            ])
        if action_type == "reply":
            _memory.append(reply_text[:280])
        _memory_key = _log_key()

    if action_type == "reply":
        try:
            reply_feedback.annotate(target_url, source=source, provider=provider, model=model,
                                    topic=reply_feedback.topic(parent_text))
        except Exception:
            # Analytics failure must never make a shipped Reply retryable.
            from .logger import log
            log.exception("[REPLY-FEEDBACK] Could not annotate shipped Reply %s", target_url)

    # Bump personality dossier so the bot grows a relationship with each
    # account it engages. Best-effort — never block the engagement log write.
    try:
        author = _extract_author(target_url)
        if author:
            from . import personality_store
            personality_store.record_interaction(author, kind=action_type)
    except Exception:
        pass
