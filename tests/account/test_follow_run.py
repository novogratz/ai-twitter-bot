"""The Follow run: one cycle's follows through the chokepoint (issue #260)."""
import json

import pytest

from src.account.follow_run import FollowRun
from src.core.state_store import StateUnreadable
from src.guards.active_hours import OutsideActiveHours
from src.x import twitter_client as tc
from src.x.twitter_client import FollowOutcome as F


@pytest.fixture
def chokepoint(monkeypatch):
    """`follow_account` answering from `answers` (an outcome, or an
    exception to raise) per handle, FOLLOWED by default; `asked` lists the
    handles it was called with."""
    state = {"asked": [], "answers": {}}

    def follow(handle):
        state["asked"].append(handle)
        answer = state["answers"].get(handle, F.FOLLOWED)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(tc, "follow_account", follow)
    return state


def _followed(tmp_path, *handles):
    (tmp_path / "followed_accounts.json").write_text(json.dumps(list(handles)))


def test_fresh_drops_the_followed_accounts_whatever_the_case(tmp_path, chokepoint):
    _followed(tmp_path, "Alreadyfan")

    run = FollowRun("TEST")

    assert run.fresh(["alreadyfan", "ALREADYFAN", "Newfan", "newfan"]) == ["Newfan"]


def test_fresh_drops_a_followed_account_recorded_with_its_at_sign(tmp_path, chokepoint):
    """Same key as follow_policy.relation and the ledger."""
    _followed(tmp_path, "@Alreadyfan")

    run = FollowRun("TEST")

    assert run.fresh(["alreadyfan", "@ALREADYFAN", "newfan"]) == ["newfan"]
    assert run.follow("alreadyfan") is None
    assert chokepoint["asked"] == []


def test_a_followed_account_is_never_asked(tmp_path, chokepoint):
    _followed(tmp_path, "Alreadyfan")

    assert FollowRun("TEST").follow("ALREADYFAN") is None
    assert chokepoint["asked"] == []


def test_a_handle_is_tried_once_per_run(chokepoint):
    run = FollowRun("TEST")
    chokepoint["answers"]["fan1"] = F.QUALITY_REJECTED

    assert run.follow("fan1") is F.QUALITY_REJECTED
    assert run.follow("Fan1") is None
    assert run.fresh(["FAN1", "fan2"]) == ["fan2"]
    assert chokepoint["asked"] == ["fan1"]


def test_cap_reached_stops_every_later_call(chokepoint):
    """Past CAP_REACHED the chokepoint is not asked again during the run:
    the budget does not come back within a cycle."""
    run = FollowRun("TEST")
    chokepoint["answers"]["fan1"] = F.CAP_REACHED

    assert [run.follow(h) for h in ("fan1", "fan2", "fan3")] == [F.CAP_REACHED] * 3
    assert chokepoint["asked"] == ["fan1"]
    assert run.fresh(["fan2"]) == ["fan2"], "a handle the cap spared was not tried"


def test_too_soon_leaves_the_chokepoint_open(chokepoint):
    """The spacing may elapse during a cycle: the run asks again."""
    run = FollowRun("TEST")
    chokepoint["answers"]["fan1"] = F.TOO_SOON

    assert run.follow("fan1") is F.TOO_SOON
    assert run.follow("fan2") is F.FOLLOWED
    assert chokepoint["asked"] == ["fan1", "fan2"]


@pytest.mark.parametrize("stop", [StateUnreadable("whitelist.json"), OutsideActiveHours("asleep")])
def test_bedtime_and_an_unreadable_state_file_end_the_run(chokepoint, stop):
    run = FollowRun("TEST")
    chokepoint["answers"]["fan1"] = stop

    with pytest.raises(type(stop)):
        run.follow("fan1")


def test_any_other_error_costs_one_pick(chokepoint):
    """Logged, the handle tried for this run, the next pick asked."""
    run = FollowRun("TEST")
    chokepoint["answers"]["fan1"] = RuntimeError("osascript died")

    assert run.follow("fan1") is None
    assert run.follow("fan2") is F.FOLLOWED
    assert run.follow("fan1") is None
    assert chokepoint["asked"] == ["fan1", "fan2"]
    assert run.failed == 1


def test_raise_failure_raises_the_last_pick_error(chokepoint):
    run = FollowRun("TEST")
    run.raise_failure()
    first, last = RuntimeError("first"), RuntimeError("last")
    chokepoint["answers"].update(fan1=first, fan2=last)
    run.follow("fan1")
    run.follow("fan2")

    with pytest.raises(RuntimeError) as raised:
        run.raise_failure()

    assert raised.value is last and run.failed == 2


def test_an_unreadable_followed_accounts_file_stops_the_run_before_any_follow(tmp_path, chokepoint):
    path = tmp_path / "followed_accounts.json"
    path.write_text("[not json")

    with pytest.raises(StateUnreadable):
        FollowRun("TEST")

    assert chokepoint["asked"] == []
    assert path.read_text() == "[not json"
