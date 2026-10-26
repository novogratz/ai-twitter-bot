"""Frequent, deterministic discovery of new originals by operator-picked handles."""
from datetime import datetime, timedelta
import time

from ..core import account, config, settings
from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile
from ..guards import active_hours
from ..guards.active_hours import OutsideActiveHours, require_active
from ..x import scraper, twitter_client, x_urls
from . import reply_pipeline, reply_source
from .direct_reply import reply_call

STATE = StateFile("priority_watch_state.json", {}, GUARDED)
JOB = reply_pipeline.Job("priority_watch", "PRIORITY", reply_call=reply_call, pipelined=True)
_retry_after = {}  # process-local backoff only; permanent claims stay at the chokepoints


def _start_times(handles) -> dict:
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


def run_priority_watch_cycle():
    handles = account.current().auto_engage_handles
    if not handles:
        return
    require_active()
    started = _start_times(handles)
    candidates = []
    for handle in handles:
        # A dedicated Latest search never depends on the random profile pools.
        tweets = reply_pipeline.scrape(
            "PRIORITY", f"@{handle}", scraper.scrape_x_search,
            f"from:{handle} -filter:replies -filter:retweets", tab="live",
            max_tweets=settings.get("PRIORITY_WATCH_SCAN_LIMIT"), text_limit=1000)
        candidates.extend(_candidates(handle, tweets, started[handle]))

    attempts = 0
    for candidate in candidates:
        require_active()
        # One failed or rate-limited action must not hide the other action types.
        for action_id, action in (("like", twitter_client.like_priority_post),
                                  ("repost", twitter_client.repost_tweet)):
            key = (x_urls.status_id(candidate.url), action_id)
            if attempts >= 8 or _retry_after.get(key, 0) > time.monotonic():
                continue
            attempts += 1
            try:
                outcome = action(candidate.url)
                log.info("[PRIORITY] %s %s: %s", action.__name__, candidate.url, outcome.value)
                # Avoid reopening the same refused short post every minute.
                # No permanent skip: transient refusals retry in five minutes.
                delay = (3600 if outcome or outcome.value == "already_liked" else
                         120 if outcome.value in {"failed", "unconfirmed"} else 300)
                _retry_after[key] = time.monotonic() + delay
            except (OutsideActiveHours, StateUnreadable):
                raise
            except Exception:
                _retry_after[key] = time.monotonic() + 120
                log.exception("[PRIORITY] %s failed for %s", action.__name__, candidate.url)

    now = time.monotonic()
    for key in list(_retry_after):
        if _retry_after[key] <= now:
            del _retry_after[key]

    reply_pipeline.run(JOB, candidates, reply_pipeline.Cycle(),
                       max_generations=settings.get("PRIORITY_WATCH_MAX_REPLIES"))
