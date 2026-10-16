"""Only a verified original may receive the conversation's single Reply."""
import json
import shutil
import subprocess

import pytest

# The ranked live Account is covered in test_reply_selection; these pin generic engine behavior.
pytestmark = pytest.mark.usefixtures("unranked_account")

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
                                    json.dumps({"url": numbered_url(800, "elonmusk"), "likes": 3, "clicked": False}),
                                    json.dumps({"url": numbered_url(801), "likes": 3, "clicked": False})])
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
  const a = {innerText: spec.text || 'An original AI post', innerHTML: ''};
  function node(values, quoted=false) {
    return {...values, closest: selector => selector === 'article' ? a : (quoted ? {} : null)};
  }
  const makeLink = (url, quoted=false) => node({
    href: url, pathname: new URL(url).pathname,
    getAttribute: name => name === 'href' ? new URL(url).pathname : null,
    querySelector: selector => selector === 'time' ? {} : null
  }, quoted);
  const link = makeLink(spec.url);
  const links = spec.quote ? [makeLink(spec.quote, true), link] : [link];
  const body = node({innerText: a.innerText});
  const button = node({click: () => clicks.push(spec.url), getAttribute: () => ''});
  const metric = (value, quoted=false) => value === null ? [] : [node({
    innerText: typeof value === 'object' ? value.text || '' : '',
    getAttribute: () => typeof value === 'object' ? value.label || '' : String(value) + ' Likes. Like'
  }, quoted)];
  a.querySelectorAll = selector => {
    if (selector === 'a[href]' || selector === 'a[href*="/status/"]') return links;
    if (selector === '[data-testid="tweetText"]') return [body];
    if (selector === '[data-testid="reply"]') return spec.noButton ? [] : [button];
    if (selector === '[data-testid="like"], [data-testid="unlike"]')
      return [...metric(spec.likes === undefined ? 3 : spec.likes), ...metric(spec.quoteLikes ?? null, true)];
    return [];
  };
  a.querySelector = selector => a.querySelectorAll(selector)[0] || null;
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
    clicks = mock_page(monkeypatch, articles, page)
    assert tc._standalone_reply_target(PARENT, click=click) is allowed
    assert clicks == ([articles[0]["url"]] if allowed and click else [])


@pytest.mark.parametrize("likes,allowed", [
    (0, False), (1, False), (2, False), (3, True), (100, True), (None, False),
    ("1.2K", True), ("1,234", True), ("1\u202f234", True),
    ({"label": "Unlike", "text": "2"}, False),
    ({"label": "Unlike", "text": "3"}, True),
    ({"label": "2 Likes. Unlike", "text": "3"}, False),
    ("unknown", False), ("1,2", False), ("1.5", False), ("-2", False),
])
@pytest.mark.parametrize("click", [False, True])
def test_actual_parent_needs_three_likes_before_any_reply_click(monkeypatch, likes, allowed, click):
    clicks = mock_page(monkeypatch, [
        {"url": PARENT, "likes": likes, "quoteLikes": "999K"},
        {"url": numbered_url(802, "another"), "likes": "999K"},
    ], PARENT)
    assert tc._standalone_reply_target(PARENT, click=click) is allowed
    assert clicks == ([PARENT] if allowed and click else [])


@pytest.mark.parametrize("likes", [0, 1, 2, None])
def test_low_like_parent_never_reaches_a_like_or_submission(monkeypatch, memory_ledger, likes):
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    for name in ("_activate_or_abort", "_open_or_abort"):
        monkeypatch.setattr(tc, name, lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: pytest.fail("liked an ineligible parent"))
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("submitted to an ineligible parent"))
    clicks = mock_page(monkeypatch, [{"url": PARENT, "likes": likes}], PARENT)
    assert tc.reply_to_tweet(PARENT, TEXT) is WriteOutcome.REFUSED
    assert not clicks and memory_ledger.rows == []
    assert PARENT not in replied_store.load_replied()


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


@pytest.mark.parametrize("parent,changed,allowed", [
    ("SI inference depends on memory bandwidth.", "SI inference depends on memory bandwidth.", True),
    ("SI inference depends on memory bandwidth.", "SI inference\n depends on memory bandwidth.", True),
    ("SI inference depends on memory bandwidth.", "SI inference costs fell 90% today.", False),
    ("SI inference depends on memory bandwidth.", "A different unrelated claim", False),
    ("SI inference. " * 25, "SI inference. " * 25, True),
    ("SI inference. " * 25, "SI inference. " * 25 + "But the claim changed.", False),
    ("SI " + "x" * 3996 + "🙂", "SI " + "x" * 3996 + "🙂 More visible text", True),
    ("SI " + "x" * 3996 + "🙂", "SI " + "x" * 3996 + "😄 More visible text", False),
])
def test_ranked_parent_must_match_reviewed_text_before_click(unranked_account, monkeypatch, parent, changed, allowed):
    from dataclasses import replace
    from src.core import account, reply_queue
    from src.guards import active_hours
    from src.replies.reply_pipeline import Candidate
    from src.replies.reply_generator import Generation, Outcome
    now = active_hours.now_local()
    monkeypatch.setattr(active_hours, "now_local", lambda: now)
    profile = account.current()
    monkeypatch.setattr(account, "current", lambda: replace(
        profile, replies=replace(profile.replies, ranked_selection=True)))
    sid = reply_queue.reserve(Candidate(PARENT, parent, "TEST"))
    reply_queue.prepared(sid, TEXT, Generation(Outcome.WRITTEN, "en", TEXT), "OTHER")
    row = reply_queue.ready()[sid]
    reply_queue.reviewed({sid: row}, {sid: {
        "impact": 5, "sharpness": 5, "interest": 5, "grounded": True, "on_topic": True, "positive": True,
        "support": "Parent describes memory bandwidth.", "reason": "Useful detail.",
        "reviewed_at": active_hours.now_local().isoformat(),
    }})
    assert reply_queue.select(sid, reply_queue.ready()[sid])
    clicks = mock_page(monkeypatch, [{"url": PARENT, "text": changed}], PARENT)
    assert tc._standalone_reply_target(PARENT, click=True) is allowed
    assert clicks == ([PARENT] if allowed else [])
