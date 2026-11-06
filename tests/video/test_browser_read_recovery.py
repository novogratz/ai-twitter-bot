from dataclasses import replace

import pytest

from src.core import work_priority
from src.video import reconcile, source_browser, workers
from src.video.security import AccessError, Deferred
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


def test_two_deferred_novelty_turns_allow_one_source_turn_after_reconciliation(
        video_store, browser_reads, ready, at, monkeypatch):
    cfg, _ = browser_reads
    cfg = replace(cfg, buffer_target=2)
    clock = [at(10).timestamp()]
    monkeypatch.setattr(workers.time, "time", lambda: clock[0])
    monkeypatch.setattr(workers.schedule, "utc_now", lambda: at(10))
    video_store.set_meta("next_reconciliation", clock[0] + 1000)
    doc = ready(when=at(10))
    doc["novelty"] = {"state": "unchecked"}
    video_store.save_candidate("clip1", doc, clock[0], state="held")
    video_store.enqueue("novelty", "clip1", clock[0])
    calls = []
    def pending(*args):
        calls.append("novelty")
        raise Deferred("fixture frames still pending", retry_after=10)
    def source(*args):
        calls.append("source")
        return "source media captured"
    monkeypatch.setattr(reconcile, "novelty", pending)
    monkeypatch.setattr(source_browser, "capture_next", source)
    monkeypatch.setattr(reconcile, "reconcile_unknown", lambda *a: calls.append("reconciliation"))
    for _ in range(2):
        assert workers._x_work(video_store, cfg, "worker", clock[0]) == "novelty checked"
        clock[0] += 10
    assert calls == ["novelty", "novelty"]
    assert video_store.meta("novelty_reads_since_source") == 2
    video_store.set_meta("next_reconciliation", clock[0])
    assert workers._x_work(video_store, cfg, "worker", clock[0]) == "source player checked"
    assert calls == ["novelty", "novelty", "reconciliation", "source"]
    assert video_store.meta("novelty_reads_since_source") == 0
    assert video_store.rows("SELECT state,attempts FROM jobs WHERE kind='novelty'") == [
        {"state": "pending", "attempts": 0}]
    assert video_store.candidate("clip1")["document"]["novelty"] == {"state": "unchecked"}
    clock[0] += 10
    assert workers._x_work(video_store, cfg, "worker", clock[0]) == "novelty checked"
    assert calls[-1] == "novelty" and calls.count("source") == 1
    assert not video_store.rows("SELECT * FROM reservations")


@pytest.mark.parametrize("reserve,expected", [(0, work_priority.REPLY), (2, work_priority.BACKGROUND)])
def test_reserve_level_sets_browser_priority_without_startup_or_nearby_slot(
        video_store, browser_reads, ready, at, monkeypatch, reserve, expected):
    cfg, client = browser_reads
    cfg = replace(cfg, buffer_target=2)
    now = at(10).timestamp()
    monkeypatch.setattr(workers.time, "time", lambda: now)
    monkeypatch.setattr(workers.schedule, "utc_now", lambda: at(10))
    video_store.set_meta("next_reconciliation", now + 1000)
    assert video_store.meta("history_import_complete") is True
    assert not video_store.rows("SELECT * FROM startup")
    assert workers.schedule.next_slot(at(10), cfg)[1].timestamp() - now > cfg.preparation_lead_seconds
    for index in range(reserve):
        ready("reserve" + str(index), when=at(10))
    calls = []
    def preflight(self, **kwargs):
        calls.append(("preflight", work_priority.current_priority()))
    def source(*args):
        calls.append(("source", work_priority.current_priority()))
        return "source media captured"
    monkeypatch.setattr(client, "preflight", preflight)
    monkeypatch.setattr(source_browser, "capture_next", source)
    assert workers._x_work(video_store, cfg, "worker", now) == "source player checked"
    assert calls == [("preflight", expected), ("source", expected)]
    assert work_priority.current_priority() == work_priority.BACKGROUND


@pytest.mark.parametrize("denial", ["existing_circuit", "preflight", "reconciliation"])
def test_global_denial_blocks_the_waiting_source_turn(video_store, browser_reads, at, monkeypatch, denial):
    cfg, client = browser_reads
    now = at(10).timestamp()
    monkeypatch.setattr(workers.time, "time", lambda: now)
    monkeypatch.setattr(workers.schedule, "utc_now", lambda: at(10))
    video_store.set_meta("novelty_reads_since_source", 2)
    video_store.set_meta("next_reconciliation", now)
    calls = []
    def preflight(self, **kwargs):
        calls.append("preflight")
        if denial == "preflight":
            raise AccessError("Safari login/account could not be verified", status=401)
    def denied_reconciliation(*args):
        calls.append("reconciliation")
        raise AccessError("provider HTTP 429", status=429, retry_after=900)
    monkeypatch.setattr(client, "preflight", preflight)
    monkeypatch.setattr(reconcile, "reconcile_unknown", denied_reconciliation)
    monkeypatch.setattr(source_browser, "capture_next", lambda *a: pytest.fail("source read bypassed global denial"))
    if denial == "existing_circuit":
        video_store.circuit("x_browser", now, failed=True, retry_after=900)
    assert workers._x_work(video_store, cfg, "worker", now) is None
    assert not video_store.circuit_ready("x_browser", now + 1)
    assert video_store.meta("novelty_reads_since_source") == 2
    expected = [] if denial == "existing_circuit" else ["preflight"]
    assert calls == expected + (["reconciliation"] if denial == "reconciliation" else [])


def test_x_media_capacity_waits_do_not_consume_attempts_or_cache_partial_fingerprint(
        video_store, browser_reads, at, monkeypatch):
    cfg, _ = browser_reads
    clock = [at().timestamp()]
    monkeypatch.setattr(workers.time, "time", lambda: clock[0])
    video_store.set_meta("x_media:fixture", {"media_key": "fixture"})
    video_store.enqueue("x_media", "fixture", clock[0])
    def pending(source, store, config, now, *, offload):
        assert source == {"media_key": "fixture"} and offload is False
        raise Deferred("fixture byte capacity wait", retry_after=37)
    monkeypatch.setattr(reconcile, "media_fingerprint", pending)
    for _ in range(cfg.max_attempts + 2):
        assert workers._x_media_work(video_store, cfg, "worker", clock[0]) is True
        assert video_store.meta("x_fingerprint:fixture") is None
        assert video_store.rows("SELECT state,attempts,error,due FROM jobs WHERE kind='x_media'") == [
            {"state": "pending", "attempts": 0, "error": "", "due": clock[0] + 37}]
        assert workers._x_media_work(video_store, cfg, "worker", clock[0] + 36) is False
        clock[0] += 37
    completed = {"fixture": "complete fingerprint"}
    monkeypatch.setattr(reconcile, "media_fingerprint", lambda *a, **k: completed)
    assert workers._x_media_work(video_store, cfg, "worker", clock[0]) is True
    assert video_store.meta("x_fingerprint:fixture") == completed
    assert video_store.rows("SELECT state,error FROM jobs WHERE kind='x_media'") == [{"state": "done", "error": ""}]
