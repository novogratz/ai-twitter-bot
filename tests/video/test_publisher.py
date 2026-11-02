from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from src.video import publisher as p
from src.video.store import Store


def shipped(store, row, now, post_id="123"):
    with store.transaction() as db:
        db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (row["id"],))
    p.confirm(store, row["id"], row["token"], now.timestamp(), post_id)


def test_explicit_deleted_post_replacement_retains_receipts_and_daily_slot(video_store, video_cfg, ready, at):
    ready()
    original = p.reserve(video_store, at(), video_cfg)
    shipped(video_store, original, at(), "123")
    with pytest.raises(ValueError, match="explicit"):
        p.replace_deleted(video_store, "123", "replacement-request", at(7, 1), video_cfg)
    row = p.replace_deleted(video_store, "123", "replacement-request", at(7, 1), video_cfg,
                            operator_reports_deleted=True)
    assert row["candidate"] == original["candidate"] and row["slot"] == original["slot"]
    assert row["id"] != original["id"]
    assert p.replace_deleted(video_store, "123", "repeat-command", at(7, 2), video_cfg,
                             operator_reports_deleted=True)["id"] == row["id"]
    assert video_store.rows("SELECT post_id FROM history") == [{"post_id": "123"}]
    shipped(video_store, row, at(7, 2), "456")
    assert len(video_store.rows("SELECT * FROM history")) == 2
    assert len(video_store.rows("SELECT * FROM slots WHERE state='posted'")) == 1
    assert len(video_store.rows("SELECT * FROM content_claims")) == 1


def test_pair_distinct_and_actual_success_gap(video_store, video_cfg, ready, at):
    ready("a")
    ready("b")
    for index in range(5):
        ready(f"buffer{index}")
    first = p.reserve(video_store, at(), video_cfg)
    shipped(video_store, first, at(7, 8))
    assert p.reserve(video_store, at(7, 15), video_cfg) is None
    # The independent preparation worker refreshes scores shortly before use.
    with video_store.transaction() as db:
        for candidate in db.execute("SELECT id,document FROM candidates WHERE state='ready'").fetchall():
            doc = json.loads(candidate["document"])
            doc["ranking"]["scored_at"] = at(7, 20).timestamp()
            db.execute("UPDATE candidates SET document=? WHERE id=?", (json.dumps(doc), candidate["id"]))
    second = p.reserve(video_store, at(7, 23), video_cfg)
    assert second["candidate"] != first["candidate"]
    assert second["slot"].endswith("07:15")


def test_delayed_first_pushes_second_beyond_grace(video_store, video_cfg, ready, at):
    ready("a")
    ready("b")
    first = p.reserve(video_store, at(7, 9), video_cfg)
    shipped(video_store, first, at(7, 10, 1))
    assert p.reserve(video_store, at(7, 15), video_cfg) is None
    assert video_store.rows("SELECT state FROM slots WHERE id LIKE '%07:15'")[0]["state"] == "skipped"


def test_pair_can_have_one_clip_and_missed_slots_never_burst(video_store, video_cfg, ready, at):
    ready()
    first = p.reserve(video_store, at(), video_cfg)
    shipped(video_store, first, at())
    assert p.reserve(video_store, at(7, 15), video_cfg) is None
    p.tick_calendar(video_store, at(8), video_cfg)
    assert video_store.rows("SELECT state FROM slots WHERE id LIKE '%07:15'")[0]["state"] == "skipped"
    ready("later", at(10))
    assert p.reserve(video_store, at(10), video_cfg) is None


def test_only_explicit_live_activation_creates_startup(video_store, video_cfg, at, settings_override):
    assert p.request_startup(video_store, "boot", at(), video_cfg) is None
    settings_override(DRY_RUN=True)
    assert p.request_startup(video_store, "dry", at(), video_cfg, explicit_live=True) is None
    assert not video_store.rows("SELECT * FROM startup")


def test_launch_idempotency_and_one_startup_per_calendar_day(video_store, video_cfg, ready, at):
    first = p.request_startup(video_store, "manual", at(5), video_cfg, explicit_live=True)
    second = p.request_startup(video_store, "another-command", at(5, 1), video_cfg, explicit_live=True)
    assert first["id"] == second["id"]
    ready(when=at(5))
    row = p.reserve(video_store, at(5), video_cfg)
    shipped(video_store, row, at(5))
    assert len(video_store.rows("SELECT * FROM startup_days")) == 1
    assert p.request_startup(video_store, "again", at(6), video_cfg, explicit_live=True)["state"] == "posted"
    assert p.request_startup(video_store, "tomorrow", at(5, day=3), video_cfg, explicit_live=True)["id"] == "tomorrow"


def test_startup_cooldown_deferral_and_expiry(video_store, video_cfg, at):
    p.request_startup(video_store, "night", at(1), video_cfg, explicit_live=True)
    p.tick_calendar(video_store, at(4, 29), video_cfg)
    assert video_store.rows("SELECT state FROM startup")[0]["state"] == "pending"
    assert p.reserve(video_store, at(4, 29), video_cfg) is None
    p.tick_calendar(video_store, at(5, 29, 59), video_cfg)
    assert video_store.rows("SELECT state FROM startup")[0]["state"] == "pending"
    p.tick_calendar(video_store, at(5, 30), video_cfg)
    assert video_store.rows("SELECT state FROM startup")[0]["state"] == "skipped"


def test_ready_startup_video_defers_until_0430(video_store, video_cfg, ready, at):
    p.request_startup(video_store, "night", at(1), video_cfg, explicit_live=True)
    ready(when=at(4, 29))
    assert p.reserve(video_store, at(4, 29, 59), video_cfg) is None
    assert not video_store.rows("SELECT * FROM reservations")
    row = p.reserve(video_store, at(4, 30), video_cfg)
    assert row["startup"] == "night" and row["slot"] is None


def test_startup_slot_collision_atomic_single_post(video_store, video_cfg, ready, at):
    ready(when=at(6, 50))
    p.request_startup(video_store, "morning", at(6, 50), video_cfg, explicit_live=True)
    assert p.reserve(video_store, at(6, 50), video_cfg) is None
    row = p.reserve(video_store, at(), video_cfg)
    assert row["startup"] == "morning" and row["slot"].endswith("07:00")
    shipped(video_store, row, at())
    assert video_store.rows("SELECT state FROM startup")[0]["state"] == "posted"
    assert video_store.rows("SELECT state FROM slots WHERE id=?", (row["slot"],))[0]["state"] == "posted"
    assert len(video_store.rows("SELECT * FROM reservations")) == 1


def test_concurrent_publishers_claim_one_slot_and_content(video_store, video_cfg, ready, at):
    for i in range(4):
        ready(str(i))
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: p.reserve(Store(video_store.path), at(), video_cfg), range(8)))
    assert sum(r is not None for r in results) == 1
    assert len(video_store.rows("SELECT * FROM content_claims")) == 1


@pytest.mark.parametrize("phase,expected", [("reserved", "failed"), ("uploading", "failed"), ("submitting", "publish_unknown")])
def test_crash_recovery_does_not_retry_uncertain_send(video_store, video_cfg, ready, at, phase, expected):
    ready()
    row = p.reserve(video_store, at(), video_cfg)
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET state=?,lease=? WHERE id=?", (phase, at().timestamp() - 1, row["id"]))
    p.recover(Store(video_store.path), at().timestamp())
    result = video_store.rows("SELECT * FROM reservations")[0]
    assert result["state"] == expected
    if expected == "publish_unknown":
        assert not p.fail_before_submit(video_store, row["id"], row["token"], at().timestamp(), "pretend safe")
        assert p.reserve(video_store, at(7, 1), video_cfg) is None
        assert video_store.rows("SELECT * FROM content_claims")


def test_dry_run_never_reserves_or_calls_api(video_store, video_cfg, ready, at, settings_override):
    ready()
    settings_override(DRY_RUN=True)
    class Forbidden:
        def upload(self, *args):
            pytest.fail("dry run uploaded media")
    assert p.publish_tick(video_store, video_cfg, now=at(), client=Forbidden()) == "dry-run"
    assert not video_store.rows("SELECT * FROM reservations")


@pytest.mark.parametrize("change", ["permission", "novelty", "cleanup", "score", "timestamp"])
def test_eligibility_cannot_be_offset_by_high_views(video_store, video_cfg, ready, at, change):
    doc = ready()
    if change == "permission": doc["permission_id"] = "not-authorized"
    elif change == "novelty": doc["novelty"]["state"] = "unchecked"
    elif change == "cleanup": doc["qc"]["overlays_clean"] = False
    elif change == "score": doc["ranking"]["total"] = 79
    else: doc["published_at"] = None
    with video_store.transaction() as db:
        db.execute("UPDATE candidates SET document=?", (json.dumps(doc),))
    assert p.reserve(video_store, at(), video_cfg) is None


def test_all_eight_slots_plus_one_startup_daily_max(video_store, video_cfg, ready, at):
    p.request_startup(video_store, "start", at(5), video_cfg, explicit_live=True)
    for index in range(16):
        ready(f"buffer{index}", at(5))
    times = [(5, 0), (7, 0), (7, 15), (9, 0), (9, 15), (12, 0), (17, 0), (21, 0), (21, 15)]
    for n, (h, m) in enumerate(times):
        with video_store.transaction() as db:
            for candidate in db.execute("SELECT id,document FROM candidates WHERE state='ready'").fetchall():
                doc = json.loads(candidate["document"])
                doc["ranking"]["scored_at"] = at(h, m).timestamp()
                db.execute("UPDATE candidates SET document=? WHERE id=?", (json.dumps(doc), candidate["id"]))
        row = p.reserve(video_store, at(h, m), video_cfg)
        assert row
        shipped(video_store, row, at(h, m), str(100 + n))
    assert len(video_store.rows("SELECT * FROM reservations WHERE state='confirmed'")) == 9
    ready("extra", at(23))
    assert p.reserve(video_store, at(23), video_cfg) is None
