"""Frequent, deterministic discovery of new originals by operator-picked handles."""
from datetime import datetime, timedelta
import time
import threading

from ..core import account, config, settings, work_priority, watch_discovery
from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile
from ..guards import active_hours
from ..guards.active_hours import OutsideActiveHours, require_active
from ..x import scraper, twitter_client, x_urls
from . import reply_pipeline, reply_source
from .direct_reply import reply_call

STATE = StateFile("priority_watch_state.json", {}, GUARDED)
JOB = reply_pipeline.Job("priority_watch", "PRIORITY", reply_call=reply_call)
_retry_after = {}  # process-local backoff only; permanent claims stay at the chokepoints
_pending = {}
_queue_lock = threading.RLock()


def _start_times(handles) -> dict:
    with _queue_lock:
        return _read_start_times(handles)


def _read_start_times(handles) -> dict:
    """Persist a first-enable boundary; restarts never replay the old backlog."""
    data = STATE.read()
    try:
        for handle, raw in data.items():
            if not isinstance(handle, str) or not datetime.fromisoformat(raw).tzinfo:
                raise ValueError("invalid watch boundary")
    except (TypeError, ValueError) as exc:
        raise StateUnreadable("Priority watch boundaries are malformed") from exc
    changed = False
    for handle in handles:
        if handle not in data:
            data[handle] = active_hours.now_local().isoformat()
            changed = True
    if changed and not config.dry_run():
        STATE.write(data)
    return {handle: datetime.fromisoformat(data[handle]) for handle in handles}


def _candidates(handle: str, tweets: list, started: datetime) -> list:
    declaration = reply_source.Declaration(
        max_age=timedelta(hours=settings.get("PRIORITY_WATCH_MAX_AGE_HOURS")),
        root_only=True, author=handle)
    candidates, seen = [], set()
    for candidate in reply_source.select(tweets, declaration, f"PRIORITY/{handle}"):
        url = x_urls.canonical_status_url(candidate.url)
        if not url or x_urls.author(url) != handle or x_urls.status_id(url) in seen:
            continue
        posted = x_urls.posted_at(url)
        if posted is None or posted < started:
            continue
        seen.add(x_urls.status_id(url))
        candidates.append(reply_pipeline.Candidate(url, candidate.text, candidate.source))
    return sorted(candidates, key=lambda c: int(x_urls.status_id(c.url)), reverse=True)


def observe(tweets):
    """Offer discoveries from every scrape. Queueing never claims a Reply."""
    handles = account.current().auto_engage_handles
    if not handles or not any(x_urls.author(t.get("url", "")) in handles for t in tweets):
        return
    require_active()
    started = _start_times(handles)
    with _queue_lock:
        for handle in handles:
            for candidate in _candidates(handle, tweets, started[handle]):
                _pending[candidate.url] = candidate
        _prune()


def _prune():
    """Bound disposable discoveries; the permanent action histories stay untouched."""
    handles = account.current().auto_engage_handles
    maximum = timedelta(hours=settings.get("PRIORITY_WATCH_MAX_AGE_HOURS"))
    valid = [c for c in _pending.values() if x_urls.author(c.url) in handles
             and (age := x_urls.age(c.url)) is not None and timedelta(0) <= age <= maximum]
    valid.sort(key=lambda c: int(x_urls.status_id(c.url)), reverse=True)
    _pending.clear()
    _pending.update((c.url, c) for c in valid[:settings.get("PRIORITY_WATCH_QUEUE_LIMIT")])
    for key in list(_retry_after):
        if key[0] not in _pending or _retry_after[key] <= time.monotonic():
            del _retry_after[key]


def _discovered():
    require_active()
    if not account.current().auto_engage_handles:
        return []
    # Refuse dispatch if guarded watch history becomes unreadable after discovery.
    started = _start_times(account.current().auto_engage_handles)
    observe(watch_discovery.take())
    with _queue_lock:
        _prune()
        return [c for c in _pending.values()
                if x_urls.posted_at(c.url) >= started[x_urls.author(c.url)]]


def run_priority_watch_cycle():
    """Only discover. Slow actions and model calls cannot occupy this worker."""
    handles = account.current().auto_engage_handles
    if not handles:
        return
    require_active()
    _start_times(handles)
    for handle in handles:
        with work_priority.scope(work_priority.WATCH):
            tweets = reply_pipeline.scrape(
                "PRIORITY", f"@{handle}", scraper.scrape_x_search,
                f"from:{handle} -filter:replies -filter:retweets", tab="live",
                max_tweets=settings.get("PRIORITY_WATCH_SCAN_LIMIT"), text_limit=1200, scroll_passes=0)
        observe(tweets)


def _ready(url, action):
    with _queue_lock:
        return _retry_after.get((url, action), 0) <= time.monotonic()


def _backoff(url, action, delay):
    with _queue_lock:
        _retry_after[(url, action)] = time.monotonic() + delay


def run_priority_actions_cycle():
    """Independent actions stay responsive while a Reply is being generated."""
    attempts = 0
    for candidate in _discovered():
        require_active()
        # One failed or rate-limited action must not hide the other action types.
        for action_id, action in (("like", twitter_client.like_priority_post),
                                  ("repost", twitter_client.repost_tweet)):
            if (attempts >= settings.get("PRIORITY_WATCH_ACTIONS_PER_CYCLE")
                    or not _ready(candidate.url, action_id)):
                continue
            attempts += 1
            try:
                with work_priority.scope(work_priority.WATCH):
                    outcome = action(candidate.url)
                log.info("[PRIORITY] %s %s: %s", action.__name__, candidate.url, outcome.value)
                # Avoid reopening the same refused post every dispatch.
                # No permanent skip: transient refusals retry in five minutes.
                delay = (3600 if outcome or outcome.value == "already_liked" else
                         120 if outcome.value in {"failed", "unconfirmed"} else 300)
                _backoff(candidate.url, action_id, delay)
            except (OutsideActiveHours, StateUnreadable):
                raise
            except Exception:
                _backoff(candidate.url, action_id, 120)
                log.exception("[PRIORITY] %s failed for %s", action.__name__, candidate.url)


def run_priority_reply_cycle():
    """Re-select newest discoveries after each generation, even if polls continue."""
    candidates = [c for c in _discovered() if _ready(c.url, "reply")]
    if not candidates:
        return
    cycle = reply_pipeline.Cycle()
    try:
        with work_priority.scope(work_priority.WATCH):
            return reply_pipeline.run(JOB, candidates, cycle,
                                      max_generations=settings.get("PRIORITY_WATCH_MAX_REPLIES"))
    finally:
        for url in cycle.tried:
            _backoff(url, "reply", settings.get("PRIORITY_WATCH_REPLY_RETRY_SECONDS"))
