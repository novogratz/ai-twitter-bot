"""Repost clicks must target one original, never toggle, and confirm before logging."""
import json
import shutil
import subprocess
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.x import twitter_client as tc, safari
from src.guards import repost_policy as policy, action_guard as ag, active_hours
from src.replies import reply_pool
from tests.helpers import fresh_local as fresh
from tests.x.test_likes import _FAKE_DOM_JS, _article


@pytest.fixture
def browser(monkeypatch):
    calls = []
    post = dict(url=fresh("elonmusk", n=1000), text="Grok Imagine video", has_video=True,
                likes=600, reposts=100, is_reply=False, result="not_reposted")
    state = dict(post=post, calls=calls, confirmed=True, fail_confirm=False)
    monkeypatch.setattr(safari, "open_url", lambda url: calls.append("navigate") or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: calls.append("close"))
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    def page(mode, target):
        calls.append(mode)
        if mode == "open":
            return {**state["post"], "result": "opened"}
        if mode == "confirm":
            if state["fail_confirm"]:
                return {}
            if state["confirmed"]:
                state["post"]["result"] = "already_reposted"
            return {**state["post"], "result": "clicked"}
        return dict(state["post"])
    monkeypatch.setattr(tc, "_repost_page", page)
    return state


def test_repost_is_logged_only_after_confirmation_and_never_repeated(browser, memory_ledger):
    url = browser["post"]["url"]
    assert tc.repost_tweet(url) is tc.WriteOutcome.SHIPPED
    assert ag.count_today(ag.RETWEET) == 1
    assert policy.history()[url.rsplit('/', 1)[1]]["state"] == "confirmed"
    before = list(browser["calls"])
    assert tc.repost_tweet(url.replace('/elonmusk/', '/renamed/') + '?s=20') is tc.WriteOutcome.REFUSED
    assert browser["calls"] == before


@pytest.mark.parametrize("fail_confirm", [True, False])
def test_ambiguous_submit_is_reserved_without_a_shipped_ledger_row(browser, memory_ledger, fail_confirm):
    browser.update(confirmed=False, fail_confirm=fail_confirm)
    url = browser["post"]["url"]
    assert tc.repost_tweet(url) is tc.WriteOutcome.UNCONFIRMED
    assert ag.count_today(ag.RETWEET) == 0
    assert policy.pending_count() == 1 and policy.known(url)
    assert tc.repost_tweet(url) is tc.WriteOutcome.REFUSED


def test_existing_native_repost_is_remembered_without_toggling(browser, memory_ledger):
    browser["post"]["result"] = "already_reposted"
    url = browser["post"]["url"]
    assert tc.repost_tweet(url) is tc.WriteOutcome.REFUSED
    assert "open" not in browser["calls"] and "confirm" not in browser["calls"]
    assert ag.count_today(ag.RETWEET) == 0 and policy.known(url)


@pytest.mark.parametrize("changes", [
    {"text": "Bitcoin with Grok"}, {"quoted_text": "crypto"}, {"is_reply": True},
    {"url": "https://x.com/impostor/status/123"}, {"result": "failed"},
])
def test_opened_target_is_verified_before_any_repost_click(browser, changes):
    url = browser["post"]["url"]
    browser["post"].update(changes)
    assert not tc.repost_tweet(url)
    assert "open" not in browser["calls"] and "confirm" not in browser["calls"]
    assert policy.history() == {}


def test_nonpriority_video_needs_matching_review_at_the_chokepoint(browser):
    browser["post"]["url"] = fresh("creator")
    post = browser["post"]
    reply_pool.observe([post], "VIDEO")
    assert tc.repost_tweet(post["url"]) is tc.WriteOutcome.REFUSED
    assert "open" not in browser["calls"]
    policy.save_review(post, True, "Caption describes generated video")
    assert tc.repost_tweet(post["url"]) is tc.WriteOutcome.SHIPPED


def test_two_competing_writers_cannot_spend_the_last_slot_twice(browser, memory_ledger, monkeypatch):
    for n in range(49):
        memory_ledger.append(ag.RETWEET, fresh("old", n=n), False, active_hours.now_local() - timedelta(hours=1))
    urls = [fresh("elonmusk", n=1000), fresh("elonmusk", n=1001)]
    confirmed = set()
    def page(mode, target):
        result = {**browser["post"], "url": f"https://x.com/elonmusk/status/{target}"}
        if mode == "open":
            return {**result, "result": "opened"}
        if mode == "confirm":
            browser["calls"].append("confirm")
            confirmed.add(target)
            return {**result, "result": "clicked"}
        return {**result, "result": "already_reposted" if target in confirmed else "not_reposted"}
    monkeypatch.setattr(tc, "_repost_page", page)
    with ThreadPoolExecutor(2) as executor:
        outcomes = list(executor.map(tc.repost_tweet, urls))
    assert outcomes.count(tc.WriteOutcome.SHIPPED) == 1
    assert ag.count_today(ag.RETWEET) == 50
    assert browser["calls"].count("confirm") == 1


def test_target_changes_while_menu_opens_prevent_submission(browser, monkeypatch):
    original = tc._repost_page
    def page(mode, target):
        result = original(mode, target)
        if mode == "open":
            browser["post"]["text"] = "Bitcoin presale"
        return result
    monkeypatch.setattr(tc, "_repost_page", page)
    assert tc.repost_tweet(browser["post"]["url"]) is tc.WriteOutcome.REFUSED
    assert "confirm" not in browser["calls"] and policy.history() == {}


def test_dry_run_never_opens_or_claims(browser, monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.repost_tweet(browser["post"]["url"]) is tc.WriteOutcome.DRY_RUN
    assert browser["calls"] == [] and policy.history() == {}
    assert ag.count_today(ag.RETWEET) == 0


def run_js(articles, mode, target, menu="retweetConfirm"):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to exercise browser JavaScript")
    snippet = tc._REPOST_JS.replace("__MODE__", mode).replace("__TARGET_ID__", target)
    spec = {"tag": "html", "children": articles + ([{"tag": "button", "attrs": {"id": "confirm", "data-testid": menu}}] if menu else [])}
    program = _FAKE_DOM_JS + "\nEl.prototype.getAttribute = function(k) { return this.attrs[k] || ''; };\n" + f'''
var root = new El({json.dumps(spec)});
Object.defineProperty(El.prototype, 'textContent', {{get: function() {{ return this.attrs['data-caption'] || this.innerText; }}}});
var document = {{querySelectorAll: s => root.querySelectorAll(s), querySelector: s => root.querySelector(s)}};
var location = {{pathname: '/author/status/{target}'}};
var out = eval({json.dumps(snippet)});
console.log(JSON.stringify({{out: JSON.parse(out), clicks}}));
'''
    result = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_native_script_opens_the_target_repost_and_confirms_only_explicit_menu():
    post = _article("https://x.com/author/status/123", "retweet", "parent")
    assert run_js([post], "open", "123")["clicks"] == ["parent-button"]
    assert run_js([post], "confirm", "123")["clicks"] == ["confirm"]
    assert run_js([post], "read", "123")["clicks"] == []


@pytest.mark.parametrize("mode", ["read", "open", "confirm"])
def test_native_script_never_clicks_undo(mode):
    post = _article("https://x.com/author/status/123", "unretweet", "parent")
    result = run_js([post], mode, "123", menu="unretweetConfirm")
    assert result["clicks"] == [] and result["out"]["result"] == "already_reposted"


def test_native_script_does_not_borrow_a_quoted_video_or_caption():
    post = _article("https://x.com/author/status/123", "retweet", "parent", quoted="https://x.com/other/status/456", quoted_first=True)
    quote = post["children"][0]["children"][0]
    quote["children"] += [{"tag": "video"}, {"tag": "div", "attrs": {"data-testid": "tweetText"}, "text": "Seedance video"}]
    post["children"] = [c for c in post["children"] if c.get("attrs", {}).get("data-testid") != "tweetText"]
    result = run_js([post], "read", "123")
    assert result["out"]["has_video"] is False and result["out"]["text"] == ""
    assert run_js([post], "open", "456")["clicks"] == []


def test_native_script_refuses_a_conversation_parent_or_an_undo_menu():
    before = _article("https://x.com/author/status/456", "retweet", "before")
    post = _article("https://x.com/author/status/123", "retweet", "parent")
    assert run_js([before, post], "open", "123")["clicks"] == []
    assert run_js([post], "confirm", "123", menu="unretweetConfirm")["clicks"] == []


def test_native_caption_uses_the_same_text_content_as_discovery():
    post = _article("https://x.com/author/status/123", "retweet", "parent")
    body = next(c for c in post["children"] if c.get("attrs", {}).get("data-testid") == "tweetText")
    body["attrs"]["data-caption"] = "SI video\nGenerated animation workflow"
    assert run_js([post], "read", "123")["out"]["text"] == body["attrs"]["data-caption"]
