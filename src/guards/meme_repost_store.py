"""Reviewed funny AI videos; legacy meme history and permanent claims survive."""
from collections import deque
import csv
from datetime import datetime, timedelta
import hashlib
import threading
import time

from ..core import account, config, settings
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile
from ..x import x_urls
from . import active_hours, content_guard, respect_list

STATE = StateFile("meme_repost_reviews.json", {}, GUARDED)
_lock = threading.RLock()
_candidates = {}
_recent = {}
_seeded = False
_retry_after = {}


def digest(text):
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def eligible(url):
    from .reply_admission import is_blocked_account
    age = x_urls.age(url)
    return bool(x_urls.canonical_status_url(url) and x_urls.author(url) not in account.own_handles()
                and not is_blocked_account(x_urls.author(url)) and age is not None
                and timedelta(0) <= age <= timedelta(hours=24))


def qualifies(page):
    profile, text = account.current(), page.get("text", "")
    return (isinstance(text, str) and bool(profile.niche.post.search(text))
            and page.get("has_video") is True
            and not profile.relevance.off_topic.search(text)
            and eligible(page.get("url", "")) and not x_urls.is_reply_like_tweet(page)
            and all(not settings.get(name) or (type(page.get(key)) is int and page[key] >= settings.get(name))
                    for key, name in (("likes", "MEME_REPOST_MIN_LIKES"), ("views", "MEME_REPOST_MIN_VIEWS")))
            and content_guard.validate(text, kind="source", source_language=page.get("language", ""))[0]
            and not respect_list.scrub_text_or_skip(text)[1])


def offer(tweets):
    if not settings.get("MEME_REPOST_ENABLED") or config.dry_run():
        return
    with _lock:
        for tweet in tweets:
            if qualifies(tweet):
                url = x_urls.canonical_status_url(tweet["url"])
                _candidates[url] = {**tweet, "url": url}
        ranked = sorted((r for r in _candidates.values() if eligible(r["url"])),
                        key=lambda r: (_recent.get(r["url"], 0), r.get("likes") or 0, r.get("views") or 0), reverse=True)[:40]
        _candidates.clear()
        _candidates.update((r["url"], r) for r in ranked)


def note_reply(url):
    """No browser/model work on the Reply path; prefer an already discovered video."""
    if not settings.get("MEME_REPOST_ENABLED") or config.dry_run():
        return
    with _lock:
        if url in _candidates:
            _recent[url] = time.time()
        for old in sorted(_recent, key=_recent.get)[:-40]:
            del _recent[old]


def _seed_recent():
    """At most ten recent confirmed parents survive restart via existing history."""
    global _seeded
    if _seeded:
        return
    _seeded = True
    try:
        with open(config.ENGAGEMENT_LOG_FILE, newline="") as handle:
            rows = deque(csv.reader(handle), maxlen=100)
    except (OSError, csv.Error):
        return
    for row in reversed(rows):
        if len(_recent) >= 10:
            break
        if len(row) >= 4 and row[1] == "reply" and eligible(row[3]):
            url = x_urls.canonical_status_url(row[3])
            _recent.setdefault(url, time.time() - len(_recent))


def defer(url):
    with _lock:
        _retry_after[url] = time.monotonic() + 900
        for old in list(_retry_after):
            if _retry_after[old] <= time.monotonic():
                del _retry_after[old]


def entries():
    data = STATE.read()
    try:
        for sid, r in data.items():
            if (x_urls.status_id(r["url"]) != sid or not x_urls.canonical_status_url(r["url"])
                    or type(r["approved"]) is not bool or not datetime.fromisoformat(r["at"]).tzinfo
                    or not isinstance(r["source_text"], str) or r["source_hash"] != digest(r["source_text"])
                    or (r["approved"] and (type(r.get("humor_score")) not in (int, float)
                                            or not (0 if r.get("kind") == "video" else 9) <= r["humor_score"] <= 10))):
                raise ValueError("invalid review")
            if r.get("kind") == "video" and r["approved"]:
                from ..video.repost_review import valid
                if not valid(r.get("video_evidence"), r["url"], r["source_text"], r.get("media_id")):
                    raise ValueError("invalid video review")
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise StateUnreadable("Meme repost reviews malformed; preserve and repair history") from exc
    return data


def next_candidate():
    from . import repost_store
    reviews = entries()
    with _lock:
        _seed_recent()
        pool = {url: dict(url=url, text="") for url in _recent}
        pool.update(_candidates)
        rows = [r for r in pool.values() if eligible(r["url"])
                and reviews.get(x_urls.status_id(r["url"]), {}).get("kind") != "video"
                and _retry_after.get(r["url"], 0) <= time.monotonic() and not repost_store.contains(r["url"])]
        return max(rows, key=lambda r: (_recent.get(r["url"], 0), r.get("likes") or 0, r.get("views") or 0), default=None)


def review(url, text, approved, reason, humor_score=0, *, video_evidence=None):
    if config.dry_run():
        return
    now = active_hours.now_local()
    with STATE._lock:
        data = entries()
        row = dict(url=url, source_text=text, source_hash=digest(text),
                                          approved=bool(approved), humor_score=humor_score,
                                          at=now.isoformat(), reason=reason[:600], kind="video",
                                          video_evidence=video_evidence, media_id=(video_evidence or {}).get("media_id", ""))
        if approved:
            from ..video.repost_review import valid
            if not valid(video_evidence, url, text, row["media_id"]):
                raise ValueError("cannot approve an uninspected video")
        data[x_urls.status_id(url)] = row
        data = {sid: r for sid, r in data.items() if eligible(r["url"])}
        STATE.write(data)


def approved(url):
    row = entries().get(x_urls.status_id(url), {})
    return (settings.get("MEME_REPOST_ENABLED") and eligible(url) and row.get("approved") is True
            and row.get("kind") == "video")


def refusal(url=""):
    from . import action_guard, repost_store
    from .ledger import MEME_REPOST
    if not settings.get("MEME_REPOST_ENABLED"):
        return "meme reposts disabled"
    if url and (not approved(url) or repost_store.contains(url)):
        return "meme needs a fresh review and an unclaimed original"
    now = active_hours.now_local()
    claims = [r for r in repost_store.entries().values() if isinstance(r, dict) and r.get("kind") == "meme"]
    if any(r["status"] == "pending" for r in claims):
        return "uncertain meme repost held"
    attempts = [datetime.fromisoformat(r["ts"]) for r in claims if r["status"] == "shipped"]
    used = max(sum(t.astimezone(now.tzinfo).date() >= now.date() for t in attempts),
               action_guard.count_today(MEME_REPOST))
    if used >= settings.get("MEME_REPOST_DAILY_CAP"):
        return "meme daily cap reached"
    last = max(attempts + [t for t in [action_guard._ledger().last_write(MEME_REPOST)] if t], default=None)
    if last and (now - last).total_seconds() < settings.get("MEME_REPOST_INTERVAL_MINUTES") * 60:
        return "meme repost spacing"
    return ""
