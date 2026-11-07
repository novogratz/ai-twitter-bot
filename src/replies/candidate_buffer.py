"""Unused sources between scans. Disposable memory, never a durable Reply claim."""
from dataclasses import replace
from datetime import timedelta
import threading
import time

from ..core import settings, reply_diagnostics
from ..x import x_urls
from . import reply_pipeline


class Buffer:
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = {}

    def _prune(self, now):
        expired = [sid for sid, candidate in self.entries.items() if candidate.expires_at <= now]
        for sid in expired:
            self.entries.pop(sid)
        if expired:
            reply_diagnostics.record("candidates", "expired", items=len(expired))
        limit = settings.get("REPLY_CANDIDATE_BUFFER_LIMIT")
        # A full ordinary buffer must not discard a just-discovered priority
        # author before ranking. Within each group, keep the freshest sources.
        large = reply_pipeline.priority_authors()
        oldest = sorted(self.entries, key=lambda sid: (
            x_urls.author(self.entries[sid].url) in large, int(sid)))[:max(0, len(self.entries) - limit)]
        for sid in oldest:
            self.entries.pop(sid)
        if oldest:
            reply_diagnostics.record("candidates", "evicted", items=len(oldest))

    def offer(self, candidates, *, max_age: timedelta):
        now, added = time.time(), 0
        ttl = settings.get("REPLY_CANDIDATE_BUFFER_TTL_SECONDS")
        with self.lock:
            self._prune(now)
            for candidate in candidates:
                url = x_urls.canonical_status_url(candidate.url)
                posted = x_urls.posted_at(url)
                if (not url or not posted or posted.timestamp() > now or not candidate.text.strip()
                        or candidate.is_reply or candidate.context or candidate.reply
                        or candidate.text.lstrip().startswith("@")):
                    continue
                expires = min(now + ttl, posted.timestamp() + max_age.total_seconds())
                if candidate.expires_at is not None:
                    expires = min(expires, candidate.expires_at)
                if expires <= now:
                    continue
                sid = x_urls.status_id(url)
                if sid in self.entries:
                    # Keep the earliest source horizon even when rediscovery
                    # supplies no counters. A wider lane can never extend TTL.
                    counters = {name: getattr(candidate, name) for name in ("likes", "views")
                                if type(getattr(candidate, name)) is int and getattr(candidate, name) >= 0}
                    self.entries[sid] = replace(self.entries[sid], **counters,
                                               expires_at=min(self.entries[sid].expires_at, expires))
                    continue
                self.entries[sid] = replace(candidate, url=url, expires_at=expires)
                added += 1
            self._prune(now)
        reply_diagnostics.record("candidates", "buffered", items=added)

    def pending(self):
        with self.lock:
            self._prune(time.time())
            # Re-read a tightened freshness setting as well as the stored horizon.
            max_age = timedelta(minutes=settings.get("DIRECT_REPLY_MAX_AGE_MINUTES"))
            for sid, candidate in list(self.entries.items()):
                age = x_urls.age(candidate.url)
                if age is None or age < timedelta(0) or age > max_age:
                    self.entries.pop(sid)
            return reply_pipeline.prioritize(self.entries.values(), diversify_authors=True, ordinary=True)

    def run(self, job, cycle, **budgets):
        candidates = self.pending()
        if not candidates or cycle.rate_limited:
            return 0
        reply_diagnostics.record("candidates", "offered", items=len(candidates))
        try:
            return reply_pipeline.run(job, candidates, cycle, ordinary_priority=True, **budgets)
        finally:
            # Only resolved work leaves the buffer. An unused lookahead, a
            # rate-limit result or an interrupted run remains unclaimed here.
            completed = {x_urls.status_id(url) for url in cycle.completed}
            with self.lock:
                for sid in completed:
                    self.entries.pop(sid, None)


SEARCH = Buffer()
FEEDS = {name: Buffer() for name in ("FEED", "FOLLOWING")}
