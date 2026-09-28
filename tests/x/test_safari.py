"""src/x/safari: bedtime checks at the browser lock and before AppleScript,
save the page session's tab close, the page JavaScript runner."""
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.guards import active_hours as hours
from tests.helpers import TORONTO, clock, stop_requested


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


@pytest.mark.parametrize("failure", [
    FileNotFoundError(2, "No such file or directory", "osascript"),
    BlockingIOError(35, "Resource temporarily unavailable"),
], ids=["missing", "fork"])
def test_an_osascript_that_does_not_start_is_a_failed_run(monkeypatch, unwalled, caplog, failure):
    """#298 review: an `OSError` at the osascript launch is a failed run,
    as `_run_js` and the tab close already treated it: keys and the paste
    return False, logged, and never raise to the write."""
    from src.x import safari
    for name in ("_run_applescript", "_paste_text"):
        monkeypatch.setattr(safari, name, unwalled[name])
    monkeypatch.setattr(safari, "require_active", lambda: None)
    monkeypatch.setattr(safari.time, "sleep", lambda *_: None)
    tries = []

    def fail(argv, **kwargs):
        tries.append(argv)
        raise failure
    monkeypatch.setattr(safari.subprocess, "run", fail)

    assert safari._run_applescript(safari.FIRST_TWEET_KEYS, retries=2) is False
    assert len(tries) == 2
    assert safari._paste_text("hello") is False
    assert "AppleScript did not start" in caplog.text


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
    ("_close_session_tab", "CLOSE_TIMEOUT_S", (), None),
    ("_scroll_page", "SCROLL_TIMEOUT_S", (), None),
    ("_paste_text", "KEYSTROKE_TIMEOUT_S", ("hello",), False),
])
def test_a_wedged_osascript_gives_the_safari_lock_back(monkeypatch, unwalled, primitive, bound,
                                                       args, failed):
    """#251: open_url, the tab close, the scroll and the paste had no
    timeout, so a wedged osascript held the Safari lock. Past its bound the
    child is killed, the primitive returns and the lock is free. A `sleep`
    child stands in for the wedged osascript. The tab walk and the other
    keys go through `Page.keys`, bounded by KEYSTROKE_TIMEOUT_S
    (test_page_session.py)."""
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
    monkeypatch.setattr(safari, "_close_session_tab", unwalled["_close_session_tab"])
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


def _asleep(monkeypatch, why):
    if why == "bedtime":
        clock(monkeypatch, datetime(2026, 9, 20, 23, 30, tzinfo=TORONTO))
    else:
        stop_requested(monkeypatch)


@pytest.mark.parametrize("why", ["bedtime", "stop"])
def test_asleep_only_the_session_tab_close_runs(monkeypatch, unwalled, why):
    """#300: after bedtime or a stop every AppleScript run is refused before
    osascript starts, save the close of the tab a page session opened,
    which is local and sends nothing to X."""
    from src.x import safari
    for name in ("_run_applescript", "_run_js", "_paste_text", "open_url", "_close_session_tab"):
        monkeypatch.setattr(safari, name, unwalled[name])
    runs = []
    monkeypatch.setattr(safari.subprocess, "run",
                        lambda argv, **k: runs.append((argv[-1], k.get("timeout"))))
    monkeypatch.setattr(safari.time, "sleep", lambda *_: None)
    _asleep(monkeypatch, why)

    for primitive in (lambda: safari.open_url("https://x.com/home"),
                      lambda: safari._run_js("return 1"),
                      lambda: safari._run_applescript(safari.FIRST_TWEET_KEYS),
                      lambda: safari._paste_text("hello"),
                      safari._scroll_page):
        with pytest.raises(hours.OutsideActiveHours):
            primitive()
    assert runs == []

    safari._close_session_tab()
    [(script, timeout)] = runs
    assert "close current tab" in script
    assert timeout == safari.CLOSE_TIMEOUT_S


@pytest.mark.parametrize("failure", [
    subprocess.CalledProcessError(1, "osascript", stderr="no window"),
    subprocess.TimeoutExpired("osascript", 5),
    FileNotFoundError("osascript"),
    PermissionError("osascript"),
], ids=["exit_status", "timeout", "missing", "denied"])
def test_a_failed_session_tab_close_never_raises(monkeypatch, unwalled, failure):
    """#300: `confirmed_write.run` no longer guards the close, so a write
    that shipped keeps its outcome only if a failed close never raises."""
    from src.x import safari
    monkeypatch.setattr(safari, "_close_session_tab", unwalled["_close_session_tab"])

    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(safari.subprocess, "run", fail)

    assert safari._close_session_tab() is None


def test_only_the_session_tab_close_skips_the_waking_hours_check():
    """#300: in safari.py, the functions that start osascript themselves are
    `_run_applescript` and `_run_js`, which check waking hours first, and
    `_close_session_tab`, which alone does not. Every other primitive runs
    through the first two."""
    import ast
    from pathlib import Path
    from src.x import safari

    tree = ast.parse(Path(safari.__file__).read_text())

    def calls(fn, name):
        return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)]

    spawning = {fn.name: fn for fn in ast.walk(tree)
                if isinstance(fn, ast.FunctionDef)
                and any(isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", None)
                        == "subprocess" for c in calls(fn, "run"))}
    assert set(spawning) == {"_run_applescript", "_run_js", "_close_session_tab"}
    assert calls(spawning["_run_applescript"], "require_active")
    assert calls(spawning["_run_js"], "require_active")
    assert not calls(spawning["_close_session_tab"], "require_active")
    spawners = {"Popen", "check_output", "check_call", "call", "system", "spawn", "execv"}
    assert not [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr in spawners], (
        "safari.py starts osascript through subprocess.run only")
    assert not calls(tree, "_close_session_tab"), "safari.py never calls the unchecked close itself"
