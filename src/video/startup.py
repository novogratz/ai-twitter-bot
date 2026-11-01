"""Explicit video-first activation intent; ordinary boots never create one."""
from functools import wraps
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from . import config, schedule
from .store import DATABASE

KEY = "startup_before_replies"


def arm(store, request_id, now):
    if not config.live():
        raise ValueError("video-first activation requires live video configuration")
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
        raise ValueError("a stable startup request identifier is required")
    with store.transaction() as db:
        old = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        current = json.loads(old[0]) if old else None
        if current:
            request = db.execute("SELECT state FROM startup WHERE id=?", (current["request_id"],)).fetchone()
            if (not request or request["state"] in ("pending", "reserved")
                    or current["request_id"] == request_id):
                return current  # repeated commands preserve unfinished intent/claims
        intent = {"request_id": request_id, "armed_at": now.timestamp(), "state": "waiting_checks"}
        store.put_meta(db, KEY, intent)
        return intent


def waiting_reason(store=None):
    """Read-only, including while VIDEO_ENABLED is off; unreadable state holds."""
    path = Path(store.path if store is not None else str(DATABASE)).resolve()
    if not path.exists():
        return ""
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.05)
        try:
            row = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
            intent = json.loads(row[0]) if row else None
            if not intent:
                return ""
            if not isinstance(intent, dict) or not intent.get("request_id"):
                return "video-first startup state is unreadable"
            fulfilled = db.execute("SELECT 1 FROM startup s JOIN reservations r ON r.id=s.reservation "
                "WHERE s.id=? AND s.state='posted' AND r.state='confirmed' AND r.post_id IS NOT NULL",
                (intent["request_id"],)).fetchone()
            return "" if fulfilled else "waiting for the confirmed startup video before interactions"
        finally:
            db.close()
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return "video-first startup state is unreadable"


def after_startup_video(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        if waiting_reason():
            return None
        return fn(*args, **kwargs)
    return run


def activate_when_ready(store, cfg, *, now=None, network=True):
    """Resume an explicit intent after checks pass; never fall through to Replies."""
    from . import operations, publisher
    now = now or schedule.utc_now()
    intent = store.meta(KEY)
    if not intent or not config.live() or store.meta("shutdown", False):
        return None
    # A pending, expired or ambiguous request is never replaced by another one.
    request = store.rows("SELECT * FROM startup WHERE id=?", (intent["request_id"],))
    if request and intent.get("state") == "requested":
        return request[0]
    result = operations.preflight(store, cfg, network=False)
    if result["ready_for_live"] and network:
        result = operations.preflight(store, cfg, network=True)
    if not result["ready_for_live"]:
        store.set_meta(KEY, intent | {"blockers": result["blockers"], "checked_at": now.timestamp()})
        return None
    request = publisher.request_startup(store, intent["request_id"], now, cfg, explicit_live=True)
    if request is None:
        return None
    # Persist the request before unpausing. A crash before this transaction
    # leaves the same intent recoverable, without releasing Replies early.
    with store.transaction() as db:
        store.put_meta(db, KEY, intent | {"request_id": request["id"], "state": "requested", "blockers": []})
        store.put_meta(db, "paused", False)
        store.put_meta(db, "profile_owned", True)
    return request


def tick(store, cfg, now):
    intent = store.meta(KEY)
    if not intent or intent.get("state") == "requested":
        return
    if store.meta("next_video_first_check", 0) > now:
        return
    store.set_meta("next_video_first_check", now + 30)
    activate_when_ready(store, cfg, now=datetime.fromtimestamp(now, timezone.utc))
