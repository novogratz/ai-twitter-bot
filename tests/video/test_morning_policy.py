"""The morning video exception never wakes ordinary social activity."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime

import pytest

from src.guards import active_hours, action_guard, reply_admission
from src.video import captions, inspection, publisher, ranking, schedule, workers
from tests.helpers import clock, fresh


def early(cfg, **changes):
    return replace(cfg, windows=("06:00", "09:00", "12:00", "17:00", "21:00"),
                   paired_windows=(), scheduled_daily_cap=5, early_video_window=True, **changes)


@pytest.mark.parametrize("h,m,s,allowed", [(5,54,59,False), (5,55,0,True), (6,0,0,True),
    (6,4,59,True), (6,5,0,False), (6,30,0,False), (7,0,0,True), (23,0,0,False)])
def test_bounded_video_eligibility_does_not_change_regular_hours(video_cfg, at, h, m, s, allowed):
    now, cfg = at(h,m,s), early(video_cfg)
    assert schedule.eligible(now, cfg) is allowed
    assert schedule.eligible(now) is (7 <= h < 23)


def test_video_io_scope_is_temporary_and_does_not_admit_replies_or_other_threads(monkeypatch, at):
    clock(monkeypatch, at(6))
    with active_hours.early_video_io(True):
        active_hours.require_active()
        assert active_hours.may_video_act() and not active_hours.may_act()
        assert active_hours.seconds_until_pause() == 300
        assert not reply_admission.judge_parent(fresh("someone"))
        assert not action_guard.can_post(action_guard.LIKE)[0]
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(active_hours.OutsideActiveHours):
                pool.submit(active_hours.require_active).result()
        clock(monkeypatch, at(6,5))
        assert not active_hours.may_video_act() and active_hours.seconds_until_pause() == 0
        with pytest.raises(active_hours.OutsideActiveHours):
            active_hours.require_active()
    clock(monkeypatch, at(6))
    with pytest.raises(active_hours.OutsideActiveHours):
        active_hours.require_active()


def test_video_scope_cannot_override_shutdown(monkeypatch, at):
    clock(monkeypatch, at(6))
    monkeypatch.setattr(active_hours, "stop_requested", lambda: True)
    with active_hours.early_video_io(True):
        assert not active_hours.may_video_act()
        with pytest.raises(active_hours.OutsideActiveHours):
            active_hours.require_active()


def test_only_video_scheduler_job_runs_at_six(monkeypatch, at, settings_override):
    import main
    from src.news import pipeline
    settings_override(VIDEO_ENABLED=True, NEWS_ENABLED=True)
    calls = []
    monkeypatch.setattr(workers, "health_job", lambda: calls.append(("video", active_hours.may_video_act())))
    monkeypatch.setattr(pipeline, "run", lambda: calls.append(("news", active_hours.may_act())))
    clock(monkeypatch, at(6))
    scheduler = main.build_scheduler()
    scheduler.get_job("video_health_job").func()
    scheduler.get_job("news_job").func()
    scheduler.get_job("direct_reply_job").func()
    assert calls == [("video", True)]
    clock(monkeypatch, at(6,5))
    scheduler.get_job("video_health_job").func()
    assert calls == [("video", True)]
    clock(monkeypatch, at(7))
    scheduler.get_job("news_job").func()
    assert calls[-1] == ("news", True)


def test_early_reservation_deadline_no_second_slot_or_late_catchup(video_store, video_cfg, ready, at, monkeypatch):
    cfg = early(video_cfg)
    now = at(5,55)
    clock(monkeypatch, now)
    ready(when=now)
    assert publisher.reserve(video_store, at(5,54,59), cfg) is None
    row = publisher.reserve(video_store, now, cfg)
    assert row["slot"].endswith("/06:00")
    assert row["deadline"] == at(6,5).timestamp()
    assert publisher.reserve(video_store, at(6), cfg) is None
    clock(monkeypatch, at(6,5))
    with pytest.raises(ValueError):
        publisher.guard(video_store, row["id"], row["token"], at(6,5).timestamp(), cfg)


def test_missed_early_slot_cannot_publish_at_seven(video_store, video_cfg, ready, at, monkeypatch):
    cfg = early(video_cfg)
    clock(monkeypatch, at(7))
    ready()
    assert publisher.reserve(video_store, at(7), cfg) is None
    row = video_store.rows("SELECT state,reason FROM slots WHERE id LIKE '%/06:00'")[0]
    assert row["state"] == "skipped" and "no catch-up" in row["reason"]


@pytest.mark.parametrize("day", ["2026-03-08", "2026-11-01"])
def test_morning_window_uses_toronto_wall_clock_on_dst_days(video_cfg, day):
    cfg = early(video_cfg)
    due = datetime.fromisoformat(day + "T06:00:00").replace(tzinfo=schedule.ZONE)
    start, end = schedule.slot_bounds(due.timestamp(), cfg)
    assert end - start == 600
    assert datetime.fromtimestamp(start, schedule.ZONE).strftime("%H:%M") == "05:55"
    assert datetime.fromtimestamp(end, schedule.ZONE).strftime("%H:%M") == "06:05"


def test_opt_in_cannot_open_other_night_slots(video_cfg):
    with pytest.raises(ValueError):
        replace(video_cfg, early_video_window=True)
    with pytest.raises(ValueError):
        replace(video_cfg, early_video_window=True, windows=("06:00",), paired_windows=("06:00",))
    with pytest.raises(ValueError):
        replace(early(video_cfg), windows=("05:00", "06:00", "09:00"))


def test_instagram_allowlist_applies_before_preparation_and_at_selection(video_store, video_cfg, ready, at):
    cfg = replace(video_cfg, publish_platforms=("instagram",))
    doc = ready()
    assert ranking.publication_gate(doc, cfg, at().timestamp()) == ""
    doc["platform"] = "x"
    assert "platform" in ranking.publication_gate(doc, cfg, at().timestamp())


def test_new_caption_needs_both_style_reviews_and_rejects_old_signoff(video_cfg, ready, at):
    cfg = replace(video_cfg, playful_caption=True, meme_caption=True, caption_disclosure=False)
    doc = ready()
    doc["inspection"]["caption"] = "Example Star took the dance break personally."
    doc["qc"]["caption_accurate"] = True
    with pytest.raises(ValueError, match="style review"):
        ranking.caption(doc, cfg, at().timestamp())
    for stage in ("inspection", "qc"):
        doc[stage].update(caption_policy=captions.POLICY, caption_style_ok=True)
    assert ranking.caption(doc, cfg, at().timestamp()) == doc["inspection"]["caption"]
    for stage in ("source", "output"):
        assert "caption_style_ok" in inspection.schema(cfg, stage)["required"]
    doc["inspection"]["caption"] += " Absolute BANGER 🔥"
    with pytest.raises(ValueError, match="meme style"):
        ranking.caption(doc, cfg, at().timestamp())
