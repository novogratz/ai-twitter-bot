from dataclasses import replace
import json
import os
from unittest.mock import Mock

import pytest

from src.video import workers


OWNER = "424242:scheduler"


def running_job(store, *, kind="novelty", item="candidate", owner=OWNER, token="old-token", attempts=3):
    store.enqueue(kind, item, 100)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='running',owner=?,token=?,lease=9000,attempts=?,error='previous error' "
                   "WHERE kind=? AND item=?", (owner, token, attempts, kind, item))
    return store.rows("SELECT * FROM jobs WHERE kind=? AND item=?", (kind, item))[0]


def absent_process(monkeypatch):
    probe = Mock(side_effect=ProcessLookupError())
    monkeypatch.setattr(workers.os, "kill", probe)
    return probe


@pytest.mark.parametrize("attempts,remaining", [(1, 0), (3, 2), (0, 0)])
def test_absent_scheduler_read_is_due_now_and_refunds_only_abandoned_attempt(
        video_store, video_cfg, monkeypatch, attempts, remaining):
    job = running_job(video_store, attempts=attempts)
    probe = absent_process(monkeypatch)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 1
        assert workers.recover_orphaned_novelty_reads(video_store, 1001) == 0
    recovered = video_store.rows("SELECT * FROM jobs")[0]
    assert recovered == job | {"state": "pending", "due": 1000, "owner": None, "lease": None,
                              "token": None, "attempts": remaining}
    assert probe.call_args_list == [((424242, 0),), ((424242, 0),)]
    events = video_store.rows("SELECT at,kind,item,detail FROM events")
    assert len(events) == 1
    assert events[0] | {"detail": None} == {
        "at": 1000, "kind": "novelty_read_recovered", "item": "candidate", "detail": None}
    assert json.loads(events[0]["detail"]) == {
        "previous_owner": OWNER, "job_id": job["id"], "refunded_attempt": min(1, attempts)}
    # It can be claimed immediately, with the previous failures still counted.
    claimed = video_store.claim("novelty", f"{os.getpid()}:scheduler", 1000, video_cfg)
    assert claimed["attempts"] == remaining + 1
    assert claimed["token"] != job["token"]
    assert not video_store.finish(job, 1000), "the abandoned token must no longer finish this job"


@pytest.mark.parametrize("probe_result", [None, PermissionError(), OSError("unknown PID status"), OverflowError()])
def test_live_reused_or_uninspectable_pid_keeps_its_lease(video_store, monkeypatch, probe_result):
    job = running_job(video_store)
    probe = Mock(return_value=None, side_effect=probe_result)
    monkeypatch.setattr(workers.os, "kill", probe)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    assert not video_store.rows("SELECT * FROM events")
    probe.assert_called_once_with(424242, 0)


@pytest.mark.parametrize("owner", [None, "", "old-worker", "424242:media", "424242:scheduler:extra",
    "0:scheduler", "-1:scheduler", "0424242:scheduler", "424242:scheduler\n", "99999999999:scheduler"])
def test_ambiguous_owner_is_untouched(video_store, monkeypatch, owner):
    job = running_job(video_store, owner=owner)
    probe = absent_process(monkeypatch)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    probe.assert_not_called()


def test_own_pid_is_never_recovered(video_store, monkeypatch):
    job = running_job(video_store, owner=f"{os.getpid()}:scheduler")
    probe = absent_process(monkeypatch)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    probe.assert_not_called()


def test_missing_claim_token_is_untouched(video_store, monkeypatch):
    job = running_job(video_store, token=None)
    probe = absent_process(monkeypatch)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    probe.assert_not_called()


@pytest.mark.parametrize("kind", ["media", "inspect_source", "inspect_output", "x_media", "discovery", "publisher"])
def test_other_job_kinds_are_never_recovered(video_store, monkeypatch, kind):
    job = running_job(video_store, kind=kind)
    probe = absent_process(monkeypatch)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    probe.assert_not_called()


@pytest.mark.parametrize("state", ["pending", "done", "dead"])
def test_only_running_reads_are_recovered(video_store, monkeypatch, state):
    job = running_job(video_store)
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET state=?", (state,))
    probe = absent_process(monkeypatch)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job | {"state": state}]
    probe.assert_not_called()


def test_publisher_role_is_required(video_store, monkeypatch):
    job = running_job(video_store)
    probe = absent_process(monkeypatch)
    assert not workers.owns_role("publisher")
    with workers.role_lock("media"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    probe.assert_not_called()


def test_pid_reappearing_before_transaction_is_preserved(video_store, monkeypatch):
    job = running_job(video_store)
    probe = Mock(side_effect=[ProcessLookupError(), None])
    monkeypatch.setattr(workers.os, "kill", probe)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert video_store.rows("SELECT * FROM jobs") == [job]
    assert not video_store.rows("SELECT * FROM events")


@pytest.mark.parametrize("changed", [{"token": "successor-token"}, {"owner": "434343:scheduler"}, {"attempts": 4}])
def test_claim_race_cannot_refund_or_release_a_successor(video_store, monkeypatch, changed):
    job = running_job(video_store)
    absent_process(monkeypatch)
    original_rows = video_store.rows
    def race(sql, args=()):
        rows = original_rows(sql, args)
        if sql.startswith("SELECT id,item,owner,token,attempts FROM jobs"):
            with video_store.transaction() as db:
                field, value = next(iter(changed.items()))
                db.execute(f"UPDATE jobs SET {field}=? WHERE id=?", (value, job["id"]))
        return rows
    monkeypatch.setattr(video_store, "rows", race)
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 0
    assert original_rows("SELECT * FROM jobs") == [job | changed]
    assert not original_rows("SELECT * FROM events")


def test_recovery_preserves_uncertain_sends_claims_and_permanent_history(video_store, monkeypatch):
    running_job(video_store)
    absent_process(monkeypatch)
    with video_store.transaction() as db:
        db.execute("INSERT INTO reservations(id,slot,startup,candidate,state,created,updated,deadline,token,lease,caption) "
                   "VALUES('uncertain','slot','startup','candidate','publish_unknown',10,20,30,'send-token',9000,'caption')")
        db.execute("INSERT INTO content_claims VALUES('candidate','uncertain')")
        db.execute("INSERT INTO history VALUES('receipt',1,'{\"original_sha256\":\"posted-hash\"}')")
        db.execute("INSERT INTO slots(id,due,state,reservation) VALUES('slot',10,'reserved','uncertain')")
        db.execute("INSERT INTO startup(id,requested_day,requested,state,reservation) "
                   "VALUES('startup','2026-11-05',10,'reserved','uncertain')")
        db.execute("INSERT INTO startup_days VALUES('2026-11-05','startup','uncertain')")
        db.execute("INSERT INTO costs VALUES('2026-11-05','x','requests',9)")
    tables = ("reservations", "content_claims", "history", "slots", "startup", "startup_days", "costs", "meta")
    before = {table: video_store.rows(f"SELECT * FROM {table}") for table in tables}
    with workers.role_lock("publisher"):
        assert workers.recover_orphaned_novelty_reads(video_store, 1000) == 1
    assert {table: video_store.rows(f"SELECT * FROM {table}") for table in tables} == before


def test_supervisor_recovers_once_after_acquiring_safari_role(video_store, video_cfg, monkeypatch):
    running_job(video_store, item="first")
    absent_process(monkeypatch)
    monkeypatch.setattr(workers.config, "load", lambda: replace(video_cfg, publishing_transport="safari"))
    monkeypatch.setattr(workers, "Store", lambda: video_store)
    monkeypatch.setattr(workers, "runtime_generation", lambda cfg: {})
    monkeypatch.setattr(workers.time, "time", lambda: 1000)
    instance = workers.Supervisor()
    try:
        assert workers.owns_role("publisher")
        assert video_store.rows("SELECT state FROM jobs WHERE item='first'") == [{"state": "pending"}]
        second = running_job(video_store, item="second")
        instance._claim_browser_role()
        assert video_store.rows("SELECT * FROM jobs WHERE item='second'") == [second]
        assert len(video_store.rows("SELECT * FROM events WHERE kind='novelty_read_recovered'")) == 1
    finally:
        instance.stop()
    assert not workers.owns_role("publisher")


def test_api_supervisor_never_recovers_browser_read_jobs(video_store, video_cfg, monkeypatch):
    job = running_job(video_store)
    probe = absent_process(monkeypatch)
    monkeypatch.setattr(workers.config, "load", lambda: video_cfg)
    monkeypatch.setattr(workers, "Store", lambda: video_store)
    monkeypatch.setattr(workers, "runtime_generation", lambda cfg: {})
    instance = workers.Supervisor()
    try:
        assert not workers.owns_role("publisher")
        assert video_store.rows("SELECT * FROM jobs") == [job]
        probe.assert_not_called()
    finally:
        instance.stop()


def test_recovery_failure_does_not_abort_reply_startup(video_cfg, monkeypatch):
    monkeypatch.setattr(workers.config, "load", lambda: replace(video_cfg, publishing_transport="safari"))
    monkeypatch.setattr(workers, "runtime_generation", lambda cfg: {})
    monkeypatch.setattr(workers, "Store", Mock(side_effect=OSError("database unavailable")))
    instance = workers.Supervisor()
    try:
        assert workers.owns_role("publisher")
    finally:
        instance.stop()
