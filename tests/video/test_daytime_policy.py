from dataclasses import replace
import json

import pytest

from src.video import connectors, preparation, publisher, ranking, schedule
from tests.video.test_publisher import shipped


def daytime(cfg):
    return replace(cfg, windows=tuple(f"{hour:02}:00" for hour in range(5, 24, 2)),
                   paired_windows=(), scheduled_daily_cap=10, max_age_hours=730 * 24)


def test_ten_two_hour_windows_with_daily_startup_coalesced_at_open(video_store, video_cfg, ready, at):
    cfg = daytime(video_cfg)
    assert schedule.clocks(cfg) == tuple(f"{hour:02}:00" for hour in range(5, 24, 2))
    publisher.request_startup(video_store, "boot", at(5), cfg, explicit_live=True)
    for i, hour in enumerate(range(5, 24, 2)):
        ready(f"clip{i}", at(hour))
        reservation = publisher.reserve(video_store, at(hour), cfg)
        assert reservation["slot"].endswith(f"{hour:02}:00")
        if hour == 5:
            assert reservation["startup"] == "boot"
        shipped(video_store, reservation, at(hour), str(1000 + i))
    assert len(video_store.rows("SELECT * FROM reservations WHERE state='confirmed'")) == 10
    assert len(video_store.rows("SELECT * FROM startup_days")) == 1
    ready("extra", at(23, 30))
    assert publisher.reserve(video_store, at(23, 30), cfg) is None


def test_two_year_fallback_is_strict_and_recent_available_clip_wins(video_store, video_cfg, ready, at):
    cfg = daytime(video_cfg)
    recent = ready("recent", score=85)
    archive = ready("archive", score=99)
    recent["published_at"] = at().timestamp() - 15 * 86400
    archive["published_at"] = at().timestamp() - 400 * 86400
    with video_store.transaction() as db:
        for ident, doc in (("recent", recent), ("archive", archive)):
            db.execute("UPDATE candidates SET document=?,published=? WHERE id=?", (json.dumps(doc), doc["published_at"], ident))
    assert ranking.gate(archive, cfg, at().timestamp(), final=True) == ""
    assert publisher.reserve(video_store, at(), cfg)["candidate"] == "recent"
    archive["published_at"] = at().timestamp() - 731 * 86400
    assert "stale" in ranking.gate(archive, cfg, at().timestamp(), final=True)
    with pytest.raises(ValueError, match="two years"):
        replace(cfg, max_age_hours=731 * 24)


@pytest.mark.parametrize("views,offset,allowed", [(0, 0, True), (50_000, 0, True),
    (50_001, 0, False), (None, 0, False), (True, 0, False), (-1, 0, False), (10, 3601, False), (10, -1, False)])
def test_x_views_checked_even_for_explicit_selection(ready, video_cfg, at, views, offset, allowed):
    doc = ready()
    cfg = replace(video_cfg, permissions={"grant": video_cfg.permissions["grant"] | {"platform": "x"}})
    now = at().timestamp()
    doc.update(platform="x", canonical_url="https://x.com/creator/status/123",
               source_metrics={"views": views, "observed_at": now - offset, "source_url": "https://x.com/creator/status/123"})
    doc["operator_selection"] = {"sha256": doc["original_sha256"], "selected_at": now, "expires_at": now + 3600}
    assert (ranking.gate(doc, cfg, now, final=True) == "") is allowed


def test_x_urls_and_provider_metrics_are_bound_to_the_source(video_store, video_cfg, at):
    now = at().timestamp()
    item = {"source_id": "123", "canonical_url": "https://twitter.com/creator/status/123?tracking=1",
            "creator": "creator", "metrics": {"views": 49999}, "metrics_observed_at": now,
            "metrics_evidence": "https://x.com/creator/status/123"}
    assert connectors.ingest(video_store, "x", [item], now, video_cfg) == 1
    doc = json.loads(video_store.rows("SELECT document FROM candidates")[0]["document"])
    assert doc["canonical_url"] == "https://x.com/creator/status/123"
    assert ranking.source_gate(doc, now) == ""
    doc["source_metrics"]["source_url"] = "https://x.com/creator/status/456"
    assert "unverified" in ranking.source_gate(doc, now)


def test_caption_uses_only_reviewed_cast_and_never_guesses_handle(ready, video_cfg, at):
    doc = ready()
    cfg = replace(video_cfg, target_handles={"performer": "@ExampleStar"}, caption_disclosure=False)
    caption = ranking.caption(doc, cfg, at().timestamp())
    assert caption.startswith("POV: @ExampleStar ")
    assert caption.endswith("\n\nANOTHER ABSOLUTE SI BANGER! 🔥")
    assert len(caption) <= 280
    doc["inspection"]["cast"] = ["unknown"]
    with pytest.raises(ValueError, match="cast"):
        ranking.caption(doc, cfg, at().timestamp())


def test_preparation_recovers_age_expired_lead_but_not_permanent_claim(video_store, video_cfg, ready, at):
    cfg = daytime(video_cfg)
    for ident in ("old", "claimed"):
        ready(ident)
        with video_store.transaction() as db:
            db.execute("UPDATE candidates SET state='expired',reason='freshness expired',published=? WHERE id=?",
                       (at().timestamp() - 200 * 86400, ident))
        video_store.enqueue("media", ident, at().timestamp())
    with video_store.transaction() as db:
        db.execute("INSERT INTO content_claims VALUES('claimed','unknown-publication')")
        db.execute("UPDATE jobs SET state='dead',attempts=4")
        preparation.recover_supply(db, cfg, at().timestamp())
    assert video_store.candidate("old")["state"] == "held"
    assert video_store.candidate("claimed")["state"] == "expired"
    assert video_store.rows("SELECT state FROM jobs WHERE item='old'")[0]["state"] == "pending"
    assert video_store.rows("SELECT state FROM jobs WHERE item='claimed'")[0]["state"] == "dead"
