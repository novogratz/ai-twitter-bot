"""src/guards/action_guard: the daily budget, Debate turns, write spacing.

The policy asks an in-memory ledger (the `memory_ledger` fixture); the file
adapter has its own tests in test_ledger.py."""
from datetime import datetime, timedelta

from src.core import config
from src.guards import action_guard as ag
from src.guards.ledger import MemoryLedger
from tests.helpers import TORONTO, stop_requested, clock


# --- daily budget and caps ----------------------------------------------------


def test_toronto_day_budget_ignores_dry_runs_and_uses_all_profile_actions(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    rows = [{"action": ag.POST, "ts": "2026-09-20T03:59:00+00:00"},
            {"action": ag.POST, "ts": "2026-09-20T04:00:00+00:00", "dry_run": True}]
    rows += [{"action": action, "ts": "2026-09-20T06:00:00"}
             for action in [ag.POST] * 5 + [ag.QUOTE, ag.RETWEET]]
    ledger = MemoryLedger(rows)
    monkeypatch.setattr(ag, "LEDGER", ledger)
    assert ledger.count(ag.POST, now.date()) == 5
    assert ag.profile_count_today() == 7
    assert ag.can_post(ag.POST)[0]
    assert ledger.last_write(ag.POST) == now - timedelta(hours=6)
    ag.record(ag.POST)
    assert ag.profile_count_today() == 8
    assert not ag.can_post(ag.POST)[0]
    assert ag.can_post(ag.REPLY)[0]


def test_replies_uncapped_but_still_paced(monkeypatch, memory_ledger):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    for n in range(500):
        memory_ledger.append(ag.REPLY, f"https://x.com/a/status/{n}", False,
                             now - timedelta(hours=6, seconds=n))
    assert ag.can_post(ag.REPLY)[0]
    ag.record(ag.REPLY, "https://x.com/a/status/500")
    assert not ag.can_post(ag.REPLY)[0]


def test_quotes_and_reposts_are_refused(memory_ledger):
    assert not ag.can_post(ag.QUOTE)[0]
    assert not ag.can_post(ag.RETWEET)[0]


def test_can_post_refuses_after_stop(monkeypatch):
    from src.guards import action_guard

    assert action_guard.can_post(action_guard.REPLY)[0] is True
    stop_requested(monkeypatch)

    ok, why = action_guard.can_post(action_guard.REPLY)
    assert not ok and "stop" in why


def _noon(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    return now


def test_debate_turn_cap_counts_todays_shipped_turns_per_author(monkeypatch, settings_override,
                                                              memory_ledger):
    now = _noon(monkeypatch)
    settings_override(DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY=2)
    memory_ledger.append(ag.DEBATE_TURN, "challenger", False, now - timedelta(days=1))
    memory_ledger.append(ag.DEBATE_TURN, "challenger", True, now)
    memory_ledger.append(ag.DEBATE_TURN, "other", False, now)
    ag.record(ag.DEBATE_TURN, "@Challenger")
    assert ag.can_debate_turn("challenger") == (True, "")

    ag.record(ag.DEBATE_TURN, "challenger")

    assert ag.can_debate_turn("@Challenger") == (False, "debate turn cap reached for @@Challenger (2/day)")
    assert ag.can_debate_turn("other") == (True, "")
    assert ag.can_debate_turn(" @ ") == (False, "debate turn without an author handle")
    assert ag.debate_turn_authors() == ["challenger", "other"]


# --- Write spacing, drawn once per write (#131) ------------------------------
# The clock stands still after a write, so seconds_until_allowed is then the
# whole gap that write drew.


def _ledger_clock(monkeypatch):
    """A Toronto noon clock shared by the ledger and the Waking hours check,
    over an empty in-memory ledger."""
    from src.guards import active_hours

    now = [datetime(2026, 9, 21, 12, tzinfo=TORONTO)]
    monkeypatch.setattr(active_hours, "now_local", lambda: now[0])
    monkeypatch.setattr(ag, "now_local", lambda: now[0])
    monkeypatch.setattr(ag, "LEDGER", MemoryLedger())
    return now


def test_reply_gap_is_drawn_once_per_reply(monkeypatch):
    now = _ledger_clock(monkeypatch)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    gap = ag.seconds_until_allowed(ag.REPLY)
    low = config.MIN_SECONDS_BETWEEN_REPLIES
    assert low <= gap <= low + config.REPLY_JITTER_SECONDS
    assert {ag.seconds_until_allowed(ag.REPLY) for _ in range(50)} == {gap}, \
        "every caller sees one gap"

    ag.record(ag.REPLY, "https://x.com/a/status/2", dry_run=True)
    assert ag.seconds_until_allowed(ag.REPLY) == gap, "a dry-run row draws nothing"

    now[0] += timedelta(seconds=30)
    ag.record(ag.REPLY, "https://x.com/a/status/3")
    assert ag.seconds_until_allowed(ag.REPLY) != gap, "a new Reply draws a new gap"


def test_the_gap_is_seeded_on_the_stamp_of_the_last_write(monkeypatch):
    import random
    now = _ledger_clock(monkeypatch)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    draw = random.Random(f"reply:{now[0].isoformat()}").uniform(0, config.REPLY_JITTER_SECONDS)
    assert ag.seconds_until_allowed(ag.REPLY) == config.MIN_SECONDS_BETWEEN_REPLIES + draw


def test_reply_gap_keeps_its_jitter_across_replies(monkeypatch):
    now = _ledger_clock(monkeypatch)
    gaps = []
    for n in range(40):
        now[0] += timedelta(seconds=17)
        ag.record(ag.REPLY, f"https://x.com/a/status/{n}")
        gaps.append(ag.seconds_until_allowed(ag.REPLY))
    low, jitter = config.MIN_SECONDS_BETWEEN_REPLIES, config.REPLY_JITTER_SECONDS
    assert all(low <= g <= low + jitter for g in gaps)
    assert max(gaps) - min(gaps) > jitter / 2, "the jitter still spreads the gaps"


def test_wait_never_exceeds_one_gap_after_a_future_ledger_row(monkeypatch):
    """A Reply stamped an hour ahead (clock set back) would otherwise make
    the pipeline wait an hour; the chokepoint alone keeps refusing it."""
    now = _ledger_clock(monkeypatch)
    now[0] += timedelta(hours=1)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    gap = ag.seconds_until_allowed(ag.REPLY)
    now[0] -= timedelta(hours=1)
    assert ag.seconds_until_allowed(ag.REPLY) == gap
    assert ag.can_post(ag.REPLY)[0] is False


def test_can_post_reply_admits_exactly_when_the_wait_reaches_zero(monkeypatch):
    now = _ledger_clock(monkeypatch)
    assert ag.seconds_until_allowed(ag.REPLY) == 0, "an empty ledger waits for nothing"
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    wait = ag.seconds_until_allowed(ag.REPLY)
    assert wait >= config.MIN_SECONDS_BETWEEN_REPLIES

    now[0] += timedelta(seconds=wait - 0.01)
    assert 0 < ag.seconds_until_allowed(ag.REPLY) <= 0.011
    verdicts = {ag.can_post(ag.REPLY) for _ in range(50)}
    assert verdicts == {(False, f"too soon since last reply (need ~{int(wait)}s gap)")}, \
        "retrying cannot fish for a smaller draw"

    now[0] += timedelta(seconds=0.02)
    assert ag.seconds_until_allowed(ag.REPLY) == 0
    assert ag.can_post(ag.REPLY) == (True, "")


def test_original_gap_is_drawn_once_per_original(monkeypatch, settings_override):
    now = _ledger_clock(monkeypatch)
    settings_override(POST_JITTER_SECONDS=600)
    ag.record(ag.POST, "original")
    gap = ag.seconds_until_allowed(ag.POST)
    assert config.MIN_SECONDS_BETWEEN_POSTS <= gap <= config.MIN_SECONDS_BETWEEN_POSTS + 600

    now[0] += timedelta(seconds=gap - 1)
    assert {ag.can_post(ag.POST) for _ in range(50)} == \
        {(False, f"too soon since last post (need ~{int(gap)}s gap)")}
    now[0] += timedelta(seconds=2)
    assert ag.seconds_until_allowed(ag.POST) == 0
    assert ag.can_post(ag.POST) == (True, "")
