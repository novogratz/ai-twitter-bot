"""Durable Reply submission budget, including ambiguous sends and restarts.

The action ledger remains the receipt of confirmed writes. This journal records
the last possible pre-submit point, so a missing receipt cannot buy another slot.
Permanent parent deduplication remains in replied_store.
"""
import fcntl
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta

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


def daily_plan() -> dict:
    """Effective workload for today's Toronto date; no state reset or rolling expiry.

    Draft capacity is planning, not evidence of a manual publication. The manual
    workflow subtracts known submissions and reserves remaining watched slots.
    """
    from . import reply_selection
    start = settings.get("REPLY_WORKLOAD_BOOST_START_DATE")
    until = date.fromisoformat(start) + timedelta(days=settings.get("REPLY_WORKLOAD_BOOST_DAYS")) if start else None
    today = active_hours.now_local().date()
    boost_target = settings.get("REPLY_WORKLOAD_BOOST_TARGET")
    configured = settings.get("MAX_REPLIES_PER_DAY")
    minimum, maximum = (settings.get("REPLY_DAILY_TARGET_MIN"), settings.get("REPLY_DAILY_TARGET_MAX"))
    # A dated increase never lowers a newer persistent policy. Its fixed dates
    # remain readable, but a superseded lower target has no effect.
    boosted = bool(start and date.fromisoformat(start) <= today < until
                   and boost_target > configured and boost_target >= max(minimum, maximum))
    automatic = boost_target if boosted and configured else configured
    mode_ceiling = (1500 if reply_selection.broad() else 100 if settings.get("REPLY_CURATED_MODE")
                    else 250 if settings.get("REPLY_INVITED_ONLY") else 1500)
    automatic = min(mode_ceiling, automatic)
    drafts = settings.get("REPLY_REVIEW_DAILY_LIMIT")
    draft_limit = boost_target if boosted and drafts else min(80, drafts)
    minimum = boost_target if boosted else minimum
    maximum = boost_target if boosted else maximum
    return {"target": boost_target if boosted else (minimum + maximum) // 2,
            "minimum": minimum, "maximum": maximum,
            "cap": boost_target if boosted else max(automatic, draft_limit),
            "automatic_cap": automatic, "draft_limit": draft_limit,
            "session_limit": 50 if boosted else 20,
            "boost_active": boosted, "boost_start": start,
            "boost_until": until.isoformat() if until else ""}


def ceiling() -> int:
    return daily_plan()["automatic_cap"]


def refusal(url: str = "") -> str:
    used, cap = used_today(), ceiling()
    if used >= cap:
        return f"daily Reply cap reached including submissions ({used}/{cap})"
    if settings.get("REPLY_CURATED_MODE") and url and account.watched_url(url):
        if used_today(x_urls.author(url)) >= settings.get("CURATED_WATCH_REPLIES_PER_DAY"):
            return "watched-author Reply daily cap reached including unresolved submissions"
        recent = [datetime.fromisoformat(row["submitted_at"]) for row in entries().values()
                  if x_urls.author(row["target"]) == x_urls.author(url)]
        from . import action_guard
        if not recent and used_today(x_urls.author(url)):
            # Legacy receipts have no per-target timestamp index. Conservatively
            # use the latest Reply stamp; never invent an earlier spacing anchor.
            if at := action_guard._ledger().last_write(action_guard.REPLY):
                recent.append(at)
        gap = settings.get("CURATED_WATCH_REPLY_MIN_SECONDS")
        if recent and (active_hours.now_local() - max(recent)).total_seconds() < gap:
            spacing = "six-hour" if gap == 21600 else f"{gap}-second"
            return f"watched-author Replies require {spacing} spacing"
        return ""
    if settings.get("REPLY_INVITED_ONLY") and url and used_today(x_urls.author(url)):
        return "author already received a Reply or has an unresolved submission today"
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


def begin(url: str, text: str = "", *, thanks: bool = False) -> str:
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
        if why := refusal(url):
            return why
        # 2026-11-25: a thank-you to a commenter was judged by judge_thanks; the
        # ordinary Reply text rules (hearts only on artist posts) stopped the first one.
        if settings.get("REPLY_CURATED_MODE") and not thanks:
            from . import reply_selection
            if why := reply_selection.text_refusal(x_urls.author(url), text, url=url):
                return why
        ok, why = guard.can_post(guard.REPLY)
        if not ok:
            return why
        data[sid] = dict(target=url, status="pending", submitted_at=active_hours.now_local().isoformat())
        if settings.get("REPLY_CURATED_MODE"):
            from . import reply_selection
            row = reply_selection._sources.get(url, {})
            data[sid].update(lane=row.get("lane", "technical"), heart=bool(reply_selection.HEART.search(text)), text=text)
        STATE.write(data)
    return ""


def confirmed(url: str) -> None:
    with _locked():
        data = entries()
        data[x_urls.status_id(url)]["status"] = "confirmed"
        STATE.write(data)
