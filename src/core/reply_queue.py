"""Bounded prepared Replies shared by collectors and the independent selector."""
import re
from datetime import datetime, timedelta

from .state_errors import StateUnreadable
from .state_store import GUARDED, StateFile, StatePath, process_lock
from ..guards import active_hours
from ..x import x_urls

QUEUE = StateFile("reply_draft_queue.json", {}, GUARDED)
LOCK = StatePath("reply_draft_queue.lock")
MAX_PENDING = 8
TTL = timedelta(minutes=30)
REVIEW_TTL = timedelta(minutes=10)
STATUSES = {"preparing", "ready", "reviewed", "rejected", "selected", "attempted"}
DIMENSIONS = ("impact", "sharpness", "interest")


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError("missing timezone")
        return stamp
    except (ValueError, TypeError) as exc:
        raise StateUnreadable("Reply queue has an invalid timestamp") from exc


def _checked_review(review):
    if (not isinstance(review, dict)
            or set(review) != {*DIMENSIONS, "grounded", "on_topic", "support", "reason", "reviewed_at"}
            or any(type(review.get(k)) is not int or not 0 <= review[k] <= 5 for k in DIMENSIONS)
            or any(type(review.get(k)) is not bool for k in ("grounded", "on_topic"))
            or any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("support", "reason"))):
        raise StateUnreadable("Reply queue has an invalid review")
    _stamp(review["reviewed_at"])
    return review


def _read():
    data = QUEUE.read()
    for sid, row in data.items():
        if (not isinstance(row, dict) or not isinstance(row.get("status"), str) or row["status"] not in STATUSES
                or any(not isinstance(row.get(k), str) for k in (
                    "url", "parent", "text", "source", "provider", "model", "language", "pattern", "created_at"))
                or x_urls.status_id(row["url"]) != sid or not row["parent"].strip()):
            raise StateUnreadable("Reply queue has an invalid draft record")
        _stamp(row["created_at"])
        if row["status"] in {"reviewed", "selected"}:
            _checked_review(row.get("review"))
        if row["status"] == "selected":
            _stamp(row.get("selected_at"))
    return data


def _fresh(row):
    age = active_hours.now_local() - _stamp(row["created_at"])
    return timedelta(0) <= age < TTL


def reserve(candidate) -> str:
    """Reserve model work once per parent across all collecting jobs."""
    sid = x_urls.status_id(candidate.url)
    if not sid or not candidate.text.strip():
        return ""
    with process_lock(LOCK):
        data = {key: row for key, row in _read().items() if _fresh(row)}
        active = sum(row["status"] in {"preparing", "ready", "reviewed", "selected"} for row in data.values())
        if sid in data or active >= MAX_PENDING:
            return ""
        data[sid] = dict(url=candidate.url, parent=candidate.text[:4000], source=candidate.source,
                         text="", provider="", model="", language="", pattern="", status="preparing",
                         created_at=active_hours.now_local().isoformat())
        QUEUE.write(data)
    return sid


def prepared(sid: str, text: str, generation, pattern: str):
    with process_lock(LOCK):
        data = _read()
        row = data.get(sid)
        if row and row["status"] == "preparing" and _fresh(row):
            row.update(text=text, provider=generation.provider, model=generation.model,
                       language=generation.language, pattern=pattern, status="ready")
            QUEUE.write(data)


def discard(sid: str, reason: str, *, attempted: bool = False):
    with process_lock(LOCK):
        data = _read()
        if sid in data:
            data[sid].update(status="attempted" if attempted else "rejected", outcome=reason)
            QUEUE.write(data)


def ready() -> dict:
    return {sid: row for sid, row in _read().items()
            if row["status"] in {"ready", "reviewed"} and _fresh(row)}


def approved(row) -> bool:
    review = row.get("review")
    if not review:
        return False
    _checked_review(review)
    age = active_hours.now_local() - _stamp(review["reviewed_at"])
    return (timedelta(0) <= age < REVIEW_TTL and review["grounded"] and review["on_topic"]
            and all(review[key] >= 4 for key in DIMENSIONS))


def reviewed(snapshot: dict, reviews: dict):
    with process_lock(LOCK):
        data = _read()
        for sid, review in reviews.items():
            row = data.get(sid)
            if row and row == snapshot[sid] and _fresh(row):
                _checked_review(review)
                row.update(review=review, status="reviewed")
                if not approved(row):
                    row["status"] = "rejected"
        QUEUE.write(data)


def select(sid: str, snapshot: dict) -> bool:
    with process_lock(LOCK):
        data = _read()
        row = data.get(sid)
        if not row or row != snapshot or row["status"] != "reviewed" or not _fresh(row) or not approved(row):
            return False
        row.update(status="selected", selected_at=active_hours.now_local().isoformat())
        QUEUE.write(data)
    return True


def _selection(url: str):
    row = _read().get(x_urls.status_id(url))
    if (not row or row["status"] != "selected" or x_urls.author(row["url"]) != x_urls.author(url)
            or not _fresh(row) or not approved(row)):
        return None
    age = active_hours.now_local() - _stamp(row["selected_at"])
    return row if timedelta(0) <= age < timedelta(minutes=5) else None


def is_selected(url: str, text: str) -> bool:
    row = _selection(url)
    return bool(row and row["text"] == text)


def matches_parent(url: str, text: str) -> bool:
    row = _selection(url)
    if not row:
        return False
    normalize = lambda s: re.sub(r"\s+", " ", s).strip()
    expected, actual = normalize(row["parent"]), normalize(text)
    return actual == expected or (len(row["parent"]) == 4000 and actual.startswith(expected))


def selected_parent(url: str):
    row = _selection(url)
    return row["parent"] if row else None
