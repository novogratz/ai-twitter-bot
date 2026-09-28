"""src/core/health: the job wrapper and the failure it is handed (#235);
only a browser failure counts toward a Safari restart (#298), and only a
restart that was tried counts as a recovery (#302)."""
import json
import os
import threading
import time

import pytest

from src.core import health, state_store
from src.core.state_errors import StateUnreadable
from src.guards.active_hours import OutsideActiveHours
from src.x import safari_hygiene as sh
from src.x.page_session import BrowserFailure, PageNotOpened
from src.x.safari_hygiene import RestartOutcome

BROWSER_FAILURES = [PageNotOpened("https://x.com/home"), BrowserFailure("Safari wedged")]
NOT_BROWSER_FAILURES = [RuntimeError("bug in the job"), TimeoutError("model timed out")]


@pytest.fixture
def restarts(monkeypatch):
    calls = []
    monkeypatch.setattr(health, "_restart_safari",
                        lambda: calls.append(1) or RestartOutcome.RESTARTED)
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


@pytest.mark.parametrize("error", BROWSER_FAILURES, ids=["page_not_opened", "browser_failure"])
def test_a_browser_failure_is_counted(restarts, error):
    health.wrap_job(_raises(error), "direct_reply")()

    assert _failures() == 1


@pytest.mark.parametrize("error", BROWSER_FAILURES, ids=["page_not_opened", "browser_failure"])
def test_browser_failures_in_a_row_restart_safari(restarts, error):
    job = health.wrap_job(_raises(error), "direct_reply")
    for _ in range(health.RECOVERY_THRESHOLD):
        job()

    assert restarts == [1]


@pytest.mark.parametrize("error", NOT_BROWSER_FAILURES, ids=["bug", "model_timeout"])
def test_an_error_outside_the_browser_never_restarts_safari(restarts, caplog, error):
    """#298: a bug or a model timeout says nothing about Safari. It is
    logged at ERROR and leaves the failure counter alone."""
    job = health.wrap_job(_raises(error), "direct_reply")
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        job()

    assert restarts == []
    assert _failures() == 0
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == health.RECOVERY_THRESHOLD + 1
    assert all(r.getMessage() == "[direct_reply] Cycle failed." and r.exc_info for r in errors)


def test_an_error_outside_the_browser_does_not_reset_the_counter_either(restarts):
    """Only a success resets the counter: a failed cycle is none."""
    health.HEALTH.write({"consecutive_failures": 2, "last_recovery_ts": 0, "total_recoveries": 0})

    health.wrap_job(_raises(RuntimeError("bug in the job")), "direct_reply")()

    assert _failures() == 2
    assert restarts == []


@pytest.mark.parametrize("error", [StateUnreadable("replied_tweets.json is unreadable"),
                                   OutsideActiveHours("Bot asleep")],
                         ids=["state_unreadable", "overnight"])
def test_an_unreadable_state_or_the_overnight_is_not_a_safari_failure(restarts, error):
    job = health.wrap_job(_raises(error), "direct_reply")
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        job()

    assert restarts == []
    assert not os.path.exists(health.HEALTH.path), "the failure counter is left alone"


def test_an_unreadable_state_is_logged_as_a_halt(restarts, caplog):
    health.wrap_job(_raises(StateUnreadable("replied_tweets.json is unreadable")), "direct_reply")()

    assert "direct_reply halted: replied_tweets.json is unreadable" in caplog.text


@pytest.mark.parametrize("error", [StateUnreadable("replied_tweets.json is unreadable"),
                                   OutsideActiveHours("Bot asleep")],
                         ids=["state_unreadable", "overnight"])
def test_the_wrapper_and_record_failure_log_the_same_line(restarts, caplog, error):
    health.wrap_job(_raises(error), "direct_reply")()
    health.record_failure("direct_reply", error)

    first, second = caplog.messages
    assert first == second
    assert first.startswith("[HEALTH] direct_reply ")
    assert "no restart" in first


@pytest.mark.parametrize("error", [StateUnreadable("slots.json is unreadable"),
                                   OutsideActiveHours("Bot asleep")],
                         ids=["state_unreadable", "overnight"])
def test_an_unwatched_job_does_not_speak_of_safari_health(restarts, caplog, error):
    health.wrap_job(_raises(error), "editorial", safari_health=False)()

    [message] = caplog.messages
    assert message.startswith("[editorial] ")
    assert "[HEALTH]" not in message
    assert "Safari" not in message and "restart" not in message


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
                                 _raises(PageNotOpened("https://x.com/home")),
                                 _raises(StateUnreadable("slots.json is unreadable")),
                                 _raises(OutsideActiveHours("Bot asleep"))],
                         ids=["success", "failure", "browser_failure", "state_unreadable",
                              "overnight"])
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
                         ids=["state_unreadable", "overnight"])
def test_record_failure_judges_the_exception_it_is_handed(restarts, error):
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        assert health.record_failure("direct_reply", error) is False

    assert restarts == []
    assert not os.path.exists(health.HEALTH.path)


def test_record_failure_counts_a_handed_exception_outside_an_except(restarts):
    health.record_failure("direct_reply", PageNotOpened("https://x.com/home"))

    assert _failures() == 1


@pytest.mark.parametrize("error", NOT_BROWSER_FAILURES, ids=["bug", "model_timeout"])
def test_record_failure_counts_only_a_browser_failure(restarts, caplog, error):
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        assert health.record_failure("direct_reply", error) is False

    assert restarts == []
    assert not os.path.exists(health.HEALTH.path), "the failure counter is left alone"
    assert caplog.messages[0] == (f"[HEALTH] direct_reply failed outside the browser "
                                  f"({type(error).__name__}). Not a Safari failure, no restart.")


def test_record_failure_requires_the_exception(restarts):
    """Issue #239: no error in flight is read in its place."""
    try:
        raise RuntimeError("page never loaded")
    except RuntimeError:
        with pytest.raises(TypeError):
            health.record_failure("direct_reply")


def _unsaved(monkeypatch):
    def disk_full(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(state_store, "atomic_write_bytes", disk_full)


def _unparsable(monkeypatch):
    os.makedirs(os.path.dirname(health.HEALTH.path), exist_ok=True)
    with open(health.HEALTH.path, "w") as f:
        f.write("{")


@pytest.mark.parametrize("fault", [_unsaved, _unparsable], ids=["unsaved", "unparsable"])
@pytest.mark.parametrize("run", [lambda: None, _raises(PageNotOpened("https://x.com/home")),
                                 _raises(RuntimeError("bug in the job"))],
                         ids=["success", "browser_failure", "other_failure"])
def test_the_wrapper_never_raises_over_the_health_file(restarts, monkeypatch, fault, run):
    """The health file is disposable: an unreadable or unsaved counter is
    logged and never stops the job wrapper."""
    fault(monkeypatch)

    health.wrap_job(run, "direct_reply")()


VALID_HEALTH = {"consecutive_failures": 1, "last_recovery_ts": 1234.5, "total_recoveries": 4}
NOT_A_NUMBER = ["3", None, [1], {"n": 1}, True, False, -1]
INVALID_FIELDS = (
    [("consecutive_failures", v) for v in NOT_A_NUMBER + [2.5]]
    + [("total_recoveries", v) for v in NOT_A_NUMBER + [4.0]]
    + [("last_recovery_ts", v) for v in NOT_A_NUMBER + [-0.5, float("nan"), float("inf")]])


def _write_health(field, value):
    """safari_health.json as an Operator's hand edit leaves it: valid JSON,
    one field that is not a count."""
    os.makedirs(os.path.dirname(health.HEALTH.path), exist_ok=True)
    with open(health.HEALTH.path, "w") as f:
        json.dump({**VALID_HEALTH, field: value}, f)


def _assert_valid_health(data):
    for field in ("consecutive_failures", "total_recoveries"):
        assert type(data[field]) is int and data[field] >= 0, (field, data)
    ts = data["last_recovery_ts"]
    assert type(ts) in (int, float) and ts >= 0, data


@pytest.mark.parametrize("field,value", INVALID_FIELDS)
@pytest.mark.parametrize("run,failures", [(lambda: None, 0),
                                          (_raises(PageNotOpened("https://x.com/home")), None)],
                         ids=["success", "browser_failure"])
def test_the_wrapper_never_raises_over_an_invalid_health_field(restarts, caplog, field, value,
                                                              run, failures):
    """#303: a field that is not a count is reset to its default with a
    warning naming it; the valid fields are kept and the file rewritten."""
    _write_health(field, value)

    health.wrap_job(run, "direct_reply")()

    data = health.HEALTH.read()
    _assert_valid_health(data)
    if failures is None:  # a browser failure counts one more, from 0 once reset
        failures = 1 if field == "consecutive_failures" else VALID_HEALTH["consecutive_failures"] + 1
    assert data["consecutive_failures"] == failures
    if field != "consecutive_failures":
        assert data[field] == 0
    kept = {k: v for k, v in VALID_HEALTH.items() if k not in (field, "consecutive_failures")}
    assert {k: data[k] for k in kept} == kept
    assert any(r.levelname == "WARNING" and f"safari_health.json: {field} " in r.getMessage()
               for r in caplog.records)
    errors = [r.exc_info[0] for r in caplog.records if r.levelname == "ERROR"]
    assert errors == ([] if failures == 0 else [PageNotOpened]), "only the job's own error"


@pytest.mark.parametrize("field,value", INVALID_FIELDS)
def test_a_reset_after_restart_never_raises_over_an_invalid_health_field(field, value):
    """#303: restart_safari calls it after a real relaunch; raising there
    would report a restart that succeeded as failed."""
    _write_health(field, value)

    health.reset_after_restart("health_recovery")

    data = health.HEALTH.read()
    _assert_valid_health(data)
    assert data["consecutive_failures"] == 0


def test_a_valid_health_file_is_rewritten_as_it_was(restarts, caplog):
    """A float timestamp and integer counters are valid: nothing is reset,
    nothing is logged about them."""
    health.HEALTH.write(VALID_HEALTH)

    health.wrap_job(_raises(PageNotOpened("https://x.com/home")), "direct_reply")()

    assert health.HEALTH.read() == {**VALID_HEALTH, "consecutive_failures": 2}
    assert restarts == []
    assert not any(r.levelname == "WARNING" for r in caplog.records)


@pytest.fixture
def safari_restart(monkeypatch, tmp_path):
    """The real restart_safari with its quit and relaunch recorded, and
    autonomous_log.md in the test's folder. `launched` sets whether x.com
    renders after the relaunch."""
    steps = {"quits": 0, "launched": True}

    def quit_safari():
        steps["quits"] += 1
    monkeypatch.setattr(sh, "_quit_safari", quit_safari)
    monkeypatch.setattr(sh, "_launch_safari", lambda: steps["launched"])
    monkeypatch.setattr(health, "AUTONOMOUS_LOG_FILE", str(tmp_path / "autonomous_log.md"))
    return steps


def _flags():
    try:
        with open(health.AUTONOMOUS_LOG_FILE) as f:
            return [line for line in f.read().splitlines() if line]
    except FileNotFoundError:
        return []


def _fail(label="direct_reply"):
    return health.record_failure(label, PageNotOpened("https://x.com/home"))


def test_a_restart_refused_on_its_cooldown_is_counted_nowhere(safari_restart, caplog):
    """#302: the last restart is 15 min old, inside restart_safari's
    cooldown. health no longer has one of its own: nothing is counted and
    autonomous_log.md gets no line."""
    sh.HYGIENE_STATE.write({"last_run_ts": time.time() - 15 * 60})
    health.HEALTH.write({"consecutive_failures": 0, "last_recovery_ts": 1000,
                         "total_recoveries": 4})

    assert [_fail() for _ in range(health.RECOVERY_THRESHOLD)] == [False] * 3

    assert safari_restart["quits"] == 0
    assert _flags() == []
    assert health.HEALTH.read() == {"consecutive_failures": 3, "last_recovery_ts": 1000,
                                    "total_recoveries": 4}
    assert "[HEALTH] Safari restart refused — no recovery counted." in caplog.messages
    assert not hasattr(health, "COOLDOWN_SECONDS")


def test_a_failed_restart_is_flagged_as_failed_and_keeps_the_counter(safari_restart):
    safari_restart["launched"] = False
    health.HEALTH.write({"consecutive_failures": 2, "last_recovery_ts": 0, "total_recoveries": 4})

    assert _fail() is False

    assert safari_restart["quits"] == 1
    [flag] = _flags()
    assert "Safari recovery #5 " in flag and "(trigger=direct_reply, success=False)" in flag
    data = health.HEALTH.read()
    assert data["consecutive_failures"] == 3 and data["total_recoveries"] == 5
    assert data["last_recovery_ts"] > 0


@pytest.mark.parametrize("how", ["not_rendered", "raised"])
def test_a_failed_restart_starts_the_cooldown_for_the_next_failure(monkeypatch, safari_restart,
                                                                    caplog, how):
    """#302: a restart tried and failed starts restart_safari's cooldown, so
    the next failure past the threshold does not bounce Safari again (the
    2026-07-19 restart storm)."""
    if how == "not_rendered":
        safari_restart["launched"] = False
    else:
        def quit_raises():
            safari_restart["quits"] += 1
            raise OSError("osascript gone")
        monkeypatch.setattr(sh, "_quit_safari", quit_raises)
    health.HEALTH.write({"consecutive_failures": 2, "last_recovery_ts": 0, "total_recoveries": 4})

    assert _fail() is False
    assert _fail() is False

    assert safari_restart["quits"] == 1
    [flag] = _flags()
    assert "success=False" in flag
    data = health.HEALTH.read()
    assert data["consecutive_failures"] == 4 and data["total_recoveries"] == 5
    assert "[HEALTH] Safari restart refused — no recovery counted." in caplog.messages


def test_a_restart_that_succeeded_is_flagged_and_resets_the_counter(safari_restart):
    health.HEALTH.write({"consecutive_failures": 2, "last_recovery_ts": 0, "total_recoveries": 4})

    assert _fail() is True

    assert safari_restart["quits"] == 1
    [flag] = _flags()
    assert "Safari recovery #5 " in flag and "(trigger=direct_reply, success=True)" in flag
    data = health.HEALTH.read()
    assert data["consecutive_failures"] == 0 and data["total_recoveries"] == 5


def test_two_failures_crossing_the_threshold_together_restart_safari_once(monkeypatch,
                                                                          safari_restart):
    """#302: health claims nothing before the restart. The second failure
    waits for the Safari lock the first restart holds, then finds its
    cooldown: one restart, one recovery counted."""
    quitting, release = threading.Event(), threading.Event()

    def blocked_quit():
        safari_restart["quits"] += 1
        quitting.set()
        release.wait(5)
    monkeypatch.setattr(sh, "_quit_safari", blocked_quit)
    health.HEALTH.write({"consecutive_failures": health.RECOVERY_THRESHOLD - 1,
                         "last_recovery_ts": 0, "total_recoveries": 0})

    results = []
    first = threading.Thread(target=lambda: results.append(_fail("first")), daemon=True)
    first.start()
    assert quitting.wait(5)
    second = threading.Thread(target=lambda: results.append(_fail("second")), daemon=True)
    second.start()
    second.join(0.3)
    assert second.is_alive(), "the second restart waits for the first one's Safari lock"
    release.set()
    first.join(5)
    second.join(5)

    assert sorted(results) == [False, True]
    assert safari_restart["quits"] == 1
    assert len(_flags()) == 1
    assert health.HEALTH.read()["total_recoveries"] == 1
