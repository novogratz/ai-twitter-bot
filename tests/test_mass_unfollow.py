"""bin/mass_unfollow.py stays inside Waking hours and is bounded (issue #122),
and drives Safari only through the src.x.safari primitives (issue #152).

The script is loaded from its file; the safari primitives are replaced by a
fake browser that checks Waking hours first, as the real ones do, so no test
reaches Safari.
"""
import importlib.util
import json
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.guards import action_guard, active_hours
from src.core import config
from src.x import safari

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "mass_unfollow.py"


def _toronto(hour, minute=0, second=0):
    return datetime(2026, 9, 23, hour, minute, second, tzinfo=ZoneInfo(config.BOT_TIMEZONE))


class FakeBrowser:
    """Every visible button is a new account; every confirm succeeds.

    `before_js` runs before the Waking-hours check of each page script, the
    moment a stop or 22:00 can reach the real `_run_js`."""

    def __init__(self, script):
        self.script = script
        self.url = "https://x.com/%s/following" % config.BOT_HANDLE
        self.picks = 0
        self.confirms = 0
        self.calls = []
        self.applescripts = []
        self.before_js = lambda js: None
        self.on_pick = lambda: None
        self.on_confirm = lambda: None

    def run_js(self, js, timeout_s=15, *, log_prefix="", activate=False, raise_timeout=False):
        self.before_js(js)
        active_hours.require_active()
        self.calls.append((js, timeout_s, log_prefix))
        if js == self.script.CONFIRM_JS:
            self.confirms += 1
            self.on_confirm()
            return "CONFIRMED"
        if "var keep" in js:
            self.picks += 1
            self.on_pick()
            return "CLICK:user%d" % self.picks
        if js == "location.href":
            return self.url
        return "OK"

    def run_applescript(self, script, retries=1, timeout_s=None):
        active_hours.require_active()
        self.applescripts.append((script, timeout_s))
        return True


@pytest.fixture
def script(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("mass_unfollow_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def no_browser(*a, **k):
        raise AssertionError("mass_unfollow reached a subprocess")

    browser = FakeBrowser(mod)
    monkeypatch.setattr(safari, "_run_js", browser.run_js)
    monkeypatch.setattr(safari, "_run_applescript", browser.run_applescript)
    monkeypatch.setattr(mod.subprocess, "run", no_browser)
    monkeypatch.setattr(mod, "_bot_is_running", lambda: False)
    monkeypatch.setattr(mod, "_whitelist_keep_set", set)
    monkeypatch.setattr(mod, "_pause", lambda seconds: None)
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))

    handlers = {}
    monkeypatch.setattr(mod.signal, "signal", lambda sig, fn: handlers.__setitem__(sig, fn))
    monkeypatch.setattr(active_hours, "_STOP", threading.Event())

    ledger = []
    monkeypatch.setattr(action_guard, "record", lambda action, target="": ledger.append(target))
    monkeypatch.setattr(action_guard, "adjust_following", lambda delta: None)
    monkeypatch.setattr(sys, "argv", ["mass_unfollow.py"])

    clock = {"now": _toronto(12)}
    monkeypatch.setattr(active_hours, "now_local", lambda: clock["now"])

    mod.browser, mod.clock, mod.ledger, mod.handlers = browser, clock, ledger, handlers
    mod.results = tmp_path / "mass_unfollow_results.json"
    return mod


@pytest.mark.parametrize("now", [_toronto(22, 0), _toronto(23, 30), _toronto(4, 29)])
def test_refuses_to_start_overnight(script, now):
    script.clock["now"] = now
    with pytest.raises(SystemExit) as exit_:
        script.main()
    assert exit_.value.code == 1
    assert script.browser.picks == 0
    assert script.handlers == {}
    assert not script.results.exists()


def test_stops_between_two_unfollows_when_waking_hours_end(script):
    script.clock["now"] = _toronto(21, 59, 50)

    def ten_seconds_pass():
        script.clock["now"] = _toronto(22, 0)

    script.browser.on_confirm = ten_seconds_pass
    script.main()
    assert script.browser.picks == 1
    assert script.browser.confirms == 1
    assert script.ledger == ["user1"]
    assert json.loads(script.results.read_text()) == ["user1"]


def test_never_confirms_a_click_made_before_22_00(script):
    script.clock["now"] = _toronto(21, 59, 59)

    def one_second_passes():
        script.clock["now"] = _toronto(22, 0)

    script.browser.on_pick = one_second_passes
    script.main()
    assert script.browser.picks == 1
    assert script.browser.confirms == 0
    assert script.ledger == []
    assert json.loads(script.results.read_text()) == []


def test_run_is_bounded_by_default(script):
    def bounded():
        assert script.browser.confirms <= 150, "no default bound"

    script.browser.on_confirm = bounded
    script.main()
    assert script.DEFAULT_MAX == 150
    assert script.browser.confirms == 150
    assert len(script.ledger) == 150


def test_sigterm_stops_before_the_next_unfollow(script):
    script.browser.on_confirm = lambda: script.handlers[signal.SIGTERM](signal.SIGTERM, None)
    script.main()
    assert script.browser.picks == 1
    assert script.ledger == ["user1"]
    assert json.loads(script.results.read_text()) == ["user1"]


def test_bedtime_before_the_confirm_script_leaves_the_account_followed(script, capsys):
    """22:00 between the last stop check and the confirm: `_run_js` refuses
    before its osascript starts, so the modal stays open, nothing is
    recorded and the run ends with its report."""
    script.clock["now"] = _toronto(21, 59, 59)

    def bedtime_at_confirm(js):
        if js == script.CONFIRM_JS:
            script.clock["now"] = _toronto(22, 0)

    script.browser.before_js = bedtime_at_confirm
    script.main()
    assert script.browser.picks == 1
    assert script.browser.confirms == 0
    assert script.ledger == []
    assert json.loads(script.results.read_text()) == []
    assert "var keep" in script.browser.calls[-1][0], "a page script ran after the refusal"
    out = capsys.readouterr().out
    assert "STOP: Waking hours ended (22:00 America/Toronto)" in out
    assert "TOTAL unfollowed: 0" in out


def test_stop_signal_before_the_confirm_script_keeps_earlier_unfollows(script, capsys):
    def sigterm_at_second_confirm(js):
        if js == script.CONFIRM_JS and script.browser.confirms == 1:
            script.handlers[signal.SIGTERM](signal.SIGTERM, None)

    script.browser.before_js = sigterm_at_second_confirm
    script.main()
    assert script.browser.picks == 2
    assert script.browser.confirms == 1
    assert script.ledger == ["user1"]
    assert json.loads(script.results.read_text()) == ["user1"]
    out = capsys.readouterr().out
    assert "STOP: stop signal" in out
    assert "TOTAL unfollowed: 1" in out


def test_page_scripts_go_through_safari_with_the_tools_prefix(script, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mass_unfollow.py", "--max", "2"])
    script.main()
    assert script.ledger == ["user1", "user2"]
    assert {prefix for _, _, prefix in script.browser.calls} == {"[MASS_UNFOLLOW]"}
    assert all(timeout == 30 for js, timeout, _ in script.browser.calls
               if js == script.CONFIRM_JS or "var keep" in js)
    assert script.browser.applescripts == []


def test_a_page_script_without_answer_is_reported_as_osaerr(script, monkeypatch, capsys):
    def no_answer_on_pick(js, *a, **k):
        answer = script.browser.run_js(js, *a, **k)
        return "" if "var keep" in js else answer

    monkeypatch.setattr(safari, "_run_js", no_answer_on_pick)
    script.main()
    assert script.ledger == []
    out = capsys.readouterr().out
    assert out.count("JS err: OSAERR:no answer (see bot.log [MASS_UNFOLLOW])") == 6
    assert "ABORT: repeated JS errors" in out
    assert "TOTAL unfollowed: 0" in out


def test_navigates_to_following_through_run_applescript(script, monkeypatch, capsys):
    script.browser.url = "https://x.com/home"
    monkeypatch.setattr(sys, "argv", ["mass_unfollow.py", "--max", "1"])
    script.main()
    target = "https://x.com/%s/following" % config.BOT_HANDLE
    assert script.browser.applescripts == [
        ('tell application "Safari" to set URL of current tab of front window to "%s"' % target, 15)]
    assert "navigating to %s" % target in capsys.readouterr().out


def test_an_empty_list_is_reloaded_through_run_js_before_done(script, monkeypatch, capsys):
    def empty_list(js, *a, **k):
        answer = script.browser.run_js(js, *a, **k)
        return "NONE" if "var keep" in js else answer

    monkeypatch.setattr(safari, "_run_js", empty_list)
    script.main()
    reloads = [c for c in script.browser.calls if c[0] == "location.reload(); 'RELOADED'"]
    assert len(reloads) == 2
    assert "DONE: no unfollow buttons after 3 reloads" in capsys.readouterr().out


def test_legacy_keep_set_protects_respect_list_targets_and_seed_tiers(script, monkeypatch):
    from src.account import engage_bot
    from src.guards import respect_list
    monkeypatch.setattr(respect_list, "load", lambda: {"mistralai"})
    monkeypatch.setattr(action_guard, "load_whitelist",
                        lambda: {"tier1": {"thebtctherapist"}, "tier2": {"morganhousel"}})
    keep = script._legacy_keep_set()
    assert {"mistralai", "thebtctherapist", "morganhousel"} <= keep
    assert {h.lower() for h in engage_bot.TARGET_ACCOUNTS} <= keep
