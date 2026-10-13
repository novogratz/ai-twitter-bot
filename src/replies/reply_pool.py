"""Durable Reply pool: discovered posts, eligibility and selection decisions."""
from datetime import datetime, timedelta
import json
import os
import fcntl

from ..core.state_store import StatePath
from ..core.topic_evidence import POOL, MIN_SCORE, MAX_AGE, _check, read
from ..core.state_errors import StateUnreadable
from ..core import account, config
from ..guards.reply_admission import is_blocked_account
from ..guards.active_hours import now_local
from ..x import x_urls

ARCHIVE = StatePath("reply_archive.jsonl")
# Operator incident 2026-10-12: thirty reviews exceeded the local model's
# 1,800-token output budget and stalled every selection cycle.
BATCH_SIZE = 8
COLLECT_SECONDS = 60


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
                   "reposts": tweet.get("reposts") or old.get("reposts", 0),
                   "has_video": bool(tweet.get("has_video", old.get("has_video", False))),
                   "is_reply": bool(tweet.get("is_reply") or text.lstrip().startswith("@")),
                   "state": old.get("state", "observed"),
                   "reason": old.get("reason", "not yet admitted by a scan’s filters")}
            if changed and row["state"] not in {"shipped", "closed", "processing", "skipped"}:
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
            if row["state"] in {"processing", "shipped", "closed", "skipped"}:
                continue
            author = x_urls.author(candidate.url)
            if config.is_own_handle(author) or is_blocked_account(author):
                row.update(eligible=False, state="rejected", reason="own or Blocked account")
                events.append(dict(kind="decision", id=key, state="rejected", reason=row["reason"], ts=stamp))
                continue
            if job.debate_turn or candidate.context or row.get("is_reply") or candidate.text.lstrip().startswith("@"):
                row.update(eligible=False, state="rejected", reason="conversation replies are disabled")
                continue
            if not account.current().niche.matches_post(row["text"]):
                row.update(eligible=False, state="rejected", reason="post is outside the Account's niche")
                events.append(dict(kind="decision", id=key, state="rejected", reason=row["reason"], ts=stamp))
                continue
            # A widened topic policy may admit a rediscovered post previously
            # refused by the keyword gate. Never recycle a model rejection.
            if row["state"] in {"observed", "queued"} or (
                    row["state"] == "rejected" and row.get("score") is None
                    and row.get("reason") == "post is outside the Account's niche"):
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
        # Recheck saved candidates after a policy change or a restart too.
        if not account.current().niche.matches_post(row["text"]):
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
            on_topic = review.get("on_topic") is True
            score = review["score"] if on_topic else 0
            minimum = account.current().replies.minimum_score(x_urls.author(row["url"]))
            row.update(score=score, on_topic=on_topic, reason=review["reason"], angle=review["angle"],
                       reviewed_at=stamp, state="ready" if score >= minimum else "rejected")
            events.append(dict(kind="reviewed", ts=stamp, **{**review, "score": score, "on_topic": on_topic}))
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
