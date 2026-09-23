"""unfollow_account reads both page answers and records only a confirmed
unfollow (issue #141)."""
import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def unfollow_env(monkeypatch, tmp_path):
    """Unfollow allowed by policy, browser stubbed; `answers` feeds the page
    JavaScript results in order."""
    from src.core import config
    from src.guards import action_guard as ag
    from src.x import safari
    from src.x import twitter_client as tc

    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(config, "MAX_UNFOLLOWS_PER_DAY", 5)
    monkeypatch.setattr(config, "FOLLOW_ACTION_JITTER_SECONDS", 0)
    wl = tmp_path / "whitelist.json"
    wl.write_text(json.dumps({"tiers": {"tier1": ["karpathy"]}}))
    monkeypatch.setattr(config, "WHITELIST_FILE", str(wl))
    monkeypatch.setattr(ag, "_WL_CACHE", {})
    monkeypatch.setattr(ag, "_WL_MTIME", 0.0)
    following = tmp_path / "following_count.json"
    following.write_text(json.dumps({"count": 100}))
    monkeypatch.setattr(ag, "_FOLLOWING_COUNT_FILE", str(following))

    answers, scripts, opened, closed = [], [], [], []

    def run_js(js):
        scripts.append(js)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(safari, "_run_js", run_js)
    monkeypatch.setattr(safari, "close_front_tab", lambda: closed.append(True))
    monkeypatch.setattr(tc.webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)

    return SimpleNamespace(
        tc=tc, ag=ag, answers=answers, scripts=scripts, opened=opened, closed=closed,
        following=lambda: json.loads(following.read_text())["count"],
        ledger=ag._load_ledger)


@pytest.mark.parametrize("answer", ["NO_FOLLOWING_BTN", ""])
def test_missing_following_button_records_nothing(unfollow_env, answer):
    unfollow_env.answers.append(answer)

    assert unfollow_env.tc.unfollow_account("someaccount") is False

    assert len(unfollow_env.scripts) == 1, "no confirm without a Following click"
    assert unfollow_env.ledger() == []
    assert unfollow_env.following() == 100
    assert unfollow_env.closed


@pytest.mark.parametrize("answer", ["NO_CONFIRM", ""])
def test_missing_confirmation_records_nothing(unfollow_env, answer):
    unfollow_env.answers.extend(["CLICKED", answer])

    assert unfollow_env.tc.unfollow_account("someaccount") is False

    assert unfollow_env.ledger() == []
    assert unfollow_env.following() == 100
    assert unfollow_env.closed


def test_confirmed_unfollow_records_one_row(unfollow_env):
    unfollow_env.answers.extend(["CLICKED", "CONFIRMED"])

    assert unfollow_env.tc.unfollow_account("@SomeAccount") is True

    rows = unfollow_env.ledger()
    assert [(r["action"], r["target"], r["dry_run"]) for r in rows] == [
        (unfollow_env.ag.UNFOLLOW, "someaccount", False)]
    assert unfollow_env.following() == 99
    assert unfollow_env.closed


def test_dry_run_records_a_dry_row_without_the_browser(unfollow_env, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")

    assert unfollow_env.tc.unfollow_account("someaccount") is unfollow_env.tc.DRY_RUN_RECORDED

    assert unfollow_env.opened == [] and unfollow_env.scripts == []
    rows = unfollow_env.ledger()
    assert [(r["action"], r["dry_run"]) for r in rows] == [(unfollow_env.ag.UNFOLLOW, True)]
    assert unfollow_env.following() == 100


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
