"""Coordinate sourced news and native videos without releasing uncertain claims."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import sqlite3
import threading

from ..core import config as core_config
from . import config
from .store import DATABASE

LOCK = threading.RLock()
_news_claim = ContextVar("news_publication_claim", default=None)


def news_enabled(cfg=None):
    return config.enabled() and (cfg or config.load()).news_enabled


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with LOCK:
            return function(*args, **kwargs)
    return wrapped


@contextmanager
def claimed_news(key, text):
    receipt = {}
    token = _news_claim.set((key, text, receipt))
    try:
        yield receipt
    finally:
        _news_claim.reset(token)


def matches_news_claim(text):
    claim = _news_claim.get()
    return bool(claim and claim[1] == text)


def note_news_receipt(url):
    claim = _news_claim.get()
    if claim:
        claim[2]["published_url"] = url


def _video_rows(store=None):
    query = "SELECT id,state,confirmed FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown','confirmed')"
    if store is not None:
        return store.rows(query)
    path = Path(str(DATABASE))
    if not path.exists():
        return []
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query)]


def refusal(kind, now, cfg=None, *, store=None, journal=None, reservation=None):
    """One shared exclusion/spacing policy, checked again at each write boundary."""
    cfg = cfg or config.load()
    if not news_enabled(cfg):
        return ""
    from ..editorial.slot_journal import FileJournal, stamp
    from ..guards import action_guard, repost_store
    journal = journal or FileJournal()
    claim = _news_claim.get() if kind == "news" else None
    pending = dict(journal.get("pending_sources", {}))
    own = pending.pop(claim[0], None) if claim else None
    if claim and (not own or own.get("text", "") + "\n\n" + own.get("url", "") != claim[1]):
        return "news reservation changed or missing"
    # A mark without its source is still an uncertain submission.
    for clock, state in journal.get("slots", {}).items():
        key = journal.get("date", "") + "/" + clock
        if state == "pending" and (not claim or key != claim[0]):
            pending.setdefault(key, {})
    if pending or repost_store.pending_times():
        return "unresolved profile submission"
    try:
        rows = _video_rows(store)
    except (sqlite3.Error, ValueError, OSError):
        return "video publication state unreadable"
    if any(r["state"] != "confirmed" and r["id"] != reservation for r in rows):
        return "video publication reserved or uncertain"
    if kind == "news":
        submitted = journal.submissions(now.date())
        used = max(action_guard.count_today(action_guard.POST), submitted.published)
        used += action_guard.count_today(action_guard.QUOTE) + action_guard.count_today(action_guard.RETWEET)
        if used + submitted.pending - bool(own) >= cfg.news_daily_cap:
            return "daily news ceiling reached"
        # A late news draft must not consume the spacing needed by a ready,
        # imminent video. A scheduled collision gives video its bounded turn.
        from .schedule import next_slot
        upcoming = next_slot(now, cfg)
        gap = max(cfg.min_spacing_seconds, core_config.MIN_SECONDS_BETWEEN_POSTS + core_config.POST_JITTER_SECONDS)
        if upcoming and 0 <= upcoming[1].timestamp() - now.timestamp() < gap:
            from .store import Store
            if (store or Store()).rows("SELECT 1 FROM candidates WHERE state='ready' LIMIT 1"):
                return "imminent ready video has publication priority"
    times = [r["confirmed"] for r in rows if r["state"] == "confirmed" and r["confirmed"] is not None]
    times += [at.timestamp() for p in journal.published() if (at := stamp(p.get("ts", "")))]
    for action in (action_guard.POST, action_guard.QUOTE, action_guard.RETWEET):
        at = action_guard._ledger().last_write(action)
        if at:
            times.append(at.timestamp())
    gap = max(cfg.min_spacing_seconds, core_config.MIN_SECONDS_BETWEEN_POSTS + core_config.POST_JITTER_SECONDS)
    if times and now.timestamp() - max(times) < gap:
        return "shared news/video publication spacing"
    return ""
