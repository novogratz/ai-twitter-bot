"""Only a verified original may receive the conversation's single Reply."""
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
def test_protected_author_is_refused_before_any_browser_work(monkeypatch, memory_ledger, dry_run, turn):
    monkeypatch.setenv("DRY_RUN", dry_run)
    refusals = []
    parent = numbered_url(801, "ElonMusk")
    assert tc.reply_to_tweet(parent, TEXT, debate_turn=turn,
                             on_refused=refusals.append) is WriteOutcome.REFUSED
    assert refusals == [Refusal.PROTECTED_ACCOUNT]
    assert parent not in replied_store.load_replied()
    assert memory_ledger.rows == []


@pytest.mark.parametrize("answer", ["", "refused", "null", "[]", "{}", '{"url":17}',
                                    json.dumps({"url": numbered_url(800, "elonmusk"), "clicked": False}),
                                    json.dumps({"url": numbered_url(801), "clicked": False})])
def test_unreadable_or_misattributed_target_is_refused(monkeypatch, answer):
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: answer)
    assert not tc._standalone_reply_target(PARENT)


def test_target_check_propagates_activity_window_closing(monkeypatch):
    def asleep(*a, **k):
        raise OutsideActiveHours("window closed")
    monkeypatch.setattr(safari, "_run_js", asleep)
    with pytest.raises(OutsideActiveHours):
        tc._standalone_reply_target(PARENT)


DOM = r"""
const input = JSON.parse(process.argv[1]);
const clicks = [];
function article(spec) {
  const a = {innerText: spec.text || 'An original AI post'};
  function node(values, quoted=false) {
    return {...values, closest: selector => selector === 'article' ? a : (quoted ? {} : null)};
  }
  const makeLink = (url, quoted=false) => node({
    href: url, pathname: new URL(url).pathname,
    querySelector: selector => selector === 'time' ? {} : null
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


@pytest.mark.parametrize("articles,page,allowed", [
    ([{"url": PARENT}], PARENT, True),
    ([{"url": PARENT + "?s=20"}], PARENT, True),
    ([{"url": PARENT + "/"}], PARENT + "/", True),
    ([{"url": PARENT, "quote": numbered_url(2, "elonmusk")}], PARENT, True),
    ([{"url": numbered_url(800, "elonmusk")}], PARENT, False),
    ([{"url": numbered_url(799)}, {"url": PARENT}], PARENT, False),
    ([{"url": PARENT, "text": "Replying to @someone"}], PARENT, False),
    ([{"url": PARENT, "text": "En réponse à @someone"}], PARENT, False),
    ([{"url": PARENT, "text": "@someone a nested reply"}], PARENT, False),
    ([{"url": PARENT, "text": "A question for @ElonMusk about inference"}], PARENT, False),
    ([{"url": PARENT, "noButton": True}], PARENT, False),
    ([{"url": PARENT}], numbered_url(799), False),
    ([], PARENT, False),
    ([{"url": PARENT}, {"url": numbered_url(801, "TheAIShrink")}], PARENT, False),
    ([{"url": PARENT}, {"url": numbered_url(801, "thesimaximalist")}], PARENT, False),
])
@pytest.mark.parametrize("click", [False, True])
def test_page_script_targets_only_the_verified_original(monkeypatch, articles, page, allowed, click):
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
    assert tc._standalone_reply_target(PARENT, click=click) is allowed
    assert clicks == ([articles[0]["url"]] if allowed and click else [])
