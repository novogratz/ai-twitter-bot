import json
from datetime import datetime, timedelta

import pytest

from src.core import config
from src.core.state_errors import StateUnreadable
from src.guards import action_guard, active_hours, reply_pacing, replied_store
from tests.helpers import TORONTO, fresh


@pytest.fixture
def clock(monkeypatch):
    now = [datetime(2026, 10, 14, 8, 0, tzinfo=TORONTO)]
    monkeypatch.setattr(active_hours, "now_local", lambda: now[0])
    monkeypatch.setattr(action_guard, "now_local", lambda: now[0])
    return now


def test_default_gap_is_75_to_95_seconds_and_never_redrawn(clock, memory_ledger):
    gaps = []
    for i in range(40):
        clock[0] += timedelta(seconds=600)
        action_guard.record(action_guard.REPLY, fresh("builder", n=i))
        gap = action_guard.seconds_until_allowed(action_guard.REPLY)
        assert 75 <= gap <= 95
        assert action_guard.seconds_until_allowed(action_guard.REPLY) == gap
        gaps.append(round(gap, 2))
    assert len(set(gaps)) > 20


def test_env_cannot_shorten_75_second_floor_or_raise_jitter(settings_override):
    settings_override(MIN_SECONDS_BETWEEN_REPLIES=4, REPLY_JITTER_SECONDS=999)
    assert config.MIN_SECONDS_BETWEEN_REPLIES == 75
    assert config.REPLY_JITTER_SECONDS == 180


def test_uncertain_reservation_survives_restart_and_cannot_be_fished(clock, memory_ledger):
    assert reply_pacing.reserve(fresh("one"))
    original = reply_pacing.PACE.read()
    gap = reply_pacing.remaining()
    assert 75 <= gap <= 95 and memory_ledger.rows == []
    for _ in range(5):
        assert not reply_pacing.reserve(fresh("two"))
        assert reply_pacing.PACE.read() == original
    # Forget all in-memory ledger objects, as after a restart.
    action_guard.LEDGER = None
    assert action_guard.seconds_until_allowed(action_guard.REPLY) == gap
    clock[0] = datetime.fromisoformat(original["next_at"]) - timedelta(microseconds=1)
    assert not reply_pacing.reserve(fresh("two"))
    clock[0] += timedelta(microseconds=1)
    assert reply_pacing.reserve(fresh("two"))


@pytest.mark.parametrize("value", ['{', '[]', '{"next_at":"bad"}',
                                     '{"submitted_at":"2026-10-14T08:00:00-04:00", "next_at":"2026-10-14T08:01:14-04:00", "target":"x"}',
                                     '{"submitted_at":"2026-10-14T08:00:00", "next_at":"2026-10-14T08:01:00", "target":"x"}'])
def test_corrupt_pacing_stops_admission_without_overwriting(clock, value):
    from pathlib import Path
    path = Path(reply_pacing.PACE.path)
    path.write_text(value)
    with pytest.raises(StateUnreadable):
        reply_pacing.reserve(fresh("one"))
    assert path.read_text() == value


def test_dry_run_and_window_close_do_not_reserve_a_submission(clock, monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("DRY_RUN", "1")
    assert not reply_pacing.reserve(fresh("one"))
    monkeypatch.setenv("DRY_RUN", "0")
    clock[0] = clock[0].replace(hour=9, minute=30)
    with pytest.raises(active_hours.OutsideActiveHours):
        reply_pacing.reserve(fresh("one"))
    assert not Path(reply_pacing.PACE.path).exists()


def test_uncertain_browser_submit_consumes_cooldown(unranked_account, clock, monkeypatch, memory_ledger):
    from src.x import safari, twitter_client as tc
    from src.x.confirmed_write import WriteOutcome
    for name in ("_activate_or_abort", "_open_or_abort", "_paste_or_abort", "_standalone_reply_target"):
        monkeypatch.setattr(tc, name, lambda *a, **k: True)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: None)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: False)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    first, second = fresh("one"), fresh("two", n=2)
    assert tc.reply_to_tweet(first, "Inference costs depend on memory bandwidth.") is WriteOutcome.UNCONFIRMED
    assert tc.reply_to_tweet(second, "Batching changes the latency budget.") is WriteOutcome.REFUSED
    assert first in replied_store.load_replied() and second not in replied_store.load_replied()
    assert memory_ledger.rows == [] and reply_pacing.remaining() >= 75


def test_old_saved_cooldown_is_not_shortened_by_faster_defaults(clock, settings_override):
    old = {"submitted_at": clock[0].isoformat(),
           "next_at": (clock[0] + timedelta(seconds=420)).isoformat(), "target": fresh("old")}
    reply_pacing.PACE.write(old)
    assert reply_pacing.remaining() == 420
    assert not reply_pacing.reserve(fresh("new"))
    assert reply_pacing.PACE.read() == old
    settings_override(MIN_SECONDS_BETWEEN_REPLIES=600)
    assert reply_pacing.remaining() == 600


def test_full_day_can_approach_300_with_ready_drafts_and_browser_time(clock, memory_ledger):
    """Capacity check, not a quota: assume an approved draft is always ready."""
    import math
    clock[0] = clock[0].replace(hour=5, minute=0)
    end = clock[0].replace(hour=23)
    sent = 0
    while clock[0] < end:
        if action_guard.can_post(action_guard.REPLY)[0]:
            clock[0] += timedelta(seconds=13)  # Open, verify, compose.
            if active_hours.may_act():
                assert reply_pacing.reserve(fresh("builder", n=sent))
                clock[0] += timedelta(seconds=2)  # Submission confirmation.
                action_guard.record(action_guard.REPLY, fresh("builder", n=sent))
                sent += 1
        # The selector runs every fifteen seconds and never catches up in bursts.
        next_tick = (math.floor(clock[0].timestamp() / 15) + 1) * 15
        clock[0] = datetime.fromtimestamp(next_tick, tz=TORONTO)
    assert 280 <= sent <= 320, sent


def _reserve_child(folder, start, results, index):
    from src.core import state_store
    from src.guards import action_guard, active_hours, reply_pacing
    from src.guards.ledger import MemoryLedger
    state_store.root = lambda: folder
    action_guard.LEDGER = MemoryLedger()
    active_hours.now_local = lambda: datetime(2026, 10, 14, 8, 0, tzinfo=TORONTO)
    action_guard.now_local = active_hours.now_local
    start.wait(10)
    results.put(reply_pacing.reserve(f"https://x.com/builder/status/{index}"))


def test_separate_processes_cannot_submit_different_parents_in_one_window(tmp_path):
    import multiprocessing
    ctx = multiprocessing.get_context("fork")
    start, results = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_reserve_child, args=(str(tmp_path), start, results, i)) for i in range(4)]
    try:
        for worker in workers:
            worker.start()
        start.set()
        assert sum(results.get(timeout=15) for _ in workers) == 1
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
