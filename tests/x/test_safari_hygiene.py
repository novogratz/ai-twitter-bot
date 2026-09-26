"""src/x/safari_hygiene: dark-screen recovery, and a restart that waits for
the Safari lock (#257)."""
from datetime import datetime

import pytest

from tests.helpers import TORONTO, clock, stop_requested


def test_safari_warmup_verifies_render_and_retries_blank(monkeypatch):
    """Dark-screen recovery must verify x.com rendered after restart.
    A blank app shell should trigger cache-busted retries and return False if
    Safari never reaches a usable page."""
    from src.x import safari_hygiene as sh

    commands = []
    statuses = iter([
        "BLANK:0:https://x.com/home",
        "BLANK:0:https://x.com/home?bot_recover=1",
        "READY:shell:500",
    ])

    monkeypatch.setattr(sh.safari, "_run_applescript",
                        lambda script, *a, **k: commands.append((script, k.get("timeout_s"))) or True)
    monkeypatch.setattr(sh.time, "sleep", lambda *_: None)

    def fake_js(js_code, timeout_s=15, **_):
        if "serviceWorker" in js_code:
            return ""
        return next(statuses)

    monkeypatch.setattr(sh.safari, "_run_js", fake_js)

    assert sh._warm_up_xcom()
    joined = "\n".join(script for script, _ in commands)
    assert "bot_recover=" in joined, "blank render must trigger cache-busted retry"
    assert all(timeout for _, timeout in commands), "a wedged Safari must not hang the warm-up"


def test_safari_warmup_logs_a_failed_clear_and_a_silent_render_check(monkeypatch):
    from src.x import safari_hygiene as sh

    warnings = []
    monkeypatch.setattr(sh.log, "warning", lambda msg, *a, **k: warnings.append(msg))
    monkeypatch.setattr(sh.safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(sh.safari, "_run_js", lambda *a, **k: "")
    monkeypatch.setattr(sh.time, "sleep", lambda *_: None)

    assert sh._warm_up_xcom() is False
    assert "[HYGIENE] x.com SW clear JS failed; the render check decides." in warnings
    blank = [w for w in warnings if "still blank" in w]
    assert len(blank) == 3 and all(w.endswith(": no answer") for w in blank)


@pytest.mark.parametrize("when", ["day", "night", "stop"])
def test_restart_safari_does_nothing_outside_waking_hours(monkeypatch, when):
    """health.record_failure and the blank-page recovery restart Safari:
    at night, or once a stop was requested, the restart touches nothing."""
    from src.x import safari_hygiene as sh

    if when == "night":
        clock(monkeypatch, datetime(2026, 9, 20, 23, 30, tzinfo=TORONTO))
    elif when == "stop":
        stop_requested(monkeypatch)
    touched = []
    monkeypatch.setattr(sh, "_last_run_ts", lambda: 0.0)
    monkeypatch.setattr(sh, "_quit_safari", lambda: touched.append("quit"))
    monkeypatch.setattr(sh, "_launch_safari", lambda: touched.append("launch") or True)
    monkeypatch.setattr(sh, "_mark_ran", lambda: touched.append("mark"))

    if when == "day":
        assert sh.restart_safari(reason="health_recovery") is True
        assert touched == ["quit", "launch", "mark"]
    else:
        assert sh.restart_safari(reason="health_recovery") is False
        assert touched == []


@pytest.fixture
def bounce(monkeypatch):
    """A restart that only records its quit and its relaunch."""
    from src.x import safari_hygiene as sh

    steps = []
    monkeypatch.setattr(sh, "_quit_safari", lambda: steps.append("quit"))
    monkeypatch.setattr(sh, "_launch_safari", lambda: steps.append("launch") or True)
    return steps


def _in_thread(target):
    import threading

    result = []
    worker = threading.Thread(target=lambda: result.append(target()), daemon=True)
    worker.start()
    return worker, result


def test_a_restart_waits_for_the_session_in_progress(bounce):
    """#257: the session refresh and the health recovery quit Safari without
    the Safari lock, and could pull the tab from under a Reply or a read.
    The restart now waits for the session holding the lock to end."""
    import threading
    from src.x import safari, safari_hygiene as sh

    inside, leave = threading.Event(), threading.Event()

    def session():
        with safari._safari_lock:
            inside.set()
            leave.wait(5)
            bounce.append("session ends")
    reader = threading.Thread(target=session, daemon=True)
    reader.start()
    assert inside.wait(5)

    restart, result = _in_thread(lambda: sh.restart_safari(reason="preventive_schedule"))
    restart.join(0.3)
    assert restart.is_alive() and bounce == []

    leave.set()
    restart.join(5)
    reader.join(5)
    assert result == [True]
    assert bounce == ["session ends", "quit", "launch"]


def test_a_restart_from_a_job_holding_the_lock_does_not_deadlock(monkeypatch, bounce):
    """A job that holds the Safari lock and reports its third failure in a
    row restarts Safari from inside its own session: the lock is reentrant
    and the restart runs at once."""
    from src.core import health
    from src.x import safari

    monkeypatch.setattr(health, "_append_autonomous_flag", lambda *a: None)

    def job():
        with safari._safari_lock:
            fired = [health.record_failure("direct_reply", RuntimeError("page never loaded"))
                     for _ in range(health.RECOVERY_THRESHOLD)]
        return fired[-1]
    worker, result = _in_thread(job)
    worker.join(5)

    assert not worker.is_alive(), "a restart inside the job's own session deadlocked"
    assert result == [True] and bounce == ["quit", "launch"]


def test_a_queued_restart_reads_the_cooldown_once_it_has_the_lock(bounce):
    """Two restarts queued behind one session bounce Safari once: the second
    finds the first one's run inside the cooldown."""
    from src.x import safari, safari_hygiene as sh

    with safari._safari_lock:
        first, first_result = _in_thread(lambda: sh.restart_safari(reason="preventive_schedule"))
        second, second_result = _in_thread(lambda: sh.restart_safari(reason="health_recovery"))
        first.join(0.2)
        second.join(0.2)
    first.join(5)
    second.join(5)

    assert sorted(first_result + second_result) == [False, True]
    assert bounce == ["quit", "launch"]


def test_a_restart_that_waited_into_bedtime_does_nothing(monkeypatch, bounce):
    """The session ended after bedtime: the waiting restart gives up without
    raising and touches nothing."""
    from src.x import safari, safari_hygiene as sh

    with safari._safari_lock:
        restart, result = _in_thread(lambda: sh.restart_safari(reason="health_recovery"))
        restart.join(0.2)
        clock(monkeypatch, datetime(2026, 9, 20, 23, 30, tzinfo=TORONTO))
    restart.join(5)

    assert result == [False] and bounce == []


def test_a_wedged_osascript_holds_the_recovery_restart_only_up_to_its_bound(
        monkeypatch, unwalled, bounce):
    """#251 bounds the osascript runs made under the Safari lock: a session
    wedged in `open_url` gives the lock back past OPEN_TIMEOUT_S, and the
    health recovery waiting behind it then restarts Safari."""
    import subprocess
    import threading
    import time
    from src.core import health
    from src.x import safari

    real_run = subprocess.run
    monkeypatch.setattr(safari, "OPEN_TIMEOUT_S", 0.5)
    monkeypatch.setattr(safari.subprocess, "run",
                        lambda argv, **k: real_run(["sleep", "30"], **k))
    monkeypatch.setattr(safari, "_run_applescript", unwalled["_run_applescript"])
    monkeypatch.setattr(safari, "open_url", unwalled["open_url"])
    monkeypatch.setattr(health, "_append_autonomous_flag", lambda *a: None)
    health.HEALTH.write({"consecutive_failures": health.RECOVERY_THRESHOLD - 1,
                         "last_recovery_ts": 0, "total_recoveries": 0})

    inside = threading.Event()

    def session():
        with safari._safari_lock:
            inside.set()
            opened = safari.open_url("https://x.com/home")
            bounce.append(f"open_url returned {opened}")
    reader = threading.Thread(target=session, daemon=True)
    reader.start()
    assert inside.wait(5)

    started = time.monotonic()
    recovery, result = _in_thread(
        lambda: health.record_failure("direct_reply", RuntimeError("page never loaded")))
    recovery.join(5)
    reader.join(5)

    assert not recovery.is_alive() and time.monotonic() - started < 5
    assert result == [True]
    assert bounce == ["open_url returned False", "quit", "launch"]
