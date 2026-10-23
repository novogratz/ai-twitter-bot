"""A repost uses its own original's controls and never undoes a prior repost."""
import json
import shutil
import subprocess

import pytest

from src.guards import action_guard as ag, repost_store
from src.x import repost_page, safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome as W

URL = "https://x.com/elonmusk/status/2063500000000000101"
TEXT = "SI tools need useful tests before we trust them with difficult work."


@pytest.fixture
def browser(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    state = dict(modes=[], opens=[], closes=[], ready=True, reposted=False, sticks=True,
                 confirm="submitted", opened=True, page=True, content=TEXT)
    monkeypatch.setattr(safari, "open_url", lambda url: state["opens"].append(url) or state["opened"])
    monkeypatch.setattr(safari, "close_front_tab", lambda: state["closes"].append(True))
    def page(url, mode="read"):
        state["modes"].append(mode)
        if not state["page"]:
            return {}
        data = dict(url=url, text=state["content"], state="reposted" if state["reposted"] else "ready")
        if mode == "open":
            data["state"] = "menu_opened" if state["ready"] else "unavailable"
        elif mode == "confirm":
            if isinstance(state["confirm"], BaseException):
                raise state["confirm"]
            data["state"] = state["confirm"]
            state["reposted"] = state["sticks"]
        return data
    monkeypatch.setattr(repost_page, "read", page)
    return state


def test_repost_ships_once_records_once_and_keeps_claim(browser, memory_ledger):
    assert tc.repost_tweet(URL) is W.SHIPPED
    assert browser["modes"] == ["read", "open", "confirm", "read"]
    assert [row["action"] for row in memory_ledger.rows] == [ag.RETWEET]
    assert repost_store.contains(URL) and repost_store.pending_today() == 0
    assert tc.repost_tweet(URL) is W.REFUSED
    assert len(browser["opens"]) == 1 and browser["closes"] == [True]


def test_existing_repost_is_remembered_and_never_toggled(browser, memory_ledger):
    browser["reposted"] = True
    assert tc.repost_tweet(URL) is W.REFUSED
    assert browser["modes"] == ["read"] and not memory_ledger.rows
    assert repost_store.contains(URL) and repost_store.pending_today() == 0


def test_stop_after_confirmed_like_does_not_hide_the_outcome(browser, monkeypatch):
    from src.guards.active_hours import OutsideActiveHours
    monkeypatch.setattr(tc, "like_tweet", lambda url: tc.LikeOutcome.LIKED)
    def stopped():
        raise OutsideActiveHours("stop after shipping")
    monkeypatch.setattr(safari, "close_front_tab", stopped)
    assert tc.like_priority_post(URL) is tc.LikeOutcome.LIKED


@pytest.mark.parametrize("failure", ["open", "menu", "target"])
def test_proven_pre_submit_failures_release_claim(browser, memory_ledger, failure):
    browser[{"open": "opened", "menu": "ready", "target": "page"}[failure]] = False
    assert not tc.repost_tweet(URL)
    assert not repost_store.contains(URL) and not memory_ledger.rows
    assert "confirm" not in browser["modes"]


@pytest.mark.parametrize("case", ["no_confirmation", "lost_response", "exception"])
def test_uncertain_submission_stays_claimed_and_counts_after_retry(browser, memory_ledger, case):
    if case == "no_confirmation":
        browser["sticks"] = False
    elif case == "lost_response":
        browser["confirm"] = ""
    else:
        browser["confirm"] = RuntimeError("connection lost")
    if case == "exception":
        with pytest.raises(RuntimeError):
            tc.repost_tweet(URL)
    else:
        assert tc.repost_tweet(URL) is W.UNCONFIRMED
    assert repost_store.pending_today() == 1 and not memory_ledger.rows
    assert tc.repost_tweet(URL) is W.REFUSED
    assert browser["modes"].count("confirm") == 1


def test_repost_dry_run_has_no_claim_or_browser(browser, monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.repost_tweet(URL) is W.DRY_RUN
    assert browser["opens"] == [] and not repost_store.contains(URL)
    assert len(memory_ledger.rows) == 1 and memory_ledger.rows[0]["dry_run"]


def test_repost_refuses_source_content_before_clicking(browser, memory_ledger):
    browser["content"] = "Bonjour, cette nouvelle technologie est vraiment très intéressante."
    assert tc.repost_tweet(URL) is W.REFUSED
    assert browser["modes"] == ["read"] and not memory_ledger.rows


def test_like_priority_post_verifies_target_and_uses_like_chokepoint(browser, monkeypatch):
    calls = []
    monkeypatch.setattr(tc, "like_tweet", lambda url: calls.append(url) or tc.LikeOutcome.LIKED)
    assert tc.like_priority_post(URL) is tc.LikeOutcome.LIKED
    assert browser["modes"] == ["read"] and calls == [URL]
    browser["page"] = False
    assert tc.like_priority_post(URL) is tc.LikeOutcome.REFUSED
    assert calls == [URL]


def test_like_cap_is_enforced_at_the_shared_chokepoint(browser, settings_override):
    settings_override(LIKE_BOT_DAILY_CAP=1)
    ag.record(ag.LIKE, "https://x.com/other/status/1")
    assert tc.like_tweet(URL) is tc.LikeOutcome.REFUSED
    assert tc.like_priority_post(URL) is tc.LikeOutcome.REFUSED
    assert browser["opens"] == []


def _page_js(mode, *, author="elonmusk", page_author="elonmusk", nested=False,
             reposted=False, quote=False, menu=True, undo_menu=False):
    options = dict(mode=mode, author=author, page_author=page_author, nested=nested,
                   reposted=reposted, quote=quote, menu=menu, undo_menu=undo_menu)
    setup = r"""
      const opt = __OPTIONS__, counts = {open: 0, confirm: 0, undo: 0};
      const location = {hostname: 'x.com', pathname: '/' + opt.page_author + '/status/2063500000000000101'};
      const article = {innerText: 'SI tools need useful tests.'};
      const element = (extra, quoted=false) => Object.assign({
        closest: sel => sel === 'article' ? article : quoted ? {} : null,
        getAttribute: () => null, getClientRects: () => [1]
      }, extra);
      const link = element({pathname: '/' + opt.author + '/status/2063500000000000101',
        href: 'https://x.com/' + opt.author + '/status/2063500000000000101',
        querySelector: () => ({})});
      const button = element({click: () => counts.open++}, opt.quote);
      const undo = element({click: () => counts.undo++});
      const confirm = element({click: () => counts.confirm++});
      article.querySelectorAll = sel => ({
        'a[href]': [link], '[data-testid="tweetText"]': [element({innerText: article.innerText})],
        '[data-testid="retweet"]': opt.reposted ? [] : [button],
        '[data-testid="unretweet"]': opt.reposted ? [undo] : []
      }[sel] || []);
      const parent = {querySelectorAll: () => [], innerText: ''};
      const document = {
        querySelectorAll: sel => sel === 'article' ? (opt.nested ? [parent, article] : [article]) :
          sel === '[data-testid="retweetConfirm"]' && opt.menu ? [confirm] : [],
        querySelector: sel => sel.includes('unretweetConfirm') && opt.undo_menu ? {} : null
      };
    """.replace("__OPTIONS__", json.dumps(options))
    script = repost_page.SCRIPT.replace("__ID__", '"2063500000000000101"')
    script = script.replace("__AUTHOR__", '"elonmusk"').replace("__SELF__", '["ownbot"]')
    script = script.replace("__MODE__", json.dumps(mode))
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to exercise page JavaScript")
    result = subprocess.run([node, "-e", setup + "\nconst result = " + script +
                             "; console.log(JSON.stringify({page: JSON.parse(result), counts}));"],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["read", "open", "confirm"])
@pytest.mark.parametrize("wrong", [{"author": "other"}, {"page_author": "other"},
                                   {"nested": True}, {"quote": True}, {"reposted": True}])
def test_page_never_clicks_wrong_nested_quoted_or_existing_repost(mode, wrong):
    result = _page_js(mode, **wrong)
    assert result["counts"] == {"open": 0, "confirm": 0, "undo": 0}


def test_page_clicks_only_verified_repost_and_confirmation_controls():
    opened = _page_js("open")
    assert opened["page"]["state"] == "menu_opened"
    assert opened["counts"] == {"open": 1, "confirm": 0, "undo": 0}
    confirmed = _page_js("confirm")
    assert confirmed["page"]["state"] == "submitted"
    assert confirmed["counts"] == {"open": 0, "confirm": 1, "undo": 0}
    assert _page_js("confirm", menu=False)["counts"]["confirm"] == 0
    assert _page_js("confirm", undo_menu=True)["counts"]["confirm"] == 0
