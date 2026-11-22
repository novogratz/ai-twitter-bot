"""Submission ceilings survive unknown sends, separate workers and restarts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.state_errors import StateUnreadable
from src.core.state_store import GUARDED, StateFile
from src.guards import action_guard as guard, reply_budget
from tests.helpers import TORONTO, clock, numbered_url
from src.x import x_urls

NOW = datetime(2026, 11, 18, 12, tzinfo=TORONTO)


@pytest.mark.parametrize("configured,effective", [(20, 20), (100, 100), (250, 250), (1400, 250)])
def test_invited_mode_honors_lower_limits_and_never_exceeds_two_hundred_fifty(monkeypatch, memory_ledger, settings_override,
                                                                     configured, effective):
    clock(monkeypatch, NOW)
    settings_override(REPLY_INVITED_ONLY=True, MAX_REPLIES_PER_DAY=configured,
                      REPLY_DAILY_TARGET_MIN=250, REPLY_DAILY_TARGET_MAX=250)
    for n in range(effective):
        memory_ledger.append(guard.REPLY, numbered_url(n, f"author{n}"), False, NOW - timedelta(hours=2))
    assert f"{effective}/{effective}" in reply_budget.refusal()
    assert reply_budget.begin(numbered_url(999, "newauthor"))


def test_invited_author_budget_and_four_minute_gap_include_uncertain_sends(monkeypatch, memory_ledger, settings_override):
    clock(monkeypatch, NOW)
    settings_override(REPLY_INVITED_ONLY=True, MAX_REPLIES_PER_DAY=250,
                      MIN_SECONDS_BETWEEN_REPLIES=8, REPLY_JITTER_SECONDS=0)
    assert reply_budget.begin(numbered_url(501, "builder")) == ""
    assert guard.seconds_until_allowed(guard.REPLY) == 240
    clock(monkeypatch, NOW + timedelta(minutes=5))
    assert "author" in reply_budget.begin(numbered_url(502, "builder"))
    assert reply_budget.begin(numbered_url(503, "someoneelse")) == ""
    assert reply_budget.used_today() == 2
    clock(monkeypatch, NOW + timedelta(days=1))
    assert reply_budget.begin(numbered_url(504, "builder")) == ""
    assert reply_budget.begin(numbered_url(501, "builder")) == "Reply already submitted"


def fresh_url(author="someone", seconds=0, now=NOW):
    millis = int((now - timedelta(seconds=seconds)).timestamp() * 1000)
    return f"https://x.com/{author}/status/{(millis - x_urls._TWITTER_EPOCH_MS) << 22}"


@pytest.mark.parametrize("cap", [40, 100, 1400])
def test_last_daily_slot_is_atomic_and_confirmation_is_not_double_counted(monkeypatch, memory_ledger, settings_override, cap):
    clock(monkeypatch, NOW)
    settings_override(MAX_REPLIES_PER_DAY=cap, REPLY_JITTER_SECONDS=0)
    for n in range(cap - 1):
        memory_ledger.append(guard.REPLY, numbered_url(n), False, NOW - timedelta(hours=2))
    urls = [numbered_url(cap + 1000), numbered_url(cap + 1001)]
    with ThreadPoolExecutor(2) as pool:
        refusals = list(pool.map(reply_budget.begin, urls))
    assert refusals.count("") == 1
    assert reply_budget.used_today() == cap
    winner = urls[refusals.index("")]
    guard.record(guard.REPLY, winner)
    reply_budget.confirmed(winner)
    assert reply_budget.used_today() == cap
    assert not guard.can_post(guard.REPLY)[0]


@pytest.mark.parametrize("gap", [8, 600, 1440])
def test_uncertain_send_survives_restart_and_keeps_spacing(monkeypatch, memory_ledger, settings_override, gap):
    clock(monkeypatch, NOW)
    settings_override(MAX_REPLIES_PER_DAY=1400, MIN_SECONDS_BETWEEN_REPLIES=gap, REPLY_JITTER_SECONDS=0)
    assert reply_budget.begin(numbered_url(20)) == ""
    monkeypatch.setattr(reply_budget, "STATE", StateFile("reply_submissions.json", {}, GUARDED))
    assert guard.count_today(guard.REPLY) == 0
    assert reply_budget.used_today() == 1
    clock(monkeypatch, NOW + timedelta(seconds=gap - 1))
    assert not guard.can_post(guard.REPLY)[0]
    clock(monkeypatch, NOW + timedelta(seconds=gap))
    assert guard.can_post(guard.REPLY)[0]
    assert reply_budget.begin(numbered_url(20)) == "Reply already submitted"


def test_1400_goal_cannot_override_spacing_or_waking_hours(monkeypatch, memory_ledger, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=1400, REPLY_DAILY_TARGET_MIN=1400, REPLY_DAILY_TARGET_MAX=1400,
                      MIN_SECONDS_BETWEEN_REPLIES=8, REPLY_JITTER_SECONDS=4)
    start = NOW.replace(hour=4, minute=30)
    clock(monkeypatch, start - timedelta(seconds=1))
    assert not guard.can_post(guard.REPLY)[0]
    clock(monkeypatch, start)
    assert reply_budget.begin(numbered_url(10000)) == ""
    gap = guard.seconds_until_allowed(guard.REPLY)
    assert 8 <= gap <= 12
    clock(monkeypatch, start + timedelta(seconds=gap - 0.01))
    assert not guard.can_post(guard.REPLY)[0]
    clock(monkeypatch, start + timedelta(seconds=gap + 0.01))
    assert guard.can_post(guard.REPLY)[0]
    clock(monkeypatch, start.replace(hour=23, minute=59, second=58))
    assert reply_budget.begin(numbered_url(10001)) == ""
    assert reply_budget.used_today() == 2
    clock(monkeypatch, (start + timedelta(days=1)).replace(hour=0, minute=0))
    assert not guard.can_post(guard.REPLY)[0]


def test_toronto_day_changes_budget_but_never_releases_parent(monkeypatch, memory_ledger):
    clock(monkeypatch, NOW)
    assert reply_budget.begin(numbered_url(30)) == ""
    clock(monkeypatch, NOW + timedelta(days=1))
    assert reply_budget.used_today() == 0
    assert reply_budget.begin(numbered_url(30)) == "Reply already submitted"


def test_overnight_midnight_preserves_spacing_claims_and_morning_budget(monkeypatch, memory_ledger, settings_override):
    settings_override(REPLY_ALL_DAY=True, MAX_REPLIES_PER_DAY=1,
                      MIN_SECONDS_BETWEEN_REPLIES=8, REPLY_JITTER_SECONDS=0)
    late = NOW.replace(hour=23, minute=59, second=58)
    clock(monkeypatch, late)
    assert reply_budget.begin(numbered_url(300)) == ""
    clock(monkeypatch, late + timedelta(seconds=3))
    assert reply_budget.used_today() == 0
    assert not guard.can_post(guard.REPLY)[0]
    assert reply_budget.begin(numbered_url(300)) == "Reply already submitted"
    clock(monkeypatch, late + timedelta(seconds=9))
    assert guard.can_post(guard.REPLY)[0]
    assert reply_budget.begin(numbered_url(301)) == ""
    clock(monkeypatch, datetime(2026, 11, 19, 7, tzinfo=TORONTO))
    assert reply_budget.used_today() == 1
    assert not guard.can_post(guard.REPLY)[0]


def test_future_stamp_and_corrupt_state_fail_closed(monkeypatch, memory_ledger):
    clock(monkeypatch, NOW)
    assert reply_budget.begin(numbered_url(31)) == ""
    clock(monkeypatch, NOW - timedelta(days=1))
    assert reply_budget.used_today() == 1
    assert not guard.can_post(guard.REPLY)[0]
    Path(reply_budget.STATE.path).write_text('{"bad": {}}')
    with pytest.raises(StateUnreadable):
        guard.can_post(guard.REPLY)
    assert Path(reply_budget.STATE.path).read_text() == '{"bad": {}}'


def _temporary_workload(settings_override):
    settings_override(REPLY_BROAD_DISCOVERY=True, REPLY_CURATED_MODE=True, REPLY_INVITED_ONLY=True,
                      MAX_REPLIES_PER_DAY=80, REPLY_REVIEW_DAILY_LIMIT=80,
                      REPLY_DAILY_TARGET_MIN=60, REPLY_DAILY_TARGET_MAX=80,
                      REPLY_WORKLOAD_BOOST_START_DATE="2026-11-20", REPLY_WORKLOAD_BOOST_DAYS=4,
                      REPLY_WORKLOAD_BOOST_TARGET=200, REPLY_JITTER_SECONDS=0)


@pytest.mark.parametrize("stamp,boosted", [
    ("2026-11-19T23:59:59-05:00", False),
    ("2026-11-20T00:00:00-05:00", True),
    ("2026-11-23T23:59:59-05:00", True),
    ("2026-11-24T00:00:00-05:00", False),
])
def test_four_day_workload_uses_fixed_toronto_dates_and_expires_without_reload(
        monkeypatch, settings_override, stamp, boosted):
    _temporary_workload(settings_override)
    clock(monkeypatch, datetime.fromisoformat(stamp).astimezone(TORONTO))
    plan = reply_budget.daily_plan()
    assert plan["boost_active"] is boosted
    assert plan["boost_until"] == "2026-11-24"
    assert plan["target"] == (200 if boosted else 70)
    assert (plan["minimum"], plan["maximum"]) == ((200, 200) if boosted else (60, 80))
    assert plan["cap"] == plan["draft_limit"] == reply_budget.ceiling() == (200 if boosted else 80)
    assert plan["session_limit"] == (50 if boosted else 20)


def test_restart_cannot_extend_the_workload_window_or_clear_pending_capacity(
        monkeypatch, memory_ledger, settings_override):
    _temporary_workload(settings_override)
    now = datetime(2026, 11, 23, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    for n in range(199):
        memory_ledger.append(guard.REPLY, numbered_url(n, f"author{n}"), False, now - timedelta(hours=2))
    winner = numbered_url(6000, "newauthor")
    assert reply_budget.begin(winner, "Check the evaluation split.") == ""
    monkeypatch.setattr(reply_budget, "STATE", StateFile("reply_submissions.json", {}, GUARDED))
    assert reply_budget.used_today() == 200
    assert "200/200" in reply_budget.refusal()
    assert reply_budget.daily_plan()["boost_until"] == "2026-11-24"
    clock(monkeypatch, datetime(2026, 11, 24, 0, tzinfo=TORONTO))
    assert reply_budget.ceiling() == 80
    assert reply_budget.daily_plan()["target"] == 70
    assert x_urls.status_id(winner) in reply_budget.entries()


def test_boost_never_overrides_zero_disable_or_outlives_four_days(monkeypatch, settings_override):
    _temporary_workload(settings_override)
    settings_override(MAX_REPLIES_PER_DAY=0, REPLY_REVIEW_DAILY_LIMIT=0,
                      REPLY_WORKLOAD_BOOST_DAYS=100, REPLY_WORKLOAD_BOOST_TARGET=1000)
    clock(monkeypatch, datetime(2026, 11, 20, 12, tzinfo=TORONTO))
    plan = reply_budget.daily_plan()
    assert plan["cap"] == 200 and plan["automatic_cap"] == plan["draft_limit"] == 0
    assert plan["boost_until"] == "2026-11-24"


def _automatic_broad(settings_override):
    settings_override(REPLY_BROAD_DISCOVERY=True, REPLY_CURATED_MODE=True, REPLY_INVITED_ONLY=True,
                      REPLY_MANUAL_ORDINARY=False, REPLY_REVIEW_ONLY=False,
                      MAX_REPLIES_PER_DAY=1500, REPLY_DAILY_TARGET_MIN=1500, REPLY_DAILY_TARGET_MAX=1500,
                      REPLY_WORKLOAD_BOOST_START_DATE="", MIN_SECONDS_BETWEEN_REPLIES=8,
                      REPLY_JITTER_SECONDS=4)


def test_fifteen_hundredth_slot_is_atomic_includes_unknown_sends_and_survives_restart(
        monkeypatch, memory_ledger, settings_override):
    _automatic_broad(settings_override)
    clock(monkeypatch, NOW)
    for n in range(1498):
        memory_ledger.append(guard.REPLY, numbered_url(n, f"author{n}"), False, NOW - timedelta(hours=2))
    earlier = numbered_url(9000, "uncertainauthor")
    reply_budget.STATE.write({x_urls.status_id(earlier): {
        "target": earlier, "status": "pending", "submitted_at": (NOW - timedelta(hours=1)).isoformat()}})
    assert reply_budget.used_today() == 1499
    urls = [numbered_url(9001, "newone"), numbered_url(9002, "newtwo")]
    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(lambda target: reply_budget.begin(target, "Check the evaluation split."), urls))
    assert results.count("") == 1
    assert reply_budget.used_today() == 1500
    winner = urls[results.index("")]
    monkeypatch.setattr(reply_budget, "STATE", StateFile("reply_submissions.json", {}, GUARDED))
    assert "1500/1500" in reply_budget.refusal()
    guard.record(guard.REPLY, winner)
    reply_budget.confirmed(winner)
    assert reply_budget.used_today() == 1500
    assert reply_budget.entries()[x_urls.status_id(earlier)]["status"] == "pending"


def test_broad_eight_second_gap_and_jitter_include_pending_sends(monkeypatch, memory_ledger, settings_override):
    _automatic_broad(settings_override)
    clock(monkeypatch, NOW)
    target = numbered_url(9100, "builder")
    assert reply_budget.begin(target, "Check the evaluation split.") == ""
    gap = guard.seconds_until_allowed(guard.REPLY)
    assert 8 <= gap <= 12
    assert guard.seconds_until_allowed(guard.REPLY) == gap
    monkeypatch.setattr(reply_budget, "STATE", StateFile("reply_submissions.json", {}, GUARDED))
    assert guard.seconds_until_allowed(guard.REPLY) == gap
    clock(monkeypatch, NOW + timedelta(seconds=gap - .01))
    assert not guard.can_post(guard.REPLY)[0]
    clock(monkeypatch, NOW + timedelta(seconds=gap + .01))
    assert guard.can_post(guard.REPLY)[0]
    assert reply_budget.begin(target, "Check the evaluation split.") == "Reply already submitted"


@pytest.mark.parametrize("broad,curated,invited,expected", [
    (True, True, True, 1500), (False, True, True, 100),
    (False, False, True, 250), (False, False, False, 1500),
])
def test_new_ceiling_does_not_lift_other_restricted_modes(settings_override, broad, curated, invited, expected):
    settings_override(MAX_REPLIES_PER_DAY=1500, REPLY_BROAD_DISCOVERY=broad,
                      REPLY_CURATED_MODE=curated, REPLY_INVITED_ONLY=invited)
    assert reply_budget.ceiling() == expected


def test_stale_lower_workload_boost_cannot_replace_persistent_fifteen_hundred(
        monkeypatch, settings_override):
    _automatic_broad(settings_override)
    settings_override(REPLY_WORKLOAD_BOOST_START_DATE="2026-11-20",
                      REPLY_WORKLOAD_BOOST_DAYS=4, REPLY_WORKLOAD_BOOST_TARGET=200)
    clock(monkeypatch, datetime(2026, 11, 20, 12, tzinfo=TORONTO))
    plan = reply_budget.daily_plan()
    assert not plan["boost_active"]
    assert plan["target"] == plan["minimum"] == plan["maximum"] == reply_budget.ceiling() == 1500
