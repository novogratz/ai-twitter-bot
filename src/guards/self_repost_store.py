"""Durable one-hour and half-hour own-post schedules, including uncertain toggles."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import math
import os

from ..core import account, config
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile, ensure_root
from ..x import x_urls
from . import active_hours

STATE = StateFile("self_reposts.json", {"started": "", "posts": {}}, GUARDED)
INITIAL_DELAY = 3600
REPEAT_INTERVAL = 1800
VIEW_THRESHOLD = 50000


def read():
    data = STATE.read()
    try:
        if data["started"] and not datetime.fromisoformat(data["started"]).tzinfo:
            raise ValueError("invalid activation")
        if not isinstance(data["posts"], dict):
            raise ValueError("invalid posts")
        for sid, row in data["posts"].items():
            if (not isinstance(row, dict) or x_urls.status_id(row["url"]) != sid
                    or not x_urls.canonical_status_url(row["url"])
                    or row["phase"] not in {"idle", "undo_pending", "repost_pending"}
                    or type(row["initial_done"]) is not bool
                    or any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) or row[k] < 0
                           for k in ("first_due", "next_due", "last", "attempted"))
                    or (row["views"] is not None and (type(row["views"]) is not int or row["views"] < 0))):
                raise ValueError("invalid own repost")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StateUnreadable("Own repost history is malformed; preserve and repair self_reposts.json") from exc
    return data


@contextmanager
def locked():
    with STATE._lock:
        ensure_root()
        try:
            with open(os.fspath(STATE.path) + ".lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            raise StateUnreadable("Own repost state could not be locked or saved") from exc


def activate():
    if not account.current().self_reposts_enabled or config.dry_run():
        return
    with locked():
        data = read()
        if not data["started"]:
            data["started"] = active_hours.now_local().isoformat()
            STATE.write(data)


def observe(url, views=None):
    if not account.current().self_reposts_enabled or config.dry_run():
        return
    url = x_urls.canonical_status_url(url)
    posted = x_urls.posted_at(url)
    now = active_hours.now_local().timestamp()
    if not url or x_urls.author(url) not in account.own_handles() or not posted or posted.timestamp() > now:
        return
    with locked():
        data = read()
        if not data["started"]:
            data["started"] = active_hours.now_local().isoformat()
        sid = x_urls.status_id(url)
        if sid not in data["posts"]:
            # A recent pre-start post still receives its upcoming one-hour turn.
            initial = posted.timestamp() + INITIAL_DELAY >= datetime.fromisoformat(data["started"]).timestamp()
            data["posts"][sid] = dict(url=url, initial_done=not initial, phase="idle",
                first_due=posted.timestamp() + INITIAL_DELAY, next_due=posted.timestamp() + INITIAL_DELAY,
                last=0, attempted=0, views=None)
        row = data["posts"][sid]
        row["views"] = views if type(views) is int and views >= 0 else None
        STATE.write(data)


def due(row, now, *, views=None):
    if now < row["first_due"] or now < row["next_due"]:
        return False
    if row["phase"] != "idle":
        return True  # reconciliation only; it never grants an automatic retry
    if not row["initial_done"]:
        return True
    count = row["views"] if views is None else views
    return type(count) is int and count > VIEW_THRESHOLD


def update(url, **values):
    """Caller holds the process lock for the whole browser transaction."""
    data = read()
    data["posts"][x_urls.status_id(url)].update(values)
    STATE.write(data)


def complete(url, now):
    update(url, phase="idle", initial_done=True, last=now, next_due=now + REPEAT_INTERVAL)


def defer(url, now):
    update(url, next_due=now + 300)
