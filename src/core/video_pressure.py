"""Best-effort, bounded reply telemetry; video observability cannot break replies."""
from contextlib import contextmanager
import sqlite3
import threading
import time
import uuid

from . import settings, state_store

_lock = threading.Lock()
_pending = 0


@contextmanager
def model_call(provider, timeout):
    """Observe shared model occupancy without delaying or changing Reply calls."""
    ident = uuid.uuid4().hex
    def write(done=False):
        if not settings.get("VIDEO_ENABLED"):
            return
        try:
            db = sqlite3.connect("file:" + str(state_store.StatePath("video_pipeline.sqlite3")) + "?mode=rw",
                                 uri=True, timeout=.005)
            try:
                now = time.time()
                if done:
                    db.execute("UPDATE model_calls SET finished=? WHERE id=?", (now, ident))
                else:
                    db.execute("INSERT INTO model_calls VALUES(?,?,?,?,NULL)",
                               (ident, provider, now, now + min(600, (timeout or 360) + 10)))
                db.commit()
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            pass
    write()
    try:
        yield
    finally:
        write(done=True)


def observe(phase, seconds, backlog):
    if not settings.get("VIDEO_ENABLED"):
        return
    # Never create/migrate the database on a reply thread and never wait on a
    # media writer. A dropped telemetry sample is preferable to reply latency.
    path = state_store.StatePath("video_pipeline.sqlite3")
    try:
        db = sqlite3.connect("file:" + str(path) + "?mode=rw", uri=True, timeout=.005)
        try:
            db.execute("INSERT INTO reply_samples(at,phase,seconds,backlog) VALUES(?,?,?,?)", (time.time(), phase, seconds, backlog))
            db.commit()
        finally:
            db.close()
    except (OSError, sqlite3.Error):
        pass


@contextmanager
def measure(phase):
    global _pending
    if not settings.get("VIDEO_ENABLED"):
        yield
        return
    start = time.monotonic()
    with _lock:
        _pending += 1
        backlog = _pending
    observe("queue", 0, backlog)
    try:
        yield
    finally:
        with _lock:
            _pending -= 1
            backlog = _pending
        observe(phase, time.monotonic() - start, backlog)


def pressure(store, cfg, now, *, resources=None):
    """Ordinary replies do not pause discovery: only measured pressure does."""
    if resources is None:
        import os
        import psutil
        resources = {"load": os.getloadavg()[0] / max(1, os.cpu_count() or 1),
                     "free_mb": psutil.virtual_memory().available / 1024 ** 2}
    store.set_meta("resource_observation", {**resources, "observed_at": now})
    if resources["load"] > cfg.max_load_per_cpu:
        return "CPU pressure"
    if resources["free_mb"] < cfg.min_free_memory_mb:
        return "memory pressure"
    samples = store.rows("SELECT * FROM reply_samples WHERE at>? ORDER BY at DESC LIMIT 1000", (now - 900,))
    latest = samples[0] if samples else None
    if latest and latest["backlog"] > cfg.max_reply_backlog:
        return "reply backlog"
    baseline = store.meta("reply_baseline_p95")
    latencies = sorted(r["seconds"] for r in samples if r["phase"] == "confirmed")
    if baseline and len(latencies) >= cfg.min_latency_samples:
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * .95))]
        if p95 > baseline * cfg.reply_latency_ratio:
            return "reply p95 exceeds comparable baseline"
    return ""
