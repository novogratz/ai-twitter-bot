"""One new operator authorization must never reset an earlier send or loop on boot."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3

import pytest

from src.video import config, publisher, schedule, store
from tests.video.test_publisher import shipped


@pytest.fixture
def once_boot(video_store, video_cfg, at, monkeypatch):
    import main
    cfg = replace(video_cfg, startup_on_boot=True, startup_once="operator-next-start")
    monkeypatch.setattr(config, "load", lambda: cfg)
    monkeypatch.setattr(store, "Store", lambda: video_store)
    monkeypatch.setattr(schedule, "utc_now", lambda: at(10))
    return main._request_startup_video, cfg


def test_one_new_boot_video_preserves_todays_receipt_and_cannot_repeat(once_boot, video_store, ready, at, monkeypatch):
    boot, cfg = once_boot
    publisher.request_startup(video_store, "earlier-test", at(8), cfg, explicit_live=True)
    ready("earlier", at(8))
    original = publisher.reserve(video_store, at(8), cfg)
    shipped(video_store, original, at(8), "111")
    prior_request = video_store.rows("SELECT * FROM startup WHERE id='earlier-test'")[0]
    prior_claim = video_store.rows("SELECT * FROM startup_days")[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = list(pool.map(lambda _: boot(), range(2)))
    assert {r["id"] for r in requests} == {"boot-once:operator-next-start"}
    assert len(video_store.rows("SELECT * FROM startup WHERE state='pending'")) == 1
    assert publisher.reserve(video_store, at(10), cfg) is None  # no eligible new clip
    ready("extra", at(10))
    row = publisher.reserve(video_store, at(10), cfg)
    assert row["startup"] == requests[0]["id"] and row["slot"] is None
    shipped(video_store, row, at(10), "222")
    assert boot()["state"] == "posted"
    ready("third", at(10))
    assert publisher.reserve(video_store, at(10, 20), cfg) is None
    assert len(video_store.rows("SELECT * FROM startup_days")) == 2
    assert video_store.rows("SELECT * FROM startup WHERE id='earlier-test'")[0] == prior_request
    assert video_store.rows("SELECT * FROM startup_days WHERE request='earlier-test'")[0] == prior_claim
    assert {r["post_id"] for r in video_store.rows("SELECT * FROM history")} == {"111", "222"}

    monkeypatch.setattr(schedule, "utc_now", lambda: at(10, day=3))
    tomorrow = boot()
    assert tomorrow["id"] == "boot:2026-11-03" and tomorrow["allowance"] == ""
    assert boot()["id"] == tomorrow["id"]


def test_once_request_alone_also_uses_daily_allowance(once_boot, video_store, ready, at):
    boot, cfg = once_boot
    request = boot()
    ready(when=at(10))
    row = publisher.reserve(video_store, at(10), cfg)
    shipped(video_store, row, at(10))
    assert boot()["id"] == request["id"]
    assert len(video_store.rows("SELECT * FROM startup")) == 1
    assert len(video_store.rows("SELECT * FROM startup_days")) == 1


def test_unknown_once_send_keeps_claim_across_restart_and_next_day(once_boot, video_store, ready, at, monkeypatch):
    boot, cfg = once_boot
    request = boot()
    ready(when=at(10))
    row = publisher.reserve(video_store, at(10), cfg)
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (row["id"],))
    publisher.unknown(video_store, row["id"], row["token"], at(10).timestamp(), "receipt missing")
    assert boot()["id"] == request["id"]
    monkeypatch.setattr(schedule, "utc_now", lambda: at(10, day=3))
    assert boot()["id"] == request["id"]
    assert publisher.reserve(video_store, at(10, day=3), cfg) is None
    assert len(video_store.rows("SELECT * FROM startup_days")) == 1
    assert len(video_store.rows("SELECT * FROM content_claims")) == 1


def test_unattempted_failure_retries_same_grant_within_existing_bounds(once_boot, video_store, ready, at):
    boot, cfg = once_boot
    request = boot()
    ready(when=at(10))
    row = publisher.reserve(video_store, at(10), cfg)
    assert publisher.fail_before_submit(video_store, row["id"], row["token"], at(10).timestamp(), "upload failed")
    assert boot()["id"] == request["id"]
    retried = publisher.reserve(video_store, at(10, 2), cfg)
    assert retried["startup"] == request["id"] and retried["id"] != row["id"]
    assert len(video_store.rows("SELECT * FROM startup_days")) == 1


def test_expired_once_grant_is_not_regenerated_by_boot(once_boot, video_store, at, monkeypatch):
    boot, cfg = once_boot
    request = boot()
    monkeypatch.setattr(schedule, "utc_now", lambda: at(11))
    assert boot()["id"] == request["id"] and boot()["state"] == "skipped"
    assert len(video_store.rows("SELECT * FROM startup")) == 1
    assert not video_store.rows("SELECT * FROM startup_days")


def test_unconfigured_allowance_cannot_create_an_extra_request(video_store, video_cfg, at):
    with pytest.raises(ValueError, match="configured one-time authorization"):
        publisher.request_startup(video_store, "arbitrary", at(10), video_cfg, explicit_live=True, allowance="arbitrary")
    assert not video_store.rows("SELECT * FROM startup")


@pytest.mark.parametrize("value", [True, 1, None, "../reset", "a" * 97])
def test_startup_once_requires_stable_operator_id(video_cfg, value):
    with pytest.raises(ValueError, match="startup_once"):
        replace(video_cfg, startup_once=value)


def test_v2_migration_preserves_every_startup_claim_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE startup(id TEXT PRIMARY KEY, requested_day TEXT NOT NULL UNIQUE,
                requested REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending', reservation TEXT,
                reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE startup_days(day TEXT PRIMARY KEY, request TEXT UNIQUE, reservation TEXT UNIQUE);
            INSERT INTO startup VALUES('posted','2026-11-01',1,'posted','receipt','',1);
            INSERT INTO startup VALUES('unknown','2026-11-02',2,'reserved','held','ambiguous send',1);
            INSERT INTO startup_days VALUES('2026-11-01','posted','receipt');
            INSERT INTO startup_days VALUES('2026-11-02','unknown','held');
            PRAGMA user_version=2;
        """)
        before = {table: list(db.execute(f"SELECT * FROM {table}")) for table in ("startup", "startup_days")}
    migrated = store.Store(path)
    migrated = store.Store(path)
    for table, rows in before.items():
        after = migrated.rows(f"SELECT * FROM {table}")
        assert [tuple(value for key, value in row.items() if key != "allowance") for row in after] == rows
        assert all(row["allowance"] == "" for row in after)
    assert migrated.rows("PRAGMA user_version")[0]["user_version"] == 3
    with migrated.transaction() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO startup(id,requested_day,requested) VALUES('reset','2026-11-02',3)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO startup_days(day,request,reservation) VALUES('2026-11-02','reset','reset')")
