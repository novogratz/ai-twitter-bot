from dataclasses import replace

import pytest

from src.video import reconcile, source_browser, workers
from src.video.security import AccessError
from src.x import safari_video


@pytest.fixture
def browser_reads(video_store, video_cfg, at, monkeypatch):
    cfg = replace(video_cfg, publishing_transport="safari")
    class Client:
        def __init__(self, *args): pass
        def preflight(self, **kwargs): return {"account_verified": True}
    monkeypatch.setattr(safari_video, "SafariVideoClient", Client)
    monkeypatch.setattr(source_browser, "capture_next", lambda *args: None)
    monkeypatch.setattr(reconcile, "collect_outcomes", lambda *args: None)
    video_store.set_meta("next_reconciliation", at().timestamp() + 1000)
    return cfg, Client


def test_archive_failure_does_not_disable_novelty_and_success_resets_its_own_circuit(video_store, browser_reads, ready, at, monkeypatch):
    cfg, _ = browser_reads
    now = at().timestamp()
    video_store.set_meta("history_import_complete", False)
    def fail(*args):
        raise AccessError("native video duration unavailable")
    monkeypatch.setattr(reconcile, "import_history", fail)
    workers._x_work(video_store, cfg, "worker", now)
    assert video_store.circuit_ready("x_browser", now + 1)
    assert not video_store.circuit_ready("x_browser:history", now + 1)
    assert video_store.rows("SELECT item,detail FROM events WHERE kind='x_read_failed'") == [
        {"item": "history", "detail": "native video duration unavailable"}]
    ready()
    video_store.enqueue("novelty", "clip1", now)
    calls = []
    monkeypatch.setattr(reconcile, "novelty", lambda *args: calls.append("novelty"))
    workers._x_work(video_store, cfg, "worker", now + 1)
    assert calls == ["novelty"]
    monkeypatch.setattr(reconcile, "import_history", lambda *args: calls.append("history"))
    workers._x_work(video_store, cfg, "worker", now + 301)
    assert calls == ["novelty", "history"]
    assert video_store.rows("SELECT failures FROM circuits WHERE provider='x_browser:history'") == [{"failures": 0}]
    assert not video_store.meta("history_import_complete")  # success call alone never invents coverage


def test_source_failure_has_its_own_cooldown_and_keeps_unknown_publication_claims(video_store, browser_reads, at, monkeypatch):
    cfg, _ = browser_reads
    def fail(*args):
        raise AccessError("browser read budget exhausted")
    monkeypatch.setattr(source_browser, "capture_next", fail)
    with video_store.transaction() as db:
        db.execute("INSERT INTO content_claims VALUES('candidate','unknown-publication')")
    workers._x_work(video_store, cfg, "worker", at().timestamp())
    assert video_store.circuit_ready("x_browser", at().timestamp() + 1)
    assert not video_store.circuit_ready("x_browser:source", at().timestamp() + 1)
    assert video_store.rows("SELECT * FROM content_claims") == [{"candidate": "candidate", "reservation": "unknown-publication"}]


def test_preflight_identity_failure_still_blocks_all_browser_work(video_store, browser_reads, ready, at, monkeypatch):
    cfg, client = browser_reads
    def fail(self, **kwargs):
        raise AccessError("Safari login/account could not be verified")
    monkeypatch.setattr(client, "preflight", fail)
    ready()
    video_store.enqueue("novelty", "clip1", at().timestamp())
    calls = []
    monkeypatch.setattr(reconcile, "novelty", lambda *args: calls.append("novelty"))
    workers._x_work(video_store, cfg, "worker", at().timestamp())
    assert not video_store.circuit_ready("x_browser", at().timestamp() + 1)
    assert calls == []
    assert video_store.rows("SELECT state FROM jobs WHERE kind='novelty'") == [{"state": "pending"}]


def test_failure_diagnostic_never_echoes_arbitrary_provider_content(video_store):
    workers._read_failure(video_store, "history", AccessError("https://source.test/?token=secret-canary"), 100)
    detail = video_store.rows("SELECT detail FROM events")[0]["detail"]
    assert detail == "AccessError" and "secret-canary" not in detail


@pytest.mark.parametrize("stage", ["history", "novelty"])
def test_provider_rate_limit_keeps_shared_cooldown(video_store, browser_reads, ready, at, monkeypatch, stage):
    cfg, _ = browser_reads
    now = at().timestamp()
    def fail(*args):
        raise AccessError("provider HTTP 429", status=429, retry_after=900)
    if stage == "novelty":
        ready()
        video_store.enqueue("novelty", "clip1", now)
        monkeypatch.setattr(reconcile, "novelty", fail)
    else:
        video_store.set_meta("history_import_complete", False)
        monkeypatch.setattr(reconcile, "import_history", fail)
    workers._x_work(video_store, cfg, "worker", now)
    assert not video_store.circuit_ready("x_browser", now + 899)
    assert video_store.circuit_ready("x_browser", now + 901)
