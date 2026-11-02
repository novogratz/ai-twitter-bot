from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3

import pytest

from src.core import video_pressure
from src.video import workers
from src.video.store import Store


def test_atomic_job_claim_and_fencing_after_crash(video_store, video_cfg):
    video_store.enqueue("media", "a", 100)
    with ThreadPoolExecutor(8) as pool:
        claims = list(pool.map(lambda n: video_store.claim("media", str(n), 100, video_cfg), range(8)))
    first = next(c for c in claims if c)
    assert sum(c is not None for c in claims) == 1
    later = 101 + video_cfg.lease_seconds
    second = video_store.claim("media", "replacement", later, video_cfg)
    assert second["token"] != first["token"]
    assert not video_store.finish(first, later)
    assert video_store.finish(second, later)


def test_bounded_retries_and_backoff(video_store, video_cfg):
    video_store.enqueue("discovery", "instagram", 100)
    clock = 100
    for _ in range(video_cfg.max_attempts):
        job = video_store.claim("discovery", "worker", clock, video_cfg)
        assert job
        video_store.finish(job, clock, error="provider failed")
        assert video_store.claim("discovery", "worker", clock + 1, video_cfg) is None
        clock += 1000
    assert video_store.claim("discovery", "worker", clock, video_cfg) is None
    assert video_store.rows("SELECT state FROM jobs")[0]["state"] == "dead"


def test_circuit_and_shared_budget_preserve_publishing_headroom(video_store, video_cfg):
    limit = video_cfg.request_budget - video_cfg.publishing_request_reserve
    assert video_store.budget("instagram", "requests", limit, limit, 100)
    assert not video_store.budget("tiktok", "requests", 1, limit, 100)
    assert video_store.budget("x", "requests", 1, video_cfg.request_budget, 100)
    video_store.circuit("instagram", 100, failed=True, retry_after=120)
    assert not video_store.circuit_ready("instagram", 219)
    assert video_store.circuit_ready("instagram", 220)


def test_unused_download_reservations_are_refunded(video_store):
    assert video_store.budget("source", "download_bytes", 100, 150, 100)
    assert not video_store.budget("other", "download_bytes", 100, 150, 100)
    video_store.refund_budget("source", "download_bytes", 90, 100)
    assert video_store.budget("other", "download_bytes", 100, 150, 100)
    assert sum(r["amount"] for r in video_store.rows("SELECT amount FROM costs")) == 110


def test_partial_byte_reservations_share_the_ceiling_atomically(video_store):
    assert video_store.budget("source", "download_bytes", 80, 150, 100)
    with ThreadPoolExecutor(4) as pool:
        amounts = list(pool.map(lambda n: video_store.reserve_up_to(str(n), "download_bytes", 50, 150, 100), range(4)))
    assert sorted(amounts) == [0, 0, 20, 50]
    assert sum(r["amount"] for r in video_store.rows("SELECT amount FROM costs")) == 150


def test_normal_replies_do_not_pause_and_measured_pressure_resumes(video_store, video_cfg):
    cfg = replace(video_cfg, min_latency_samples=3)
    resources = {"load": .1, "free_mb": 10000}
    video_store.set_meta("reply_baseline_p95", 1)
    with video_store.transaction() as db:
        for n in range(3):
            db.execute("INSERT INTO reply_samples(at,phase,seconds,backlog) VALUES(100,'confirmed',1,1)")
    assert video_pressure.pressure(video_store, cfg, 100, resources=resources) == ""
    with video_store.transaction() as db:
        db.execute("UPDATE reply_samples SET seconds=1.2")
    assert "p95" in video_pressure.pressure(video_store, cfg, 101, resources=resources)
    assert video_pressure.pressure(video_store, cfg, 1100, resources=resources) == ""
    assert video_pressure.pressure(video_store, cfg, 1100, resources={"load": 2, "free_mb": 10000}) == "CPU pressure"


def test_discovery_runs_overnight_with_publisher_closed(video_store, video_cfg, at, monkeypatch):
    from src.video import schedule, connectors
    monkeypatch.setattr(video_pressure, "pressure", lambda *a, **kw: "")
    monkeypatch.setattr(schedule, "utc_now", lambda: at(1))
    monkeypatch.setattr("src.video.workers.time.time", lambda: at(1).timestamp())
    calls = []
    monkeypatch.setattr(connectors, "discover", lambda *a: calls.append("discovery") or "ok")
    workers.seed_jobs(video_store, video_cfg, at(1).timestamp())
    assert workers.run_once("discovery", video_store, video_cfg, "test", now=at(1).timestamp()) == "ok"
    assert calls == ["discovery"]
    assert workers.run_once("publisher", video_store, video_cfg, "test", now=at(1).timestamp()) == "waiting"
    job = video_store.rows("SELECT due FROM jobs WHERE item='instagram'")[0]
    assert job["due"] == at(1).timestamp() + video_cfg.night_poll_seconds


def test_corrupt_database_is_not_reset(tmp_path):
    path = tmp_path / "bad.db"
    path.write_bytes(b"broken durable state")
    with pytest.raises(sqlite3.DatabaseError):
        Store(path)
    assert path.read_bytes() == b"broken durable state"


def test_media_queue_cannot_starve_novelty(video_store, video_cfg, ready, monkeypatch):
    from src.video import media, reconcile
    import time
    ready()
    now = time.time()
    video_store.enqueue("media", "waiting-media", now)
    video_store.enqueue("novelty", "clip1", now)
    video_store.set_meta("prefer_api", True)
    monkeypatch.setattr(video_pressure, "pressure", lambda *a, **k: "")
    calls = []
    monkeypatch.setattr(reconcile, "novelty", lambda *a: calls.append("novelty"))
    monkeypatch.setattr(media, "process", lambda *a: calls.append("media"))
    cfg = replace(video_cfg, x_reads_enabled=True)
    workers.run_once("media", video_store, cfg, "worker", now=now)
    workers.run_once("media", video_store, cfg, "worker", now=now + 1)
    assert calls == ["novelty", "media"]
