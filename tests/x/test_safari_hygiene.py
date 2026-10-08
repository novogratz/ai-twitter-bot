"""src/x/safari_hygiene: dark-screen recovery."""
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
