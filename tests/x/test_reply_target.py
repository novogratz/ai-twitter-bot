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
@pytest.mark.parametrize("host", ["x.com", "twitter.com"])
def test_excluded_author_cannot_receive_any_reply_or_parent_like(monkeypatch, memory_ledger, dry_run, turn, host):
    from dataclasses import replace
    from src.core import account
    profile = replace(account.current(), reply_excluded_handles=("elonmusk",))
    monkeypatch.setattr(account, "current", lambda: profile)
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setattr(tc, "_open_or_abort", lambda *a: pytest.fail("opened excluded Reply target"))
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda *a: pytest.fail("liked via excluded Reply"))
    parent = numbered_url(801, "ElonMusk").replace("x.com", host)
    refusals = []
    assert tc.reply_to_tweet(parent, TEXT, debate_turn=turn,
                            on_refused=refusals.append) is WriteOutcome.REFUSED
    # Legacy non-canonical URLs already refuse before any account can be answered.
    assert refusals == [Refusal.REPLY_EXCLUDED if host == "x.com" else Refusal.NO_AUTHOR]
    assert not replied_store.load_replied() and not memory_ledger.rows


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
const input = JSON.parse(process.argv[1]), clicks = [], expansions = [];
const dialog = {querySelectorAll: selector => selector === 'article' ? articles.filter(a => a.inDialog) : []};
function article(spec) {
  const a = {innerText: spec.text || 'An original SI post', inDialog: !!spec.dialog, closest: () => spec.dialog ? dialog : null};
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
  const quoteBody = node({innerText: spec.quoteText || ''}, true);
  const profile = new URL(spec.profile || '/' + new URL(spec.url).pathname.split('/')[1], 'https://x.com');
  const profileLink = node({href: profile.href, pathname: profile.pathname, querySelector: () => null});
  const badgeLink = spec.badge ? node({href: 'https://x.com/' + spec.badge, pathname: '/' + spec.badge, querySelector: () => null}) : null;
  if (spec.profileInBody) {
    profileLink.closest = selector => selector === 'article' ? a : selector === '[data-testid="tweetText"]' ? body : null;
  }
  const button = node({click: () => clicks.push(spec.url)});
  a.querySelectorAll = selector => {
    if (selector === 'a[href]') return badgeLink ? [...links, profileLink, badgeLink] : [...links, profileLink];
    if (selector === '[data-testid="tweetText"]') return spec.quoteText ? [body, quoteBody] : [body];
    if (selector === '[data-testid="reply"]') return spec.noButton ? [] : [button];
    if (selector === '[data-testid="tweet-text-show-more-link"]') return spec.more ? [node({click: () => expansions.push(spec.url)})] : [];
    if (selector === 'video') return spec.mediaId ? [node({poster: 'https://pbs.twimg.com/ext_tw_video_thumb/'+spec.mediaId+'/pu/img/frame.jpg'})] : [];
    return [];
  };
  return a;
}
const articles = input.articles.map(article);
global.document = {querySelectorAll: selector => selector === 'article' ? articles :
  selector === '[role="dialog"] [data-testid="tweetTextarea_0"]' && articles.some(a => a.inDialog) ?
    Array.from({length: input.editorCount}, () => ({closest: () => dialog})) : []};
global.location = {pathname: new URL(input.page).pathname};
const answer = eval(input.js);
process.stdout.write(JSON.stringify({answer, clicks, expansions}));
"""


def mock_page(monkeypatch, articles, page, *, expansions=None, editor_count=1):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute the browser script fixture")
    clicks = []

    def run(js, timeout_s, **kwargs):
        assert timeout_s == 10 and kwargs["log_prefix"] == "[REPLY]"
        result = subprocess.run([node, "-e", DOM, json.dumps(
            {"js": js, "articles": articles, "page": page() if callable(page) else page,
             "editorCount": editor_count})], capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        clicks.extend(output["clicks"])
        if expansions is not None:
            expansions.extend(output["expansions"])
        for url in output["expansions"]:
            for spec in articles:
                if spec.get("dialog") and spec["url"] == url:
                    spec.update(text=spec.get("expandedText", spec["text"]), more=spec.get("expandedMore", False))
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


@pytest.fixture
def invited(settings_override):
    settings_override(REPLY_INVITED_ONLY=True, REPLY_REVIEW_ONLY=False, MAX_REPLIES_PER_DAY=20)


def invited_source():
    from datetime import timedelta
    from src.core import account
    from src.guards import active_hours
    from src.x import x_urls
    now = active_hours.now_local() - timedelta(hours=1)
    sid = (int(now.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22
    return f"https://x.com/builder/status/{sid}", f"@{account.current().handle} how do I reduce AI model memory use?"


def test_invited_page_checks_outer_text_and_allows_a_direct_standalone_mention(invited, monkeypatch):
    url, text = invited_source()
    clicks = mock_page(monkeypatch, [{"url": url, "text": text}], url)
    assert tc._reply_target(url, expected_text=text, click=True)
    assert clicks == [url]
    clicks = mock_page(monkeypatch, [{"url": url, "text": "An AI demo", "quoteText": text}], url)
    assert not tc._reply_target(url, expected_text=text, click=True)
    assert clicks == []
    clicks = mock_page(monkeypatch, [{"url": url, "text": text + " New question."}], url)
    assert not tc._reply_target(url, expected_text=text, click=True)
    assert clicks == []


def test_final_source_read_ignores_the_composer_copy_of_parent(invited, monkeypatch):
    url, text = invited_source()
    mock_page(monkeypatch, [{"url": url, "text": text}, {"url": url, "text": text, "dialog": True}], url)
    assert tc._reply_target(url, expected_text=text)


@pytest.mark.parametrize("change_before_submit", [False, True])
@pytest.mark.parametrize("public_request", [False, True])
@pytest.mark.parametrize("receipt_visible", [False, True])
def test_invited_write_has_no_parent_like_and_rechecks_source_at_submit(invited, monkeypatch, memory_ledger, settings_override, change_before_submit, public_request, receipt_visible):
    from src.guards import reply_budget
    from src.x import reply_metrics
    url, text = invited_source()
    settings_override(REPLY_PUBLIC_REQUESTS=public_request)
    if public_request:
        text = "How do I reduce AI model memory use?"
    articles = [{"url": url, "text": text}]
    current_page = [url]
    mock_page(monkeypatch, articles, lambda: current_page[0])
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    for name in ("_activate_or_abort", "_open_or_abort"):
        monkeypatch.setattr(tc, name, lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda *a: pytest.fail("parent like was attempted"))
    def paste(*args):
        current_page[0] = "https://x.com/compose/post"
        articles.insert(0, {"url": url, "text": text, "dialog": True, "noTime": True})
        if change_before_submit:
            articles[1]["text"] = "An AI model announcement; no request for help."
        return True
    monkeypatch.setattr(tc, "_paste_or_abort", paste)
    submits = []
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: submits.append(k) or True)
    receipt = numbered_url(804, "thesimaximalist")
    captures = []
    def capture(*a, **k):
        captures.append((a, k))
        return receipt if receipt_visible else ""
    monkeypatch.setattr(reply_metrics, "capture", capture)
    result = tc.reply_to_tweet(url, TEXT, expected_text=text)
    if change_before_submit:
        assert result is WriteOutcome.REFUSED
        assert submits == [] and memory_ledger.rows == []
        assert reply_budget.entries() == {}
        assert url not in replied_store.load_replied()
    elif receipt_visible:
        assert result is WriteOutcome.SHIPPED
        assert len(submits) == 1 and len(memory_ledger.rows) == 1
        assert reply_budget.used_today() == 1
        assert len(captures) == 1
    else:
        assert result is WriteOutcome.UNCONFIRMED
        assert len(submits) == 1 and memory_ledger.rows == []
        assert reply_budget.used_today() == 1
        assert list(reply_budget.entries().values())[0]["status"] == "pending"
        assert url in replied_store.load_replied()
        assert len(captures) == 3
        assert tc.reply_to_tweet(url, TEXT, expected_text=text) is WriteOutcome.REFUSED
        assert len(submits) == 1


def test_final_public_source_cannot_borrow_request_from_quoted_card(invited, monkeypatch, settings_override):
    settings_override(REPLY_PUBLIC_REQUESTS=True)
    url, _ = invited_source()
    text = "My new AI model announcement."
    clicks = mock_page(monkeypatch, [{"url": url, "text": text,
                       "quoteText": "How do I reduce AI model memory use?"}], url)
    assert not tc._reply_target(url, expected_text=text, click=True)
    assert clicks == []


@pytest.mark.parametrize("page", ["https://x.com/compose/post", "https://x.com/compose/tweet"])
@pytest.mark.parametrize("wrong_copy", [False, True])
def test_final_composer_route_requires_exact_source_and_recipient(invited, monkeypatch, page, wrong_copy):
    url, text = invited_source()
    articles = [{"url": url, "text": text, "dialog": True,
                 "profile": "/another_author" if wrong_copy else "/builder"},
                {"url": url, "text": text}]
    clicks = mock_page(monkeypatch, articles, page)
    assert not tc._reply_target(url, expected_text=text)  # no before-click route bypass
    assert tc._reply_target(url, expected_text=text, composing=True) is (not wrong_copy)
    assert clicks == []


@pytest.mark.parametrize("case", ["no_source", "no_composer", "two_copies", "changed_copy", "wrong_route", "only_body_mention"])
def test_final_composer_refuses_missing_ambiguous_or_changed_context(invited, monkeypatch, case):
    url, text = invited_source()
    root = {"url": url, "text": text}
    copy = {"url": url, "text": text, "dialog": True}
    articles = [copy, root]
    page = "https://x.com/compose/post"
    if case == "no_source": articles.remove(root)
    if case == "no_composer": articles.remove(copy)
    if case == "two_copies": articles.insert(0, dict(copy))
    if case == "changed_copy": copy["text"] = "Another AI request"
    if case == "wrong_route": page = numbered_url(805)
    if case == "only_body_mention": copy["profileInBody"] = True
    mock_page(monkeypatch, articles, page)
    assert not tc._reply_target(url, expected_text=text, composing=True)


@pytest.mark.parametrize("tag", ["LIKE", "REPOST", "FOLLOW", "POST", "QUOTE", "SELF-REPOST", "MEME-REPOST"])
@pytest.mark.parametrize("require_like", [False, True])
def test_invited_mode_blocks_other_writes_before_browser_or_rows(invited, settings_override, tag, require_like):
    from src.x import confirmed_write
    settings_override(REPLY_REQUIRE_PARENT_LIKE=require_like)
    def forbidden(*a, **k):
        pytest.fail("non-Reply write reached browser or ledger")
    assert confirmed_write.run(tag, WriteOutcome, would=forbidden, rows=forbidden,
        steps=forbidden, before_lock=(confirmed_write.DRY_RUN_EXIT,)) is WriteOutcome.REFUSED


def test_alternate_reply_caller_without_exact_source_is_refused(invited, memory_ledger):
    url, _ = invited_source()
    assert tc.reply_to_tweet(url, TEXT) is WriteOutcome.REFUSED
    assert not replied_store.load_replied() and not memory_ledger.rows


@pytest.mark.parametrize("case,allowed", [("expanded", True), ("changed", False), ("no_more", False), ("wrong_author", False)])
def test_collapsed_composer_parent_expands_then_requires_exact_full_source(invited, monkeypatch, case, allowed):
    url, question = invited_source()
    preview = question + " The model has many layers and my available device memory is limited."
    full = preview + " I need a smaller KV cache without losing the useful context."
    copy = {"url": url, "text": preview, "dialog": True, "noTime": True,
            "more": case != "no_more", "expandedText": full if case != "changed" else full + " Changed."}
    if case == "wrong_author": copy["profile"] = "/another_author"
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True) is allowed
    assert clicks == []


_NATIVE_MEDIA_LINK = "https://x.com/video_author/status/2124084959459873080/video/1…"


def compact_media_source(*, short=False):
    url, question = invited_source()
    prose = question + " I made a video showing the model and its memory use."
    full = prose + " " + _NATIVE_MEDIA_LINK
    # X replaces the native media link with a glued pic.x link in the compact
    # copy. Expansion restores the original link and whitespace byte for byte.
    compact = ("AI model memory help?" if short else prose) + "https://pic.x.com/example"
    return url, full, {"url": url, "text": compact, "dialog": True, "noTime": True,
                       "more": True, "expandedText": full}


@pytest.mark.parametrize("short", [False, True])
def test_compact_media_link_expands_before_exact_source_admission(invited, monkeypatch, short):
    url, full, copy = compact_media_source(short=short)
    assert not full.startswith(copy["text"])
    if short:
        assert len(copy["text"]) < 80
    expansions = []
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}],
                       "https://x.com/compose/post", expansions=expansions)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True)
    # A complete prose copy whose pic alias renders the same native media is
    # X's rendering variance (2026-11-23); only a truncated copy must expand.
    assert expansions == ([url] if short else [])
    assert clicks == []


@pytest.mark.parametrize("change", ["prose", "link", "unchanged"])
def test_compact_media_expansion_never_replaces_full_equality(invited, monkeypatch, change):
    url, full, copy = compact_media_source(short=True)
    if change == "prose":
        copy["expandedText"] = full.replace("memory use", "latency")
    elif change == "link":
        copy["expandedText"] = full.replace("/video/1", "/video/2")
    else:
        copy["expandedText"] = copy["text"]
        copy["expandedMore"] = True  # A persistent button still gets one attempt.
    expansions = []
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}],
                       "https://x.com/compose/post", expansions=expansions)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert not tc._reply_target(url, expected_text=full, composing=True)
    assert expansions == [url]
    assert clicks == []


@pytest.mark.parametrize("case", ["missing", "changed", "nested", "wrong_author", "wrong_id", "duplicate"])
def test_background_original_is_verified_before_any_composer_expansion(invited, monkeypatch, case):
    url, full, copy = compact_media_source(short=True)
    root = {"url": url, "text": full}
    articles = [copy, root]
    if case == "missing":
        articles.remove(root)
    elif case == "changed":
        root["text"] = full + " Changed after drafting."
    elif case == "nested":
        articles.insert(1, {"url": numbered_url(805, "thread_root"), "text": "An earlier AI original."})
    elif case == "wrong_author":
        root["url"] = url.replace("/builder/", "/another_author/")
    elif case == "wrong_id":
        root["url"] = numbered_url(805, "builder")
    elif case == "duplicate":
        articles.append(dict(root))
    expansions = []
    clicks = mock_page(monkeypatch, articles, "https://x.com/compose/post", expansions=expansions)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert not tc._reply_target(url, expected_text=full, composing=True)
    assert expansions == clicks == []


@pytest.mark.parametrize("case", ["no_more", "wrong_author", "body_only_author", "multiple_copies", "multiple_editors"])
def test_compact_copy_must_identify_one_parent_before_expansion(invited, monkeypatch, case):
    url, full, copy = compact_media_source(short=True)
    articles = [copy, {"url": url, "text": full}]
    if case == "no_more":
        copy["more"] = False
    elif case == "wrong_author":
        copy["profile"] = "/another_author"
    elif case == "body_only_author":
        copy["profileInBody"] = True
    elif case == "multiple_copies":
        articles.insert(1, dict(copy))
    expansions = []
    clicks = mock_page(monkeypatch, articles, "https://x.com/compose/post", expansions=expansions,
                       editor_count=2 if case == "multiple_editors" else 1)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert not tc._reply_target(url, expected_text=full, composing=True)
    assert expansions == clicks == []


def test_background_source_is_rechecked_after_compact_copy_expansion(invited, monkeypatch):
    url, full, copy = compact_media_source(short=True)
    root = {"url": url, "text": full}
    expansions = []
    clicks = mock_page(monkeypatch, [copy, root], "https://x.com/compose/post", expansions=expansions)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: root.update(text=full + " Changed during expansion."))
    assert not tc._reply_target(url, expected_text=full, composing=True)
    assert expansions == [url]
    assert clicks == []


def compact_quote_alias_copy(appended, *, more=False):
    url, question = invited_source()
    full = question + " I compared the quoted model memory numbers against my own runs."
    return url, full, {"url": url, "text": full + appended, "dialog": True,
                       "noTime": True, "more": more}


@pytest.mark.parametrize("appended", [
    " x.com/GiorgioPatrini…",                      # quote alias truncated inside the handle (2026-11-21)
    " x.com/swarogan/statu…",                      # quote alias truncated at the path
    " x.com/swarogan/status/2124312080282997005",  # complete appended status link
    "https://pic.x.com/example",                   # glued media alias without a Show more control
    " pic.x.com/abc12 x.com/swarogan/statu…",      # media and quote aliases together
])
def test_compact_copy_trailing_link_aliases_never_block_exact_source(invited, monkeypatch, appended):
    url, full, copy = compact_quote_alias_copy(appended)
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True)
    assert clicks == []


@pytest.mark.parametrize("appended", [
    " and one more thought",            # ordinary prose is never stripped
    " x.com/GiorgioPatrini… yet more",  # an alias form away from the end
    "x.com/swarogan/statu",             # neither ellipsis-truncated nor a status id: not X's alias
])
def test_compact_copy_extra_text_beyond_link_aliases_still_refuses(invited, monkeypatch, appended):
    url, full, copy = compact_quote_alias_copy(appended)
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert not tc._reply_target(url, expected_text=full, composing=True)
    assert clicks == []


def test_truncated_compact_copy_with_quote_alias_expands_then_passes(invited, monkeypatch):
    url, full, copy = compact_quote_alias_copy(" x.com/swarogan/statu…", more=True)
    copy["expandedText"] = copy["text"]
    copy["text"] = full[:40] + "… x.com/swarogan/statu…"
    expansions = []
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}],
                       "https://x.com/compose/post", expansions=expansions)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True)
    assert expansions == [url]
    assert clicks == []


@pytest.mark.parametrize("suffix,allowed", [
    # The dialog copy renders a mid-text mention inline; the scraped source
    # wrapped it in newlines. Removing whitespace admits identical characters only.
    (" (@impetusgrants has details) on model runs.", True),
    (" (@impetusgrants has details) on model costs.", False),
])
def test_mention_whitespace_rendering_never_blocks_exact_source(invited, monkeypatch, suffix, allowed):
    url, question = invited_source()
    expected = question + " (\n@impetusgrants\n has details) on model runs."
    copy = {"url": url, "text": question + suffix, "dialog": True, "noTime": True, "more": False}
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": expected}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=expected, composing=True) is allowed
    assert clicks == []


@pytest.mark.parametrize("appended,allowed", [
    ("https://github.com/gitify-app/gitify", True),   # glued full link-card URL (2026-11-21)
    (" github.com/gitify-app/git…", True),            # display-truncated link text
    (" https://github.com/gitify-app/gitify and more", False),  # prose beyond the link
])
def test_trailing_link_card_text_in_copy_never_blocks_exact_source(invited, monkeypatch, appended, allowed):
    url, question = invited_source()
    full = question + " The project link is here 👇"
    copy = {"url": url, "text": full + appended, "dialog": True, "noTime": True, "more": False}
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True) is allowed
    assert clicks == []


@pytest.mark.parametrize("missing,allowed", [
    (" https://llmstxt.org", True),      # scrape kept a trailing link the dialog drops (2026-11-22)
    (" from your homepage!", False),     # missing prose is never excused
])
def test_trailing_link_in_scrape_missing_from_copy_never_blocks_exact_source(invited, monkeypatch, missing, allowed):
    url, question = invited_source()
    full = question + " Serve it from your homepage!" + missing
    copy = {"url": url, "text": full[:-len(missing)], "dialog": True, "noTime": True, "more": False}
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True) is allowed
    assert clicks == []


@pytest.mark.parametrize("copy_extra,allowed", [
    ("https://pic.x.com/uAKimFHBsY", True),   # copy adds a media alias after the shared link (2026-11-22)
    (" extra prose after", False),            # prose beyond the shared link is never excused
])
def test_shared_trailing_link_plus_copy_alias_never_blocks_exact_source(invited, monkeypatch, copy_extra, allowed):
    url, question = invited_source()
    full = question + " Full set here vk.com/wall-10164239992709527…"
    copy = {"url": url, "text": full + copy_extra, "dialog": True, "noTime": True, "more": False}
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True) is allowed
    assert clicks == []


def test_opaque_pic_alias_matches_native_video_permalink_tail(invited, monkeypatch):
    # @google quoting a creator's video: the scrape ends with the native video
    # permalink, the dialog copy with its opaque pic.x.com alias (2026-11-23).
    url, question = invited_source()
    full = question + " Great showcase here " + _NATIVE_MEDIA_LINK
    copy = {"url": url, "text": question + " Great showcase here https://pic.x.com/JfZiLtiBGR",
            "dialog": True, "noTime": True, "more": False}
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True)
    assert clicks == []


@pytest.mark.parametrize("spec,allowed", [
    ({"badge": "partner_org"}, True),          # affiliation badge beside the author (2026-11-23)
    ({"profile": "/another_author"}, False),   # the author's own link stays required
])
def test_affiliation_badge_never_misattributes_the_copy_author(invited, monkeypatch, spec, allowed):
    url, question = invited_source()
    full = question + " Full breakdown of the model memory budget."
    copy = {"url": url, "text": full, "dialog": True, "noTime": True, "more": False, **spec}
    clicks = mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert tc._reply_target(url, expected_text=full, composing=True) is allowed
    assert clicks == []


def test_missing_composer_parent_is_skipped_for_a_day(invited, monkeypatch, memory_ledger):
    from src.x import x_urls
    monkeypatch.setattr(tc, "_no_composer", {})
    url, question = invited_source()
    full = question + " Full breakdown of the model memory budget."
    copy = {"url": url, "text": full, "dialog": True, "noTime": True, "more": False}
    mock_page(monkeypatch, [copy, {"url": url, "text": full}], "https://x.com/compose/post", editor_count=0)
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)
    assert not tc._reply_target(url, expected_text=full, composing=True)
    sid = x_urls.status_id(url)
    assert sid in tc._no_composer
    # The next attempt refuses at admission, before any page opens or claim.
    monkeypatch.setattr(tc, "_open_or_abort", lambda *a, **k: pytest.fail("opened a skipped parent"))
    assert tc.reply_to_tweet(url, TEXT, expected_text=full) is WriteOutcome.REFUSED
    assert not replied_store.load_replied()
    # An expired hold re-admits the parent (the open attempt then runs).
    tc._no_composer[sid] -= tc._NO_COMPOSER_TTL_SECONDS + 1
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(tc, "_open_or_abort", lambda *a, **k: False)
    assert tc.reply_to_tweet(url, TEXT, expected_text=full) is WriteOutcome.FAILED
