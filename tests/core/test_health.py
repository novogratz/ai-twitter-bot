"""src/core/health: the job wrapper and the failure it is handed (#235)."""
import os

import pytest

from src.core import health
from src.core.state_errors import StateUnreadable
from src.guards.active_hours import OutsideActiveHours


@pytest.fixture
def restarts(monkeypatch):
    calls = []
    monkeypatch.setattr(health, "_restart_safari", lambda: calls.append(1) or True)
    monkeypatch.setattr(health, "_append_autonomous_flag", lambda *a: None)
    return calls


def _failures():
    return health.HEALTH.read()["consecutive_failures"]


def _raises(error):
    def run():
        raise error
    return run


def test_a_success_resets_the_failure_counter(restarts):
    health.HEALTH.write({"consecutive_failures": 2, "last_recovery_ts": 0, "total_recoveries": 0})

    health.wrap_job(lambda: None, "direct_reply")()

    assert _failures() == 0


def test_a_failure_is_counted(restarts):
    health.wrap_job(_raises(RuntimeError("page never loaded")), "direct_reply")()

    assert _failures() == 1


def test_failures_in_a_row_restart_safari(restarts):
    job = health.wrap_job(_raises(RuntimeError("page never loaded")), "direct_reply")
    for _ in range(health.RECOVERY_THRESHOLD):
        job()

    assert restarts == [1]


@pytest.mark.parametrize("error", [StateUnreadable("replied_tweets.json is unreadable"),
                                   OutsideActiveHours("Bot asleep")],
                         ids=["state_unreadable", "bedtime"])
def test_an_unreadable_state_or_bedtime_is_not_a_safari_failure(restarts, error):
    job = health.wrap_job(_raises(error), "direct_reply")
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        job()

    assert restarts == []
    assert not os.path.exists(health.HEALTH.path), "the failure counter is left alone"


def test_an_unreadable_state_is_logged_as_a_halt(restarts, caplog):
    health.wrap_job(_raises(StateUnreadable("replied_tweets.json is unreadable")), "direct_reply")()

    assert "direct_reply halted: replied_tweets.json is unreadable" in caplog.text


def test_the_traceback_is_in_the_log(restarts, caplog):
    def run_direct_reply_cycle():
        raise RuntimeError("page never loaded")

    health.wrap_job(run_direct_reply_cycle, "direct_reply")()

    [record] = [r for r in caplog.records if r.levelname == "ERROR"]
    assert record.exc_info is not None
    assert "Traceback (most recent call last)" in caplog.text
    assert "in run_direct_reply_cycle" in caplog.text
    assert "RuntimeError: page never loaded" in caplog.text


@pytest.mark.parametrize("run", [lambda: None, _raises(RuntimeError("model timed out")),
                                 _raises(StateUnreadable("slots.json is unreadable")),
                                 _raises(OutsideActiveHours("Bot asleep"))],
                         ids=["success", "failure", "state_unreadable", "bedtime"])
def test_an_unwatched_job_never_touches_the_health_file(restarts, run):
    job = health.wrap_job(run, "editorial", safari_health=False)
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        job()

    assert restarts == []
    assert not os.path.exists(health.HEALTH.path)


def test_an_unwatched_failure_is_still_logged_with_its_traceback(restarts, caplog):
    health.wrap_job(_raises(RuntimeError("model timed out")), "editorial", safari_health=False)()

    assert "RuntimeError: model timed out" in caplog.text
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_the_wrapper_keeps_the_job_name():
    def run_direct_reply_cycle():
        return None

    assert health.wrap_job(run_direct_reply_cycle, "direct_reply").__name__ == "run_direct_reply_cycle"


@pytest.mark.parametrize("error", [StateUnreadable("replied_tweets.json is unreadable"),
                                   OutsideActiveHours("Bot asleep")],
                         ids=["state_unreadable", "bedtime"])
def test_record_failure_judges_the_exception_it_is_handed(restarts, error):
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        assert health.record_failure("direct_reply", error) is False

    assert restarts == []
    assert not os.path.exists(health.HEALTH.path)


def test_record_failure_counts_a_handed_exception_outside_an_except(restarts):
    health.record_failure("direct_reply", RuntimeError("page never loaded"))

    assert _failures() == 1
