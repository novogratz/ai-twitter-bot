from dataclasses import replace
from datetime import datetime
import json

import pytest

from src.video import inventory, publisher, schedule
from src.video.operations import status
from src.video.store import dumps


def refresh_fixture(store, now):
    """Keep fixture scores current without inventing live observations."""
    with store.transaction() as db:
        for row in db.execute("SELECT id,document FROM candidates WHERE state='ready'").fetchall():
            doc = json.loads(row["document"])
            doc["ranking"]["scored_at"] = now.timestamp()
            db.execute("UPDATE candidates SET document=? WHERE id=?", (dumps(doc), row["id"]))


def confirm(store, row, now):
    with store.transaction() as db:
        db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (row["id"],))
    publisher.confirm(store, row["id"], row["token"], now.timestamp(), row["candidate"])


def test_five_clips_supply_five_windows_before_any_pair_extra(video_store, video_cfg, ready, at):
    for index in range(5):
        ready(str(index))
    posts = []
    for hour, minute in ((7, 0), (7, 15), (9, 0), (9, 15), (12, 0), (17, 0), (21, 0), (21, 15)):
        now = at(hour, minute)
        refresh_fixture(video_store, now)
        row = publisher.reserve(video_store, now, video_cfg)
        if minute == 15:
            assert row is None
        else:
            assert row is not None
            posts.append(row["candidate"])
            confirm(video_store, row, now)
    assert len(set(posts)) == 5
    publisher.tick_calendar(video_store, at(22), video_cfg)
    skipped = video_store.rows("SELECT reason FROM slots WHERE state='skipped'")
    assert len(skipped) == 3
    assert "inventory held" in skipped[0]["reason"]


def test_pair_can_supply_missed_primary_even_without_surplus(video_store, video_cfg, ready, at):
    ready(when=at(7, 15))
    row = publisher.reserve(video_store, at(7, 15), video_cfg)
    assert row and row["slot"].endswith("07:15")
    assert video_store.rows("SELECT state FROM slots WHERE id LIKE '%07:00'")[0]["state"] == "skipped"


def test_replenishment_within_grace_releases_extra(video_store, video_cfg, ready, at):
    for index in range(6):
        ready(str(index))
    first = publisher.reserve(video_store, at(), video_cfg)
    confirm(video_store, first, at())
    assert publisher.reserve(video_store, at(7, 15), video_cfg) is None
    ready("replenishment", at(7, 17))
    row = publisher.reserve(video_store, at(7, 17), video_cfg)
    assert row and row["slot"].endswith("07:15")
    assert video_store.rows("SELECT reason FROM slots WHERE id=?", (row["slot"],))[0]["reason"] == ""


def test_last_evening_extra_protects_next_morning(video_store, video_cfg, ready, at):
    for index in range(6):
        ready(str(index), at(21))
    first = publisher.reserve(video_store, at(21), video_cfg)
    confirm(video_store, first, at(21))
    assert publisher.reserve(video_store, at(21, 15), video_cfg) is None
    report = status(video_store, video_cfg, at(21, 15))["window_coverage"]
    assert report["covered"] == 5 and report["shortfall"] == 0
    assert report["windows"][0]["id"] == "2026-11-03/07:00"
    assert report["windows"][-1]["id"] == "2026-11-03/21:00"


def test_expiring_clips_do_not_falsely_cover_tomorrow(video_store, video_cfg, ready, at):
    for index in range(6):
        doc = ready(str(index), at(21))
        doc["published_at"] = at(23).timestamp() - video_cfg.max_age_hours * 3600
        video_store.save_candidate(str(index), doc, at(21).timestamp(), state="ready", score=95)
    first = publisher.reserve(video_store, at(21), video_cfg)
    confirm(video_store, first, at(21))
    assert publisher.reserve(video_store, at(21, 15), video_cfg) is None
    report = inventory.report(video_store, video_cfg, at(21, 15))
    assert report["eligible_distinct"] == 5 and report["shortfall"] == 5


def test_surplus_selection_keeps_only_clip_licensed_for_late_window(video_store, video_cfg, ready, at):
    for index in range(7):
        ready(str(index), score=90 + index)
    first = publisher.reserve(video_store, at(), video_cfg)
    confirm(video_store, first, at())
    # One remaining clip can cover tomorrow morning; do not spend it as the extra.
    with video_store.transaction() as db:
        rows = db.execute("SELECT id,document FROM candidates WHERE state='ready' ORDER BY score DESC").fetchall()
        long_lived = rows[0]["id"]
        for row in rows[1:]:
            doc = json.loads(row["document"])
            doc["permission_id"] = "short"
            db.execute("UPDATE candidates SET document=? WHERE id=?", (dumps(doc), row["id"]))
    short = dict(video_cfg.permissions["grant"], expires_at=at(23).timestamp())
    cfg = replace(video_cfg, permissions=dict(video_cfg.permissions, short=short))
    extra = publisher.reserve(video_store, at(7, 15), cfg)
    assert extra and extra["candidate"] != long_lived


def test_duplicates_across_platforms_cannot_pad_coverage(video_store, video_cfg, ready, at):
    source = ready("original")
    copy = ready("copy")
    copy["original_sha256"] = source["original_sha256"]
    copy["inspection"]["sha256"] = source["original_sha256"]
    video_store.save_candidate("copy", copy, at().timestamp(), state="ready", score=95)
    with video_store.transaction() as db:
        db.execute("UPDATE candidates SET platform='bilibili' WHERE id='copy'")
    report = inventory.report(video_store, video_cfg, at())
    assert report["eligible_distinct"] == 1 and report["shortfall"] == 4


def test_protection_does_not_cancel_explicit_startup(video_store, video_cfg, ready, at):
    ready(when=at(5))
    publisher.request_startup(video_store, "explicit", at(5), video_cfg, explicit_live=True)
    row = publisher.reserve(video_store, at(5), video_cfg)
    assert row and row["startup"] == "explicit" and row["slot"] is None


def test_known_freshness_score_decay_cannot_inflate_coverage(video_store, video_cfg, ready, at):
    doc = ready(score=80.1)
    current_freshness = 10 * (1 - 1 / video_cfg.max_age_hours)
    doc["ranking"]["components"] = {"freshness": current_freshness}
    video_store.save_candidate("clip1", doc, at().timestamp(), state="ready", score=80.1)
    report = inventory.report(video_store, video_cfg, at(7, 15))
    assert report["eligible_distinct"] == 1
    assert report["shortfall"] == 5  # below 80 before the 09:00 window


def test_protection_switch_restores_pair_selection(video_store, video_cfg, ready, at):
    ready("a")
    ready("b")
    first = publisher.reserve(video_store, at(), video_cfg)
    confirm(video_store, first, at())
    assert publisher.reserve(video_store, at(7, 15), replace(video_cfg, protect_primary_windows=False))
    with pytest.raises(ValueError, match="protect_primary_windows"):
        replace(video_cfg, protect_primary_windows="false")


@pytest.mark.parametrize("now,expected", [("2026-10-31T21:15:00-04:00", "2026-11-01T07:00:00-05:00"),
    ("2026-03-07T21:15:00-05:00", "2026-03-08T07:00:00-04:00")])
def test_primary_coverage_crosses_dst(now, expected, video_cfg):
    upcoming = schedule.upcoming_primary(datetime.fromisoformat(now), video_cfg)
    assert len(upcoming) == 5
    assert upcoming[0][1].isoformat() == expected


def test_primary_mapping_tracks_configured_pair_spacing(video_cfg):
    cfg = replace(video_cfg, pair_minutes=20)
    assert schedule.primary_slot("2026-11-02/07:20", cfg) == "2026-11-02/07:00"
    assert schedule.primary_slot("2026-11-02/12:00", cfg) == "2026-11-02/12:00"
