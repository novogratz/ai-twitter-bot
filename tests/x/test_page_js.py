"""Every page JavaScript runs through `safari._run_js` (issue #144): each
caller keeps its timeout, its log prefix and its answer on failure, and
lets `OutsideActiveHours` through without it counting as a Safari failure."""
import json
import os
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

from src.guards.active_hours import OutsideActiveHours
from src.x.confirmed_write import WriteOutcome
from src.x.twitter_client import FollowOutcome

OWN_POST = "https://x.com/TheAIShrink/status/2063500000000000103"


class FakeJS:
    """Stands in for `safari._run_js`: records each call, then returns the
    next scripted answer or raises it."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, js, timeout_s=15, **kwargs):
        self.calls.append(SimpleNamespace(js=js, timeout_s=timeout_s, **kwargs))
        answer = self.answers.pop(0) if self.answers else ""
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture
def browser(monkeypatch):
    """Stubs the navigation around each page script; `browser(*answers)`
    installs a FakeJS as `safari._run_js`."""
    from src.x import safari

    monkeypatch.setattr(safari, "open_url", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)

    def install(*answers):
        fake = FakeJS(*answers)
        monkeypatch.setattr(safari, "_run_js", fake)
        return fake
    return install


def _like_js(monkeypatch):
    from src.x import twitter_client as tc
    return tc._run_page_js("1")


def _follow(monkeypatch):
    from src.guards import action_guard, follow_policy
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(follow_policy, "judge", lambda *a, **k: follow_policy.ADMITTED)
    monkeypatch.setattr(follow_policy, "judge_profile", lambda *a, **k: follow_policy.ADMITTED)
    monkeypatch.setattr(action_guard, "jitter_sleep", lambda *a, **k: None)
    return tc.follow_account("someaccount")


def _pin(monkeypatch):
    from src.x import twitter_client as tc
    monkeypatch.setenv("DRY_RUN", "0")
    return tc.pin_own_tweet(OWN_POST)


def _profile_quality(monkeypatch):
    from src.x import scraper
    return scraper._scrape_profile_quality()


def _tweets(monkeypatch):
    from src.x import scraper
    blanks = []
    monkeypatch.setattr(scraper, "_record_blank_page", lambda **k: blanks.append(k))
    monkeypatch.setattr(scraper, "_record_timed_out_scrape", lambda label: blanks.append(label))
    return scraper._scrape_tweets_from_page("search 'ai'", 10)


def _following_tab(monkeypatch):
    from src.x import scraper
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", lambda *a, **k: [])
    return scraper.scrape_following_feed(12)


def _own_replies(monkeypatch):
    from src.x import scraper
    return scraper.scrape_own_tweet_and_replies()


def _followers_list(monkeypatch):
    from src.account import followback_bot
    return followback_bot._scrape_followers_list(5)


def _follower_count(monkeypatch):
    from src.account import follower_tracker_bot
    return follower_tracker_bot._scrape_follower_count()


def _warm_up(monkeypatch):
    from src.x import safari_hygiene
    return safari_hygiene._warm_up_xcom()


# caller, (timeout_s, log_prefix, activate) of its page script, its answer
# when osascript failed
CALLERS = {
    "like": (_like_js, (10, "[LIKE]", False), ""),
    "follow": (_follow, (15, "[FOLLOW]", True), FollowOutcome.FAILED),
    "pin": (_pin, (15, "[PIN]", True), WriteOutcome.FAILED),
    "profile_quality": (_profile_quality, (15, "[SCRAPE]", False), {}),
    "tweets": (_tweets, (30, "[SCRAPE]", True), []),
    "following_tab": (_following_tab, (8, "[SCRAPE]", False), []),
    "own_replies": (_own_replies, (30, "[REPLYBACK]", True), None),
    "followers_list": (_followers_list, (30, "[FOLLOWBACK]", True), []),
    "follower_count": (_follower_count, (20, "[FOLLOWER]", True), 0),
    "warm_up": (_warm_up, (45, "[HYGIENE]", True), False),
}


@pytest.mark.parametrize("name", CALLERS)
def test_each_caller_keeps_its_timeout_prefix_and_failure_answer(monkeypatch, browser, name):
    run, (timeout_s, prefix, activate), on_failure = CALLERS[name]
    fake = browser()

    assert run(monkeypatch) == on_failure
    first = fake.calls[0]
    assert (first.timeout_s, first.log_prefix, first.__dict__.get("activate", False)) \
        == (timeout_s, prefix, activate)


# Callers that used to wrap osascript in `except Exception`, swallowing the
# bedtime check with every other error.
SWALLOWED_BEFORE = ["follow", "pin", "profile_quality", "tweets", "following_tab",
                    "own_replies", "followers_list", "follower_count", "warm_up"]


@pytest.mark.parametrize("name", ["like", *SWALLOWED_BEFORE])
def test_bedtime_reaches_the_job_through_every_caller(monkeypatch, browser, name):
    run = CALLERS[name][0]
    browser(OutsideActiveHours("Bot asleep"))
    with pytest.raises(OutsideActiveHours):
        run(monkeypatch)


def test_bedtime_through_a_job_is_not_a_safari_failure(monkeypatch, browser, tmp_path):
    """Nine callers used to swallow bedtime; now it reaches the jobs'
    `except Exception`, which must not count it toward a Safari restart."""
    from src.account import follower_tracker_bot
    from src.core import health

    restarts = []
    monkeypatch.setattr(health, "_restart_safari", lambda: restarts.append(1) or True)
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        browser(OutsideActiveHours("Bot asleep"))
        follower_tracker_bot.safe_run_follower_tracker_cycle()
    assert restarts == []
    assert not os.path.exists(health.HEALTH.path), "the failure counter is left alone"


# The answer each caller falls back on when the page answer does not parse.
UNPARSABLE = {
    "profile_quality": ("{not json", {}),
    "tweets": ("[{not json", []),
    "own_replies": ("{not json", None),
    "followers_list": ("{not json", []),
    "follower_count": ("1.2.3", 0),
}


@pytest.mark.parametrize("name", UNPARSABLE)
def test_an_unparsable_answer_keeps_its_old_fallback(monkeypatch, browser, name):
    answer, on_failure = UNPARSABLE[name]
    browser(answer)
    assert CALLERS[name][0](monkeypatch) == on_failure


# Every caller but the tweet scrape, whose `except Exception` also counts a
# blank page, now catches nothing broader than a parse error.
LOUD = [name for name in CALLERS if name != "tweets"]


@pytest.mark.parametrize("name", LOUD)
def test_a_test_that_forgets_to_mock_run_js_fails_on_the_wall(monkeypatch, browser, name):
    with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
        CALLERS[name][0](monkeypatch)


def test_scrape_timeouts_retry_once_then_count_as_a_blank(monkeypatch, browser):
    from src.x import scraper

    blanks = []
    monkeypatch.setattr(scraper, "_record_timed_out_scrape", blanks.append)
    timeout = subprocess.TimeoutExpired("osascript", 30)
    fake = browser(timeout, timeout)

    assert scraper._scrape_tweets_from_page("search 'ai'", 10) == []
    assert [c.raise_timeout for c in fake.calls] == [True, True]
    assert blanks == ["search 'ai'"]


def test_scrape_failure_is_not_a_blank_page_but_no_articles_is(monkeypatch, browser):
    """"" from _run_js means osascript failed (JavaScript from Apple Events
    off, no window): it must not push Safari toward a restart."""
    from src.x import scraper

    blanks = []
    monkeypatch.setattr(scraper, "_record_blank_page", lambda **k: blanks.append(k["label"]))
    browser("", "NO_ARTICLES")

    assert scraper._scrape_tweets_from_page("search 'ai'", 10) == []
    assert blanks == []
    assert scraper._scrape_tweets_from_page("search 'ai'", 10) == []
    assert blanks == ["search 'ai'"]


def test_scrape_parses_the_page_answer(monkeypatch, browser):
    from src.x import scraper

    browser(json.dumps([{"u": OWN_POST, "t": "hello", "a": "Someone", "l": 3, "r": 1}]))
    tweets = scraper._scrape_tweets_from_page("search 'ai'", 10)
    assert [(t["url"], t["likes"], t["replies"]) for t in tweets] == [(OWN_POST, 3, 1)]


def test_follow_ships_only_on_a_clicked_answer(monkeypatch, browser):
    from src.guards import action_guard, follow_policy

    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(a))
    monkeypatch.setattr(follow_policy, "adjust_following", lambda *a: None)
    browser("CLICKED")
    assert _follow(monkeypatch) is FollowOutcome.FOLLOWED
    assert recorded == [(action_guard.FOLLOW,)]

    browser("ALREADY")
    assert _follow(monkeypatch) is FollowOutcome.ALREADY_FOLLOWED
    assert len(recorded) == 1


def test_own_replies_script_carries_no_applescript_escaping(monkeypatch, browser):
    """The script used to sit inside an AppleScript string, escaped for it;
    read from a file it must be plain JavaScript."""
    answer = {"own_tweet": "ours", "replies": [{"user": "a", "text": "hi", "url": OWN_POST}]}
    fake = browser(json.dumps(answer))
    assert _own_replies(monkeypatch) == answer
    js = fake.calls[0].js
    assert 'article[data-testid="tweet"]' in js
    assert r"h.match(/\/status\/\d+$/)" in js
    assert '\\"' not in js and "\\\\" not in js


def _node_run(js, document_js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the page script cannot be run")
    program = document_js + f"\nconsole.log(eval({json.dumps(js)}));"
    res = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def test_own_replies_script_reads_a_thread(monkeypatch, browser):
    fake = browser()
    _own_replies(monkeypatch)
    fake_dom = r"""
    function el(attrs, kids) {
        return {
            attrs: attrs, kids: kids || [], textContent: attrs.text || '',
            getAttribute: function(n) { return this.attrs[n] || null; },
            querySelector: function(s) { return this.querySelectorAll(s)[0] || null; },
            querySelectorAll: function(s) {
                var want = {'[data-testid="tweetText"]': 'tweetText',
                            '[data-testid="User-Name"] a[role="link"]': 'user',
                            'a[href*="/status/"]': 'status'}[s];
                return this.kids.filter(function(k) { return k.attrs.kind === want; });
            }
        };
    }
    function article(text, user, href) {
        return el({}, [el({kind: 'tweetText', text: text}), el({kind: 'user', text: user}),
                       el({kind: 'status', href: href})]);
    }
    var document = {querySelectorAll: function(s) {
        if (s !== 'article[data-testid="tweet"]') throw new Error('selector ' + s);
        return [article('ours', 'Us', '/TheAIShrink/status/1'),
                article('a reply', 'Them', '/them/status/2')];
    }};
    """
    out = json.loads(_node_run(fake.calls[0].js, fake_dom))
    assert out == {"own_tweet": "ours",
                   "replies": [{"user": "Them", "text": "a reply",
                                "url": "https://x.com/them/status/2"}]}


# `_run_js` itself, with osascript faked under it.

def _fake_osascript(monkeypatch, unwalled, run):
    from src.x import safari
    monkeypatch.setattr(safari, "_run_js", unwalled["_run_js"])
    monkeypatch.setattr(safari, "require_active", lambda: None)
    monkeypatch.setattr(safari, "subprocess", SimpleNamespace(
        run=run, SubprocessError=subprocess.SubprocessError,
        TimeoutExpired=subprocess.TimeoutExpired))
    return safari


def _script_reader(seen, outcome):
    def run(argv, **kwargs):
        script = argv[-1]
        seen["script"] = script
        seen["timeout"] = kwargs.get("timeout")
        seen["path"] = script.split('POSIX file "')[1].split('"')[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return run


def test_run_js_activates_safari_only_on_request(monkeypatch, unwalled):
    seen = {}
    ok = SimpleNamespace(returncode=0, stdout="OK\n", stderr="")
    safari = _fake_osascript(monkeypatch, unwalled, _script_reader(seen, ok))

    assert safari._run_js("1", 7) == "OK"
    assert 'to activate' not in seen["script"] and seen["timeout"] == 7
    assert safari._run_js("1", activate=True) == "OK"
    script = seen["script"]
    assert script.index('tell application "Safari" to activate') < script.index("do JavaScript")


def test_run_js_prefixes_its_failure_line(monkeypatch, unwalled):
    from src.x import safari as safari_mod
    lines = []
    monkeypatch.setattr(safari_mod.log, "info", lambda msg, *a, **k: lines.append(msg))
    failed = SimpleNamespace(returncode=1, stdout="", stderr="execution error\n")
    safari = _fake_osascript(monkeypatch, unwalled, _script_reader({}, failed))

    assert safari._run_js("1", log_prefix="[FOLLOWER]") == ""
    assert safari._run_js("1") == ""
    assert lines == ["[FOLLOWER] Page JavaScript failed (osascript exit 1): execution error",
                     "Page JavaScript failed (osascript exit 1): execution error"]


def test_run_js_raises_a_timeout_on_request_and_removes_its_file(monkeypatch, unwalled):
    seen = {}
    timeout = subprocess.TimeoutExpired("osascript", 30)
    safari = _fake_osascript(monkeypatch, unwalled, _script_reader(seen, timeout))

    with pytest.raises(subprocess.TimeoutExpired):
        safari._run_js("1", 30, raise_timeout=True)
    assert not os.path.exists(seen["path"])
    assert safari._run_js("1", 30) == ""
    assert not os.path.exists(seen["path"])


def test_run_js_checks_bedtime_before_osascript(monkeypatch, unwalled):
    from src.x import safari

    def asleep():
        raise OutsideActiveHours("Bot asleep")
    ran = []
    monkeypatch.setattr(safari, "_run_js", unwalled["_run_js"])
    monkeypatch.setattr(safari, "require_active", asleep)
    monkeypatch.setattr(safari.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(OutsideActiveHours):
        safari._run_js("1", activate=True)
    assert ran == []


def test_scrape_text_limit_reaches_the_page_script(monkeypatch, browser):
    from src.x import scraper

    fake = browser("NO_ARTICLES", "NO_ARTICLES")
    monkeypatch.setattr(scraper, "_record_blank_page", lambda **k: None)
    scraper._scrape_tweets_from_page("search 'ai'", 10)
    scraper._scrape_tweets_from_page("search 'ai'", 10, text_limit=600)
    assert "text.substring(0, 200), a: author" in fake.calls[0].js
    assert "text.substring(0, 600), a: author" in fake.calls[1].js
