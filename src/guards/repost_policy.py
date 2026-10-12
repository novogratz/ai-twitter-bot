"""Repost eligibility, durable status-ID deduplication and uncertain submissions.

Operator 2026-10-12: up to fifty reposts, priority originals plus popular
generated videos. Only the write chokepoint reserves or confirms a submission.
"""
from datetime import datetime, timedelta

from ..core import account, config, settings, topic_evidence
from ..core.state_store import StateFile, GUARDED
from ..core.state_errors import StateUnreadable
from ..x import x_urls
from . import active_hours
from .reply_admission import is_blocked_account
from . import respect_list

HISTORY = StateFile("repost_history.json", {}, GUARDED)


def history() -> dict:
    rows = HISTORY.read()
    try:
        for key, row in rows.items():
            if (not key.isdigit() or not isinstance(row, dict)
                    or row.get("state") not in {"pending", "confirmed", "observed"}
                    or not isinstance(row.get("url"), str) or not isinstance(row.get("at"), str)
                    or x_urls.status_id(row["url"]) != key
                    or datetime.fromisoformat(row["at"]).tzinfo is None):
                raise ValueError("invalid repost record")
    except (KeyError, TypeError, ValueError) as exc:
        raise StateUnreadable("repost_history.json is unreadable; repair repost history") from exc
    return rows


def known(url: str) -> bool:
    from . import action_guard
    key = x_urls.status_id(url)
    return key in history() or any(x_urls.status_id(u) == key
                                  for u in action_guard._ledger().targets(action_guard.RETWEET))


def pending_count() -> int:
    from . import action_guard
    shipped = {x_urls.status_id(u) for u in action_guard._ledger().targets(action_guard.RETWEET)}
    today = active_hours.now_local().date()
    return sum(row["state"] in {"pending", "observed"} and key not in shipped
               and datetime.fromisoformat(row["at"]).astimezone(active_hours.now_local().tzinfo).date() >= today
               for key, row in history().items())


def spacing_remaining() -> float:
    from . import action_guard
    times = [datetime.fromisoformat(row["at"]) for row in history().values()]
    last = action_guard._ledger().last_write(action_guard.RETWEET)
    if last:
        times.append(last)
    if not times:
        return 0
    return max(0, settings.get("MIN_SECONDS_BETWEEN_REPOSTS") - (active_hours.now_local() - max(times)).total_seconds())


def remember(url: str, state: str) -> None:
    """Under the Safari lock, before a possible click or after its ledger row."""
    history()  # Validate before updating; never heal a malformed guarded store.
    key = x_urls.status_id(url)
    if not key or state not in {"pending", "confirmed", "observed"}:
        raise ValueError("invalid repost reservation")
    def save(rows):
        old = rows.get(key, {})
        rows[key] = dict(url=url, state=state, at=old.get("at", active_hours.now_local().isoformat()))
        return rows
    HISTORY.update(save)


def priority(url: str) -> bool:
    return x_urls.author(url) in account.current().reposts.priority_handles


def popularity(post: dict) -> tuple:
    age = x_urls.age(post.get("url", ""), active_hours.now_local())
    minutes = max(1, age.total_seconds() / 60) if age is not None else float("inf")
    likes = max(0, int(post.get("likes") or 0))
    reposts = max(0, int(post.get("reposts") or 0))
    return (likes + 4 * reposts) / minutes, likes, reposts


def is_rising_video(post: dict) -> bool:
    if post.get("has_video") is not True or not account.current().niche.matches_video(post.get("text", "")):
        return False
    velocity, likes, reposts = popularity(post)
    return likes >= 500 or reposts >= 100 or (likes >= 75 and velocity >= 5) or (reposts >= 20 and velocity >= 4)


def refusal(post: dict, *, require_review: bool = True) -> str:
    """Same checks during discovery and against the opened post before a click."""
    url, text = post.get("url", ""), post.get("text", "")
    author = x_urls.author(url)
    if not x_urls.status_id(url) or not author or config.is_own_handle(author) or is_blocked_account(author):
        return "missing, own or blocked author"
    if post.get("is_reply") is not False or text.lstrip().startswith("@"):
        return "standalone original required"
    age = x_urls.age(url, active_hours.now_local())
    if age is None or not timedelta(0) <= age <= timedelta(hours=24):
        return "post outside the 24-hour discovery window"
    niche = account.current().niche
    if niche.excludes(text + " " + post.get("quoted_text", "")):
        return "excluded topic"
    _, why = respect_list.scrub_text_or_skip(text, addressee=author)
    if why:
        return why
    if priority(url):
        if account.current().reposts.allow_off_topic_priority or niche.matches_post(text):
            return ""
        return "priority post outside the Account's topic policy"
    if not is_rising_video(post):
        return "requires a rising generated video with caption evidence"
    if require_review and not approved(post):
        return "video has no current matching semantic approval"
    return ""


def reviewed(post: dict) -> dict | None:
    row = topic_evidence.read().get(x_urls.status_id(post.get("url", "")), {})
    review = row.get("repost_review")
    if not isinstance(review, dict) or review.get("text") != post.get("text"):
        return None
    try:
        age = active_hours.now_local() - datetime.fromisoformat(review["at"])
        if (timedelta(0) <= age < timedelta(hours=1)
                and type(review.get("approved")) is bool and isinstance(review.get("reason"), str)
                and review["reason"].strip()):
            return review
    except (KeyError, TypeError, ValueError):
        pass
    return None


def approved(post: dict) -> bool:
    review = reviewed(post)
    return bool(review and review["approved"])


def save_review(post: dict, approved: bool, reason: str) -> None:
    key = x_urls.status_id(post["url"])
    def save(rows):
        topic_evidence._check(rows)
        if key in rows and rows[key]["text"] == post["text"]:
            rows[key]["repost_review"] = dict(text=post["text"], approved=approved,
                                             reason=reason, at=active_hours.now_local().isoformat())
        return rows
    topic_evidence.POOL.update(save)
