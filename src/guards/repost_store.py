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
# Operator ceiling, independent of the broader discovery/watch list.
ALLOWED_AUTHOR = "elonmusk"
DAILY_CAP = 2


def allowed_url(url: str) -> str:
    from .reply_admission import is_blocked_account
    url = x_urls.canonical_status_url(url)
    author = x_urls.author(url)
    if (author != ALLOWED_AUTHOR or author not in account.current().auto_engage_handles or author in account.own_handles()
            or is_blocked_account(author)):
        return ""
    return url


def entries() -> dict:
    data = STATE.read()
    try:
        for sid, entry in data.items():
            if not isinstance(sid, str) or not sid.isdigit():
                raise ValueError("invalid repost ID")
            # Legacy confirmed IDs remain permanently claimed. They contain
            # no URL or time; never invent either or rewrite them on read.
            if entry == "confirmed":
                continue
            if (not isinstance(entry, dict)
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


def used_today(data=None) -> int:
    """Count receipts plus unreceipted reservations; never count a send twice."""
    from . import action_guard as guard
    now, ledger = active_hours.now_local(), guard._ledger()
    used = ledger.count(guard.RETWEET, now.date())
    receipted = {x_urls.status_id(url) for url in ledger.targets(guard.RETWEET)
                 if ledger.count(guard.RETWEET, now.date(), url)}
    for sid, entry in (entries() if data is None else data).items():
        if entry == "confirmed":
            continue  # Legacy undated IDs remain deduplication evidence only.
        at = datetime.fromisoformat(entry["ts"]).astimezone(now.tzinfo)
        if at.date() >= now.date() and sid not in receipted:
            used += 1
    return used


def budget_refusal() -> str:
    return "daily repost cap reached, including uncertain sends (2)" if used_today() >= DAILY_CAP else ""


def claim(url: str) -> bool:
    url = allowed_url(url)
    if not url:
        return False
    with _locked():
        data = entries()
        sid = x_urls.status_id(url)
        if sid in data or used_today(data) >= DAILY_CAP:
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
        if data.get(sid) == "confirmed":
            return
        data[sid] = dict(url=url, status=status, ts=data.get(sid, {}).get("ts", active_hours.now_local().isoformat()))
        STATE.write(data)


def release(url: str) -> None:
    """Only a proven pre-submit failure releases a claim."""
    with _locked():
        data = entries()
        sid = x_urls.status_id(url)
        entry = data.get(sid)
        if isinstance(entry, dict) and entry.get("status") == "pending":
            del data[sid]
            STATE.write(data)


def pending_times() -> list[datetime]:
    return [datetime.fromisoformat(e["ts"]) for e in entries().values()
            if isinstance(e, dict) and e["status"] == "pending"]


def pending_today() -> int:
    now = active_hours.now_local()
    return sum(at.astimezone(now.tzinfo).date() >= now.date() for at in pending_times())
