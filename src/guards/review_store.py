"""Guarded manual-review history and no-contact requests, shared with admission."""
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import math
import re
import threading

from ..core import account, state_store
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile, StatePath
from ..x import x_urls
from . import active_hours

QUEUE = StateFile("manual_reply_review.json", {"version": 1, "items": {}}, GUARDED)
OPT_OUTS = StateFile("manual_reply_opt_outs.json", {}, GUARDED)
REPORT = StatePath("manual_reply_review.md")
LOCK = StatePath("manual_reply_review.lock")
_LOCK = threading.RLock()
_STATUSES = {"source", "draft", "skipped", "dismissed", "reported_posted"}
SESSION_TIMES = ("05:00", "10:00", "15:00", "20:00")
METRIC_FIELDS = ("meaningful_responses", "repeat_interactions", "reply_views",
                 "attributable_profile_visits", "attributable_follows", "minutes")


@contextmanager
def locked():
    with _LOCK:
        state_store.ensure_root()
        with open(LOCK, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


def timestamp(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return at


def thread_refusal(row):
    """A manual follow-up needs the supplied external-root / own-reply chain.

    This checks snapshot consistency, not publication or consent. The operator
    still reads the live thread before posting; these snapshots never authorize X.
    """
    if row.get("is_reply") is False:
        return "" if not row.get("thread") else "standalone source carries conflicting thread context"
    thread = row.get("thread")
    if row.get("is_reply") is not True or not isinstance(thread, dict):
        return "missing standalone status or complete external-thread context"
    root = x_urls.canonical_status_url(thread.get("root_url", ""))
    own = x_urls.canonical_status_url(thread.get("own_reply_url", ""))
    reply_to = x_urls.canonical_status_url(thread.get("in_reply_to_url", ""))
    target = x_urls.canonical_status_url(row.get("url", ""))
    if (not root or not own or not target or reply_to != own
            or x_urls.author(root) in account.own_handles()
            or x_urls.author(own) not in account.own_handles()
            or not int(x_urls.status_id(root)) < int(x_urls.status_id(own)) < int(x_urls.status_id(target))):
        return "follow-up must answer an incoming reply to our reply under an external original"
    if any(not isinstance(thread.get(key), str) or not 1 <= len(thread[key].strip()) <= 12000
           for key in ("root_text", "own_reply_text")):
        return "follow-up context is incomplete"
    return ""


def session_key(now):
    current = now.strftime("%H:%M")
    slot = max((slot for slot in SESSION_TIMES if slot <= current), default=SESSION_TIMES[0])
    return f"{now.date().isoformat()}/{slot}"


def _session_key_valid(key):
    day, slot = key.split("/")
    date.fromisoformat(day)
    return slot in SESSION_TIMES


def valid_metric(key, value):
    if key == "minutes":
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1440
    return key in METRIC_FIELDS and type(value) is int and value >= 0


def entries():
    data = QUEUE.read()
    try:
        if data.get("version") != 1 or not isinstance(data.get("items"), dict):
            raise ValueError("unsupported queue version")
        for sid, row in data["items"].items():
            if (not isinstance(row, dict) or row.get("status") not in _STATUSES
                    or sid != x_urls.status_id(x_urls.canonical_status_url(row.get("url", "")))
                    or not isinstance(row.get("parent"), str) or not row["parent"].strip()
                    or thread_refusal(row)):
                raise ValueError("malformed source")
            timestamp(row["observed_at"])
            if "review_session" in row and not _session_key_valid(row["review_session"]):
                raise ValueError("malformed review session")
            if "drafted_on" in row:
                date.fromisoformat(row["drafted_on"])
                if not isinstance(row.get("draft"), str) or not row["draft"].strip():
                    raise ValueError("missing draft")
            elif row["status"] in {"draft", "reported_posted"}:
                raise ValueError("missing draft date")
        sessions = data.get("sessions", {})
        if not isinstance(sessions, dict):
            raise ValueError("malformed review sessions")
        for key, row in sessions.items():
            if (not _session_key_valid(key) or not isinstance(row, dict)
                    or type(row.get("attempts")) is not int or not 0 <= row["attempts"] <= 50
                    or type(row.get("discovered", False)) is not bool):
                raise ValueError("malformed review session")
        metrics = data.get("reported_metrics", {})
        if not isinstance(metrics, dict):
            raise ValueError("malformed reported metrics")
        for day, row in metrics.items():
            date.fromisoformat(day)
            if not isinstance(row, dict) or row.get("verification") != "operator_reported_unverified":
                raise ValueError("missing self-report attribution")
            timestamp(row["reported_at"])
            if any(not valid_metric(key, value) for key, value in row.items()
                   if key not in {"verification", "reported_at"}):
                raise ValueError("malformed reported metric")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise StateUnreadable("Malformed manual Reply review queue; repair without resetting history") from exc
    return data


def _opt_outs():
    data = OPT_OUTS.read()
    if any(not re.fullmatch(r"[a-z0-9_]{1,15}", handle) or not isinstance(row, dict)
           or not isinstance(row.get("reason"), str) for handle, row in data.items()):
        raise StateUnreadable("Malformed manual Reply opt-outs; repair without resetting history")
    return data


def opted_out(author):
    return author.lower().lstrip("@") in _opt_outs()


def reserved_for_manual_review(url):
    row = entries()["items"].get(x_urls.status_id(url), {})
    return row.get("status") in {"draft", "dismissed", "reported_posted"}


def record_opt_out(author, reason):
    data = _opt_outs()
    data[author] = {"reason": reason, "at": active_hours.now_local().isoformat()}
    OPT_OUTS.write(data)


