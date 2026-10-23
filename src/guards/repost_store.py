"""Permanent repost claims; uncertain submissions retain their publication budget."""
import fcntl
import os
from contextlib import contextmanager
from datetime import datetime

from ..core import account
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile, ensure_root
from ..x import x_urls
from . import active_hours

STATE = StateFile("reposted_tweets.json", {}, GUARDED)


def allowed_url(url: str) -> str:
    from .reply_admission import is_blocked_account
    url = x_urls.canonical_status_url(url)
    author = x_urls.author(url)
    if (author not in account.current().auto_engage_handles or author in account.own_handles()
            or is_blocked_account(author)):
        return ""
    return url


def entries() -> dict:
    data = STATE.read()
    try:
        for sid, entry in data.items():
            if (not sid.isdigit() or not isinstance(entry, dict)
                    or entry.get("status") not in {"pending", "shipped", "observed"}
                    or x_urls.status_id(x_urls.canonical_status_url(entry.get("url"))) != sid
                    or not datetime.fromisoformat(entry.get("ts", "")).tzinfo):
                raise ValueError("invalid repost entry")
    except (AttributeError, TypeError, ValueError) as exc:
        raise StateUnreadable("Repost history is malformed; repair reposted_tweets.json") from exc
    return data


@contextmanager
def _locked():
    with STATE._lock:
        try:
            ensure_root()
            with open(os.fspath(STATE.path) + ".lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            raise StateUnreadable("Repost history could not be locked or saved") from exc


def contains(url: str) -> bool:
    return x_urls.status_id(url) in entries()


def claim(url: str) -> bool:
    url = allowed_url(url)
    if not url:
        return False
    with _locked():
        data = entries()
        sid = x_urls.status_id(url)
        if sid in data:
            return False
        data[sid] = dict(url=url, status="pending", ts=active_hours.now_local().isoformat())
        STATE.write(data)
        return True


def remember(url: str, status: str) -> None:
    if status not in {"shipped", "observed"}:
        raise ValueError(status)
    url = x_urls.canonical_status_url(url)
    if not url:
        raise ValueError("invalid repost URL")
    with _locked():
        data = entries()
        sid = x_urls.status_id(url)
        data[sid] = dict(url=url, status=status, ts=data.get(sid, {}).get("ts", active_hours.now_local().isoformat()))
        STATE.write(data)


def release(url: str) -> None:
    """Only a proven pre-submit failure releases a claim."""
    with _locked():
        data = entries()
        sid = x_urls.status_id(url)
        if data.get(sid, {}).get("status") == "pending":
            del data[sid]
            STATE.write(data)


def pending_times() -> list[datetime]:
    return [datetime.fromisoformat(e["ts"]) for e in entries().values() if e["status"] == "pending"]


def pending_today() -> int:
    now = active_hours.now_local()
    return sum(at.astimezone(now.tzinfo).date() >= now.date() for at in pending_times())
