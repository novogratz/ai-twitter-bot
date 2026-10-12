"""Shared guarded Reply candidates and the topic evidence used by account jobs."""
from datetime import datetime, timedelta

from . import account, config
from .state_store import StateFile, GUARDED
from .state_errors import StateUnreadable
from ..guards.reply_admission import is_blocked_account
from ..guards.active_hours import now_local
from ..x import x_urls

POOL = StateFile("reply_candidates.json", {}, GUARDED)
MIN_SCORE = 85
MAX_AGE = timedelta(hours=24)


def _check(records: dict) -> dict:
    try:
        for key, row in records.items():
            if (not key.isdigit() or not isinstance(row, dict)
                    or not isinstance(row.get("url"), str)
                    or x_urls.status_id(row["url"]) != key
                    or not isinstance(row.get("text"), str)
                    or row.get("state") not in {"observed", "queued", "ready", "rejected", "processing", "shipped", "closed", "skipped"}
                    or not isinstance(row.get("sources"), list)
                    or any(not isinstance(source, str) for source in row["sources"])
                    or ("eligible" in row and type(row["eligible"]) is not bool)
                    or ("has_video" in row and type(row["has_video"]) is not bool)
                    or ("on_topic" in row and type(row["on_topic"]) is not bool)):
                raise ValueError("invalid Reply pool record")
            for field in ("first_seen", "last_seen"):
                if datetime.fromisoformat(row[field]).tzinfo is None:
                    raise ValueError("naive Reply pool timestamp")
            if "repost_review" in row:
                review = row["repost_review"]
                if (not isinstance(review, dict) or type(review.get("approved")) is not bool
                        or not isinstance(review.get("text"), str)
                        or not isinstance(review.get("reason"), str) or not review["reason"].strip()
                        or datetime.fromisoformat(review["at"]).tzinfo is None):
                    raise ValueError("invalid repost review")
            if row["state"] == "ready":
                if (type(row.get("score")) is not int or not MIN_SCORE <= row["score"] <= 100
                        or not isinstance(row.get("angle"), str) or not row["angle"].strip()
                        or datetime.fromisoformat(row["reviewed_at"]).tzinfo is None):
                    raise ValueError("invalid Reply selection")
    except (KeyError, TypeError, ValueError) as exc:
        raise StateUnreadable("reply_candidates.json is unreadable; repair the Reply pool") from exc
    return records


def read() -> dict:
    return _check(POOL.read())


def approved_authors() -> list[str]:
    """Fresh, explicitly on-topic discoveries; old handle lists are not evidence."""
    now = now_local()
    authors = []
    for row in read().values():
        author = x_urls.author(row["url"])
        age = x_urls.age(row["url"], now)
        if (row.get("on_topic") is True and row.get("eligible") is True
                and row["state"] in {"ready", "processing", "shipped", "closed", "skipped"}
                and not row.get("is_reply") and author and not config.is_own_handle(author)
                and not is_blocked_account(author) and age is not None
                and timedelta(0) <= age <= MAX_AGE
                and account.current().niche.matches_post(row["text"])):
            authors.append(author)
    return list(dict.fromkeys(authors))
