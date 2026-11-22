"""Reviewed watched quotes and permanent, process-locked publication claims."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import os

from ..core import account, config, settings
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile, ensure_root
from ..x import x_urls
from . import active_hours, content_guard, respect_list

STATE = StateFile("priority_quotes.json", {}, GUARDED)


def valid_text(text):
    from twitter_text import parse_tweet
    if not isinstance(text, str) or not 8 <= len(text) <= 250:
        return False
    parsed = parse_tweet(text)
    return (parsed.valid and parsed.weightedLength <= 280
            and not content_guard.looks_truncated(text)
            and content_guard.validate(text, kind="original")[0]
            and not content_guard.is_duplicate(text)
            and not respect_list.scrub_text_or_skip(text)[1])


def digest(text):
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def entries():
    data = STATE.read()
    try:
        for sid, row in data.items():
            if (not isinstance(row, dict) or x_urls.status_id(row["url"]) != sid
                    or not x_urls.canonical_status_url(row["url"])
                    or row["state"] not in {"rejected", "approved", "pending", "shipped"}
                    or not datetime.fromisoformat(row["updated"]).tzinfo):
                raise ValueError("invalid quote record")
            if row["state"] != "rejected":
                if (not row["text"] or not row["source_text"]
                        or row["source_hash"] != digest(row["source_text"])
                        or type(row["impact"]) not in (int, float)
                        or not 8 <= row["impact"] <= 10 or row["reviewed"] is not True):
                    raise ValueError("invalid quote approval")
            if row["state"] in {"pending", "shipped"} and not datetime.fromisoformat(row["submitted"]).tzinfo:
                raise ValueError("invalid submission time")
            if row["state"] == "shipped" and x_urls.author(row["receipt"]) not in account.own_handles():
                raise ValueError("invalid quote receipt")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StateUnreadable("Quote history is malformed; preserve and repair priority_quotes.json") from exc
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
            raise StateUnreadable("Quote history could not be locked or saved") from exc


def eligible_source(url):
    age = x_urls.age(url)
    return (account.current().priority_quotes_enabled and account.watched_url(url)
            and age is not None and timedelta(0) <= age <= timedelta(hours=24))


def save_review(url, *, text="", source_text="", impact=0, reason="", approved=False):
    if config.dry_run():
        return
    with locked():
        data = entries()
        sid = x_urls.status_id(url)
        if sid in data:
            return
        data[sid] = dict(url=url, state="approved" if approved else "rejected",
                         updated=active_hours.now_local().isoformat(), text=text,
                         source_text=source_text, source_hash=digest(source_text),
                         impact=impact, reviewed=approved, reason=reason)
        # Rejected/unused reviews are disposable after source expiry; sends are permanent.
        data = {k: r for k, r in data.items() if r["state"] in {"pending", "shipped"}
                or (active_hours.now_local() - datetime.fromisoformat(r["updated"])) < timedelta(days=2)}
        STATE.write(data)


def latest_submission():
    return max((datetime.fromisoformat(r["submitted"]) for r in entries().values()
                if r["state"] in {"pending", "shipped"}), default=None)


def video_hold(stamp):
    last = latest_submission()
    return "spacing from a confirmed or uncertain quote" if last and stamp - last.timestamp() < config.MIN_SECONDS_BETWEEN_POSTS else ""


def refusal(url=""):
    if not account.current().priority_quotes_enabled:
        return "automatic quotes disabled"
    if url and not eligible_source(url):
        return "quote requires a fresh exact watched original"
    data, now = entries(), active_hours.now_local()
    if any(r["state"] == "pending" for r in data.values()):
        return "uncertain quote retained; reconcile before another quote"
    used = sum(r["state"] == "shipped" and datetime.fromisoformat(r["submitted"]).astimezone(now.tzinfo).date() >= now.date()
               for r in data.values())
    from . import action_guard
    if max(used, action_guard.count_today(action_guard.QUOTE)) >= settings.get("PRIORITY_QUOTE_DAILY_CAP"):
        return "selective quote daily cap reached"
    latest = latest_submission()
    if latest and (now - latest).total_seconds() < settings.get("PRIORITY_QUOTE_INTERVAL_MINUTES") * 60:
        return "selective quote spacing"
    last_text = action_guard._last_write(action_guard.POST)
    if last_text and (now - last_text).total_seconds() < config.MIN_SECONDS_BETWEEN_POSTS:
        return "spacing from last profile text publication"
    from ..video.config import legacy_usage
    _, last_video = legacy_usage(now)
    if last_video and now.timestamp() - last_video < config.MIN_SECONDS_BETWEEN_POSTS:
        return "spacing from confirmed video"
    return ""


def claim(url):
    with locked():
        if refusal(url):
            return False
        data = entries()
        row = data.get(x_urls.status_id(url), {})
        if row.get("state") != "approved":
            return False
        row.update(state="pending", submitted=active_hours.now_local().isoformat())
        STATE.write(data)
        return True


def release(url):
    """Only proven pre-submit failure may release a quote reservation."""
    with locked():
        data = entries()
        row = data.get(x_urls.status_id(url), {})
        if row.get("state") == "pending":
            row.update(state="approved")
            row.pop("submitted", None)
            STATE.write(data)


def confirm(url, receipt):
    if not x_urls.canonical_status_url(receipt) or x_urls.author(receipt) not in account.own_handles():
        raise ValueError("exact own receipt required")
    with locked():
        data = entries()
        row = data[x_urls.status_id(url)]
        if row["state"] != "pending":
            raise ValueError("quote not reserved")
        row.update(state="shipped", receipt=receipt)
        STATE.write(data)
