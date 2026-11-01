from dataclasses import replace
from datetime import date, datetime

import pytest

from src.video import schedule


def test_exact_eight_slots_and_noon(video_cfg):
    assert schedule.clocks(video_cfg) == ("07:00", "07:15", "09:00", "09:15", "12:00", "17:00", "21:00", "21:15")
    assert len(schedule.slots(date(2026, 11, 1), video_cfg)) == 8


def test_current_seven_slot_schedule_has_only_two_pairs(video_cfg):
    cfg = replace(video_cfg, paired_windows=("07:00", "21:00"))
    assert schedule.clocks(cfg) == ("07:00", "07:15", "09:00", "12:00", "17:00", "21:00", "21:15")


@pytest.mark.parametrize("day,offset", [(date(2026, 3, 7), -5), (date(2026, 3, 8), -4),
                                      (date(2026, 10, 31), -4), (date(2026, 11, 1), -5)])
def test_dst_offsets(day, offset, video_cfg):
    for _, at in schedule.slots(day, video_cfg):
        assert at.utcoffset().total_seconds() == offset * 3600
        assert schedule.eligible(at)


@pytest.mark.parametrize("when,allowed", [("2026-11-01T00:00:00-04:00", False),
    ("2026-11-01T01:30:00-04:00", False), ("2026-11-01T01:30:00-05:00", False),
    ("2026-11-01T03:59:59-05:00", False), ("2026-11-01T04:00:00-05:00", True),
    ("2026-11-01T23:59:59-05:00", True)])
def test_cooldown_including_fold(when, allowed):
    assert schedule.eligible(datetime.fromisoformat(when)) is allowed


@pytest.mark.parametrize("before,after", [("2026-10-31T23:30:00-04:00", "2026-11-01T04:30:00-05:00"),
                                       ("2026-03-07T23:30:00-05:00", "2026-03-08T04:30:00-04:00")])
def test_startup_eligible_hour_excludes_dst_night(before, after):
    assert schedule.eligible_seconds(datetime.fromisoformat(before), datetime.fromisoformat(after)) == 3600


def test_configurable_pair_and_no_overnight_slots(video_cfg):
    assert "07:20" in schedule.clocks(replace(video_cfg, pair_minutes=20))
    with pytest.raises(ValueError):
        replace(video_cfg, pair_minutes=14)
    with pytest.raises(ValueError):
        replace(video_cfg, windows=("00:00", "09:00", "12:00", "17:00", "21:00"))


def test_naive_timestamp_refused():
    with pytest.raises(ValueError):
        schedule.eligible(datetime(2026, 11, 1, 7))
