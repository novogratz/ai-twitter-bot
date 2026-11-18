"""Durable Reply submission budget, including ambiguous sends and restarts.

The action ledger remains the receipt of confirmed writes. This journal records
the last possible pre-submit point, so a missing receipt cannot buy another slot.
Permanent parent deduplication remains in replied_store.
"""
import fcntl
import os
from contextlib import contextmanager
from datetime import datetime

from ..core import account, settings
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile, ensure_root
from ..x import x_urls
from . import active_hours

STATE = StateFile("reply_submissions.json", {}, GUARDED)


def entries() -> dict:
    data = STATE.read()
    try:
        for sid, entry in data.items():
            if (not isinstance(sid, str) or not sid.isdigit()
                    or not isinstance(entry, dict)
                    or entry.get("status") not in {"pending", "confirmed"}
                    or not isinstance(entry.get("target"), str)
                    or x_urls.status_id(x_urls.canonical_status_url(entry["target"])) != sid
                    or not datetime.fromisoformat(entry.get("submitted_at", "")).tzinfo):
                raise ValueError("invalid submission")
    except (AttributeError, TypeError, ValueError) as exc:
        raise StateUnreadable("Reply budget is malformed; repair reply_submissions.json") from exc
    return data


def submission_times() -> list[datetime]:
    return [datetime.fromisoformat(entry["submitted_at"]) for entry in entries().values()]


def used_today(author: str = "") -> int:
    from . import action_guard as guard
    now = active_hours.now_local()
    ledger = guard._ledger()
    used = (sum(ledger.count(guard.REPLY, now.date(), target) for target in ledger.targets(guard.REPLY)
                if x_urls.author(target) == author) if author else ledger.count(guard.REPLY, now.date()))
    for entry in entries().values():
        if author and x_urls.author(entry["target"]) != author:
            continue
        at = datetime.fromisoformat(entry["submitted_at"]).astimezone(now.tzinfo)
        # Future stamps remain charged after a clock rollback. A receipt for
        # this target already counted on this day must not count twice.
        if at.date() >= now.date() and not ledger.count(guard.REPLY, now.date(), entry["target"]):
            used += 1
    return used


def refusal(url: str = "") -> str:
    used, cap = used_today(), settings.get("MAX_REPLIES_PER_DAY")
    if used >= cap:
        return f"daily Reply cap reached including submissions ({used}/{cap})"
    author = x_urls.author(url)
    if author and author in account.current().auto_engage_handles:
        used, cap = used_today(author), settings.get("REPLY_WATCHED_DAILY_CAP")
        if used >= cap:
            return f"daily Reply cap reached for @{author} including submissions ({used}/{cap})"
    return ""


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
            raise StateUnreadable("Reply submission budget could not be locked or saved") from exc


def begin(url: str) -> str:
    """Reserve immediately before submit; return a refusal, or empty on success.

    There is deliberately no release: after this point a crash or transport
    failure cannot establish that X did not receive the Reply.
    """
    from . import action_guard as guard
    sid = x_urls.status_id(x_urls.canonical_status_url(url))
    if not sid:
        return "invalid Reply parent URL"
    with _locked():
        data = entries()
        if sid in data:
            return "Reply already submitted"
        from .reply_focus import freshness_refusal
        why = freshness_refusal(url)
        if why:
            return why
        ok, why = guard.can_post(guard.REPLY, target=url)
        if not ok:
            return why
        data[sid] = dict(target=url, status="pending", submitted_at=active_hours.now_local().isoformat())
        STATE.write(data)
    return ""


def confirmed(url: str) -> None:
    with _locked():
        data = entries()
        data[x_urls.status_id(url)]["status"] = "confirmed"
        STATE.write(data)
