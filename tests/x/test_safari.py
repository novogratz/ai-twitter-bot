"""src/x/safari: bedtime checks at the browser lock and before AppleScript,
the page JavaScript runner."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.guards import active_hours as hours
from tests.helpers import TORONTO, clock


def test_browser_wait_rechecks_bedtime(monkeypatch):
    from src.x.safari import _AwakeSafariLock
    clock(monkeypatch, datetime(2026, 9, 20, 21, 59, tzinfo=TORONTO))
    browser = _AwakeSafariLock()
    released = []

    class SlowLock:
        def acquire(self):
            clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))

        def release(self):
            released.append(True)

    browser._lock = SlowLock()
    with pytest.raises(hours.OutsideActiveHours):
        with browser:
            pytest.fail("Browser action ran after bedtime")
    assert released == [True]


def test_submit_checks_bedtime_before_applescript(monkeypatch):
    from src.x import safari
    # Use the real helper (the suite normally prevents Safari calls).
    import importlib
    from unittest.mock import patch
    with patch("subprocess.run") as run:
        safari = importlib.reload(safari)
        clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))
        with pytest.raises(hours.OutsideActiveHours):
            safari._run_applescript("submission")
        run.assert_not_called()


def _fake_osascript(monkeypatch, run):
    import subprocess
    from src.x import safari
    monkeypatch.setattr(safari, "require_active", lambda: None)
    monkeypatch.setattr(safari, "subprocess", SimpleNamespace(
        run=run, SubprocessError=subprocess.SubprocessError,
        TimeoutExpired=subprocess.TimeoutExpired))


@pytest.mark.parametrize("outcome, expected", [
    (SimpleNamespace(returncode=0, stdout="CLICKED\n", stderr=""), "CLICKED"),
    (SimpleNamespace(returncode=1, stdout="", stderr="execution error"), ""),
    ("timeout", ""),
])
def test_run_js_returns_the_page_answer_and_removes_its_temp_file(monkeypatch, unwalled, outcome, expected):
    """_run_js reads the JS back as UTF-8, returns osascript's stdout, "" on a
    failed or timed-out run, and never leaves its temp file behind."""
    import os
    import subprocess
    seen = {}

    def run(argv, **kwargs):
        script = argv[-1]
        seen["path"] = script.split('POSIX file "')[1].split('"')[0]
        seen["utf8"] = "\u00abclass utf8\u00bb" in script
        with open(seen["path"], encoding="utf-8") as f:
            seen["js"] = f.read()
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return outcome

    _fake_osascript(monkeypatch, run)
    assert unwalled["_run_js"]("return 'é';") == expected
    assert seen["js"] == "return 'é';" and seen["utf8"]
    assert not os.path.exists(seen["path"])


def test_run_applescript_counts_a_timeout_as_a_failed_attempt(monkeypatch, unwalled):
    """A wedged Safari must not hang the caller: past timeout_s the run fails."""
    import subprocess
    from src.x import safari

    seen = []

    def run(argv, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(safari, "require_active", lambda: None)
    monkeypatch.setattr(safari.subprocess, "run", run)
    assert unwalled["_run_applescript"]("return 1", timeout_s=20) is False
    assert seen == [20]
