"""src/x/safari: bedtime checks at the browser lock and before AppleScript,
the page JavaScript runner."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.guards import active_hours as hours
from tests.helpers import TORONTO, clock


def test_browser_wait_rechecks_bedtime(monkeypatch):
    from src.x.safari import _AwakeSafariLock
    clock(monkeypatch, datetime(2026, 9, 20, 23, 29, tzinfo=TORONTO))
    browser = _AwakeSafariLock()
    released = []

    class SlowLock:
        def acquire(self):
            clock(monkeypatch, datetime(2026, 9, 20, 23, 30, tzinfo=TORONTO))

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
        clock(monkeypatch, datetime(2026, 9, 20, 23, 30, tzinfo=TORONTO))
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


def test_open_url_targets_safari_not_the_default_browser(monkeypatch, unwalled):
    """`webbrowser.open` followed the default browser: with Firefox as the
    default, pages opened in Firefox while `_run_js` read Safari's front tab.
    open_url names Safari and escapes the URL for the AppleScript literal."""
    from src.x import safari

    scripts = []
    monkeypatch.setattr(safari, "_run_applescript", lambda script, **k: scripts.append(script) or True)
    assert unwalled["open_url"]('https://x.com/search?q=%22AI%22&x="y"') is True
    [script] = scripts
    assert 'tell application "Safari"' in script
    assert "activate" in script
    assert 'open location "https://x.com/search?q=%22AI%22&x=\\"y\\""' in script


@pytest.mark.parametrize("primitive, bound, args, failed", [
    ("open_url", "OPEN_TIMEOUT_S", ("https://x.com/home",), False),
    ("close_front_tab", "CLOSE_TIMEOUT_S", (), None),
    ("_scroll_page", "SCROLL_TIMEOUT_S", (), None),
    ("_paste_text", "KEYSTROKE_TIMEOUT_S", ("hello",), False),
    ("_navigate_to_first_tweet", "KEYSTROKE_TIMEOUT_S", (), None),
])
def test_a_wedged_osascript_gives_the_safari_lock_back(monkeypatch, unwalled, primitive, bound,
                                                       args, failed):
    """#251: open_url, the tab close, the scroll, the paste and the tab
    walk had no timeout, so a wedged osascript held the Safari lock. Past
    its bound the child is killed, the primitive returns and the lock is
    free. A `sleep` child stands in for the wedged osascript."""
    import subprocess
    import threading
    import time
    from src.x import safari

    real_run = subprocess.run
    monkeypatch.setattr(safari, "require_active", lambda: None)
    monkeypatch.setattr(safari, bound, 0.3)
    monkeypatch.setattr(safari.subprocess, "run",
                        lambda argv, **k: real_run(["sleep", "30"], **k))
    monkeypatch.setattr(safari, "_run_applescript", unwalled["_run_applescript"])
    monkeypatch.setattr(safari, "open_url", unwalled["open_url"])
    monkeypatch.setattr(safari, "_paste_text", unwalled["_paste_text"])
    monkeypatch.setattr(safari.time, "sleep", lambda *_: None)

    started = time.monotonic()
    with safari._safari_lock:
        result = getattr(safari, primitive)(*args)
    assert time.monotonic() - started < 5
    assert result is failed

    free = []

    def take_and_give_back():
        if safari._safari_lock._lock.acquire(timeout=1):
            free.append(True)
            safari._safari_lock._lock.release()
    other = threading.Thread(target=take_and_give_back)
    other.start()
    other.join()
    assert free == [True]
