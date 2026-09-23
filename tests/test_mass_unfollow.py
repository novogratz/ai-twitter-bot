"""bin/mass_unfollow.py stays inside Waking hours and is bounded (issue #122).

The script is loaded from its file; every osascript path is replaced by a
fake browser, so no test reaches Safari.
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

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "mass_unfollow.py"


def _toronto(hour, minute=0, second=0):
    return datetime(2026, 9, 23, hour, minute, second, tzinfo=ZoneInfo(config.BOT_TIMEZONE))


class FakeBrowser:
    """Every visible button is a new account; every confirm succeeds."""

    def __init__(self, script):
        self.script = script
        self.picks = 0
        self.confirms = 0
        self.on_pick = lambda: None
        self.on_confirm = lambda: None

    def run_js(self, js):
        if js == self.script.CONFIRM_JS:
            self.confirms += 1
            self.on_confirm()
            return "CONFIRMED"
        if "var keep" in js:
            self.picks += 1
            self.on_pick()
            return "CLICK:user%d" % self.picks
        return "OK"


@pytest.fixture
def script(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("mass_unfollow_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def no_browser(*a, **k):
        raise AssertionError("mass_unfollow reached osascript")

    browser = FakeBrowser(mod)
    monkeypatch.setattr(mod, "run_js", browser.run_js)
    monkeypatch.setattr(mod.subprocess, "run", no_browser)
    monkeypatch.setattr(mod, "_reload_page", no_browser)
    monkeypatch.setattr(mod, "_ensure_following_page", lambda: None)
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


def test_legacy_keep_set_protects_respect_list_targets_and_seed_tiers(script, monkeypatch):
    from src.account import engage_bot
    from src.guards import respect_list
    monkeypatch.setattr(respect_list, "load", lambda: {"mistralai"})
    monkeypatch.setattr(action_guard, "load_whitelist",
                        lambda: {"tier1": {"thebtctherapist"}, "tier2": {"morganhousel"}})
    keep = script._legacy_keep_set()
    assert {"mistralai", "thebtctherapist", "morganhousel"} <= keep
    assert {h.lower() for h in engage_bot.TARGET_ACCOUNTS} <= keep
