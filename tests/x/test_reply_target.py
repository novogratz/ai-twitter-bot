"""The final browser check refuses self, comments and already-answered threads."""
import json
import shutil
import subprocess

import pytest

from src.guards import replied_store
from src.guards.active_hours import OutsideActiveHours
from src.guards.reply_admission import Refusal
from src.x import safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome
from tests.helpers import numbered_url

PARENT = numbered_url(800)
TEXT = "Batching is where inference margins are won or lost."


@pytest.mark.parametrize("dry_run", ["0", "1"])
@pytest.mark.parametrize("turn", [False, True])
@pytest.mark.parametrize("handle", ["TheAIShrink", "thesimaximalist", "RuntimeBot"])
def test_all_own_identities_stop_before_browser_or_claim(
        monkeypatch, settings_override, memory_ledger, dry_run, turn, handle):
    settings_override(BOT_HANDLE="RuntimeBot")
    monkeypatch.setenv("DRY_RUN", dry_run)
    refusals = []
    parent = numbered_url(801, handle.upper())
    assert tc.reply_to_tweet(parent, TEXT, debate_turn=turn,
                             on_refused=refusals.append) is WriteOutcome.REFUSED
    assert refusals == [Refusal.OWN_POST]
    assert parent not in replied_store.load_replied()
    assert memory_ledger.rows == []


def test_debate_cannot_bypass_policy_at_the_final_write(memory_ledger):
    refusals = []
    assert tc.reply_to_tweet(PARENT, TEXT, debate_turn=True,
                             on_refused=refusals.append) is WriteOutcome.REFUSED
    assert refusals == [Refusal.CONVERSATION]
    assert not replied_store.load_replied() and not memory_ledger.rows


@pytest.mark.parametrize("answer", ["", "refused", "null", "[]", "{}", '{"url":17}',
                                    json.dumps({"url": numbered_url(800, "other"), "clicked": False}),
                                    json.dumps({"url": numbered_url(801), "clicked": False})])
def test_unreadable_or_misattributed_target_is_refused(monkeypatch, answer):
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: answer)
    assert not tc._reply_target(PARENT)


def test_target_check_propagates_bedtime(monkeypatch):
    def asleep(*a, **k):
        raise OutsideActiveHours("window closed")
    monkeypatch.setattr(safari, "_run_js", asleep)
    with pytest.raises(OutsideActiveHours):
        tc._reply_target(PARENT)


DOM = r"""
const input = JSON.parse(process.argv[1]), clicks = [];
function article(spec) {
  const a = {innerText: spec.text || 'An original SI post'};
  function node(values, quoted=false) {
    return {...values, closest: selector => selector === 'article' ? a : (quoted ? {} : null)};
  }
  const makeLink = (url, quoted=false) => node({
    href: url, pathname: new URL(url).pathname,
    querySelector: selector => selector === 'time' && !spec.noTime ? {} : null
  }, quoted);
  const link = makeLink(spec.url);
  const links = spec.quote ? [makeLink(spec.quote, true), link] : [link];
  const body = node({innerText: a.innerText});
  const button = node({click: () => clicks.push(spec.url)});
  a.querySelectorAll = selector => {
    if (selector === 'a[href]') return links;
    if (selector === '[data-testid="tweetText"]') return [body];
    if (selector === '[data-testid="reply"]') return spec.noButton ? [] : [button];
    return [];
  };
  return a;
}
global.document = {querySelectorAll: () => input.articles.map(article)};
global.location = {pathname: new URL(input.page).pathname};
const answer = eval(input.js);
process.stdout.write(JSON.stringify({answer, clicks}));
"""


def mock_page(monkeypatch, articles, page):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute the browser script fixture")
    clicks = []

    def run(js, timeout_s, **kwargs):
        assert timeout_s == 10 and kwargs["log_prefix"] == "[REPLY]"
        result = subprocess.run([node, "-e", DOM, json.dumps(
            {"js": js, "articles": articles, "page": page})], capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        clicks.extend(output["clicks"])
        return output["answer"]

    monkeypatch.setattr(safari, "_run_js", run)
    return clicks


@pytest.mark.parametrize("articles,page,allowed", [
    ([{"url": PARENT}], PARENT, True),
    ([{"url": PARENT + "?s=20"}], PARENT, True),
    ([{"url": PARENT + "/"}], PARENT + "/", True),
    ([{"url": PARENT, "quote": numbered_url(2, "TheAIShrink")}], PARENT, True),
    ([{"url": numbered_url(800, "other")}], PARENT, False),
    ([{"url": numbered_url(799)}, {"url": PARENT}], PARENT, False),
    ([{"url": PARENT}, {"url": PARENT}], PARENT, False),
    ([{"url": PARENT, "text": "Replying to @someone"}], PARENT, False),
    ([{"url": PARENT, "text": "En réponse à @someone"}], PARENT, False),
    ([{"url": PARENT, "text": "@someone a nested reply"}], PARENT, False),
    ([{"url": PARENT, "noButton": True}], PARENT, False),
    ([{"url": PARENT, "noTime": True}], PARENT, False),
    ([{"url": PARENT}], numbered_url(799), False),
    ([{"url": PARENT}], numbered_url(800, "other"), False),
    ([], PARENT, False),
    ([{"url": PARENT}, {"url": numbered_url(801, "TheAIShrink")}], PARENT, False),
    ([{"url": PARENT}, {"url": numbered_url(801, "thesimaximalist")}], PARENT, False),
])
@pytest.mark.parametrize("click", [False, True])
def test_page_script_targets_only_the_verified_original(monkeypatch, articles, page, allowed, click):
    clicks = mock_page(monkeypatch, articles, page)
    assert tc._reply_target(PARENT, click=click) is allowed
    assert clicks == ([articles[0]["url"]] if allowed and click else [])


def test_nested_target_cannot_reach_parent_like_or_submission(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    for name in ("_activate_or_abort", "_open_or_abort"):
        monkeypatch.setattr(tc, name, lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda *a: pytest.fail("liked an ineligible parent"))
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("submitted to an ineligible parent"))
    clicks = mock_page(monkeypatch, [{"url": numbered_url(799)}, {"url": PARENT}], PARENT)
    assert tc.reply_to_tweet(PARENT, TEXT) is WriteOutcome.REFUSED
    assert not clicks and memory_ledger.rows == []
    assert PARENT not in replied_store.load_replied()


def test_visible_earlier_reply_is_remembered_even_after_it_leaves_the_page(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    for name in ("_activate_or_abort", "_open_or_abort"):
        monkeypatch.setattr(tc, name, lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda *a: pytest.fail("liked an answered parent"))
    articles = [{"url": PARENT}, {"url": numbered_url(801, "thesimaximalist")}]
    clicks = mock_page(monkeypatch, articles, PARENT)
    assert tc.reply_to_tweet(PARENT, TEXT) is WriteOutcome.REFUSED
    assert PARENT in replied_store.load_replied()
    articles.pop()
    assert tc.reply_to_tweet(PARENT, TEXT) is WriteOutcome.REFUSED
    assert not clicks and not memory_ledger.rows
