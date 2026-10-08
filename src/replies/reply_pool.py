"""Durable Reply pool: discovered posts, eligibility and selection decisions."""
from datetime import datetime, timedelta
import json
import os
import fcntl

from ..core.state_store import StateFile, StatePath, GUARDED
from ..core.state_errors import StateUnreadable
from ..core import config
from ..guards.reply_admission import is_blocked_account
from ..guards.active_hours import now_local
from ..x import x_urls

ARCHIVE = StatePath("reply_archive.jsonl")
POOL = StateFile("reply_candidates.json", {}, GUARDED)
BATCH_SIZE = 30
MIN_SCORE = 85
COLLECT_SECONDS = 60
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
                    or ("eligible" in row and type(row["eligible"]) is not bool)):
                raise ValueError("invalid Reply pool record")
            for field in ("first_seen", "last_seen"):
                if datetime.fromisoformat(row[field]).tzinfo is None:
                    raise ValueError("naive Reply pool timestamp")
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


def _archive(events: list) -> None:
    if not events:
        return
    try:
        with open(ARCHIVE, "a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise StateUnreadable("reply_archive.jsonl cannot be saved; Reply collection stopped") from exc


def _prune(records: dict) -> None:
    # The append-only archive keeps every discovery and decision permanently.
    # The mutable comparison pool keeps only the last day's discoveries.
    cutoff = now_local() - MAX_AGE
    events = []
    for key in list(records):
        if datetime.fromisoformat(records[key]["first_seen"]) < cutoff:
            del records[key]


def observe(tweets: list, source: str) -> None:
    """Save every discovered status before the reply scan filters it."""
    if not tweets:
        return
    stamp = now_local().isoformat()
    # Check the record schema before any update; never replace corrupt state.
    read()
    def save(records):
        _check(records)
        _prune(records)
        events = []
        for tweet in tweets:
            url = tweet.get("url") or ""
            key = x_urls.status_id(url)
            if not key:
                continue
            text = tweet.get("full_text") or tweet.get("text") or ""
            old = records.get(key, {})
            changed = old and old["text"] != text
            row = {**old, "url": url, "text": text, "author": x_urls.author(url),
                   "first_seen": old.get("first_seen", stamp), "last_seen": stamp,
                   "sources": sorted(set(old.get("sources", [])) | {source}),
                   "likes": tweet.get("likes") or old.get("likes", 0),
                   "views": tweet.get("views") or old.get("views", 0),
                   "is_reply": bool(tweet.get("is_reply") or text.lstrip().startswith("@")),
                   "state": old.get("state", "observed"),
                   "reason": old.get("reason", "not yet admitted by a scan’s filters")}
            if changed and row["state"] not in {"shipped", "closed", "processing"}:
                row.update(state="observed", eligible=False, score=None, reason="post text changed")
            records[key] = row
            if not old or changed:
                events.append(dict(kind="discovered", id=key, ts=stamp, post=row))
        _archive(events)
        return records
    POOL.update(save)


def collect(job, candidates) -> int:
    """A scan queues candidates and never writes to X or calls a model."""
    candidates = list(candidates)
    read()
    stamp = now_local().isoformat()
    def save(records):
        _check(records)
        _prune(records)
        events = []
        for candidate in candidates:
            key = x_urls.status_id(candidate.url)
            if not key:
                continue
            new = key not in records
            row = records.setdefault(key, dict(url=candidate.url, text=candidate.text,
                                     author=x_urls.author(candidate.url), first_seen=stamp,
                                     last_seen=stamp, sources=[], state="observed"))
            if new:
                events.append(dict(kind="discovered", id=key, ts=stamp, post=dict(row)))
            row["sources"] = sorted(set(row["sources"]) | {candidate.source})
            author = x_urls.author(candidate.url)
            if author == config.BOT_HANDLE.lower() or is_blocked_account(author):
                row.update(eligible=False, state="rejected", reason="own or Blocked account")
                events.append(dict(kind="decision", id=key, state="rejected", reason=row["reason"], ts=stamp))
                continue
            if job.debate_turn or candidate.context or row.get("is_reply") or candidate.text.lstrip().startswith("@"):
                row.update(eligible=False, state="rejected", reason="conversation replies are disabled")
                continue
            if row["state"] in {"observed", "queued"}:
                row.update(eligible=True, state="queued", source=candidate.source,
                           reason="awaiting comparison with the Reply pool")
        _archive(events)
        return records
    POOL.update(save)
    return 0


def contenders(now=None) -> list:
    now = now or now_local()
    candidates = []
    for key, row in read().items():
        if not row.get("eligible") or row["state"] not in {"queued", "ready"}:
            continue
        age = x_urls.age(row["url"], now)
        try:
            seen = datetime.fromisoformat(row["first_seen"])
        except (KeyError, TypeError, ValueError):
            raise StateUnreadable("reply_candidates.json has an unreadable discovery time") from None
        if age is None or age < timedelta(0) or age > MAX_AGE or now - seen < timedelta(seconds=COLLECT_SECONDS):
            continue
        candidates.append({"id": key, **row})
    # Unreviewed posts get a turn; all scores are compared globally after review.
    return sorted(candidates, key=lambda row: (row["state"] != "queued", row["first_seen"], row["id"]))


def decide(batch: list, reviews: list) -> None:
    stamp = now_local().isoformat()
    by_id = {row["id"]: row for row in batch}
    def save(records):
        _check(records)
        events = []
        for review in reviews:
            key = review["id"]
            row = records.get(key)
            if not row or row["text"] != by_id[key]["text"] or row["state"] not in {"queued", "ready"}:
                continue
            row.update(score=review["score"], reason=review["reason"], angle=review["angle"],
                       reviewed_at=stamp, state="ready" if review["score"] >= MIN_SCORE else "rejected")
            events.append(dict(kind="reviewed", ts=stamp, **review))
        _archive(events)
        return records
    POOL.update(save)


def mark(key: str, state: str, **fields) -> None:
    def save(records):
        _check(records)
        records[key].update(state=state, **fields)
        _archive([dict(kind="decision", id=key, state=state, ts=now_local().isoformat(), **fields)])
        return records
    POOL.update(save)
