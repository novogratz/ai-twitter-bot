"""A like is one click on the "like" button of an identified post, never
the toggling 'l' shortcut (issue #121)."""
import inspect
import json
import shutil
import subprocess

import pytest

POST = "https://x.com/thebtctherapist/status/2063500000000000101"
NEXT = "https://x.com/thebtctherapist/status/2063500000000000102"
REPOST = "https://x.com/someoneelse/status/2063500000000000103"
OWN = "https://x.com/TheAIShrink/status/2063500000000000104"
REPLY = "https://x.com/engager/status/2063500000000000105"
BLOCKED = "https://x.com/BlockedOne/status/2063500000000000107"


class FakePage:
    """Answers `_page_posts` like `_POSTS_JS` would on a page of posts."""

    def __init__(self, page="https://x.com/thebtctherapist", posts=()):
        self.page = page
        self.posts = [dict(p) for p in posts]
        self.clicks = []
        self.click_sticks = True

    def _find(self, target_id):
        from src.x import x_urls
        return next((p for p in self.posts if target_id and x_urls.status_id(p["url"]) == target_id), None)

    def __call__(self, mode, target_id=""):
        if mode == "list":
            return {"page": self.page, "posts": [p["url"] for p in self.posts]}
        post = self._find(target_id)
        if post is None:
            return {"url": "", "result": "failed"}
        if post["liked"]:
            return {"url": post["url"], "result": "already_liked"}
        if mode != "press":
            return {"url": post["url"], "result": "not_liked"}
        self.clicks.append(post["url"])
        post["liked"] = self.click_sticks
        return {"url": post["url"], "result": "clicked"}


@pytest.fixture
def browser(monkeypatch, tmp_path):
    """Live write path on a scripted page; ledger rows and tab closes recorded."""
    from src.guards import action_guard
    from src.x import safari, twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc, "_liked_cache_path", lambda: str(tmp_path / "liked_tweets.json"))
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(safari, "_navigate_to_first_tweet", lambda: None)
    state = {"page": FakePage(), "recorded": [], "closed": 0}
    monkeypatch.setattr(tc, "_page_posts", lambda *a: state["page"](*a))
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: state["recorded"].append((a, k)))

    def close_front_tab():
        state["closed"] += 1
    monkeypatch.setattr(safari, "close_front_tab", close_front_tab)
    return state


def test_no_like_path_presses_the_l_shortcut():
    from src.x import safari, scraper, twitter_client as tc
    for module in (safari, scraper, tc):
        assert 'keystroke "l"' not in inspect.getsource(module)


def test_already_liked_post_is_never_clicked(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": True}])
    assert tc.like_tweet(POST) is tc.LikeOutcome.ALREADY_LIKED
    assert page.clicks == [] and browser["recorded"] == []


def test_cached_like_is_never_clicked_even_if_the_page_says_not_liked(browser):
    from src.x import twitter_client as tc

    tc._mark_liked(POST)
    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": False}])
    assert tc.like_tweet(POST) is tc.LikeOutcome.ALREADY_LIKED
    assert page.clicks == []


def test_like_clicks_the_identified_post_once_and_records_the_read_url(browser):
    from src.guards import action_guard
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": False}])
    outcome = tc.like_tweet(POST)
    assert outcome is tc.LikeOutcome.LIKED and outcome
    assert page.clicks == [POST]
    assert browser["recorded"] == [((action_guard.LIKE,), {"target": POST})]
    assert tc._already_liked(POST)


def test_like_clicks_the_given_post_not_another(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(
        posts=[{"url": POST, "liked": False}, {"url": NEXT, "liked": False}])
    assert tc.like_tweet(NEXT) is tc.LikeOutcome.LIKED
    assert page.clicks == [NEXT]


def test_unconfirmed_click_is_not_a_like(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": False}])
    page.click_sticks = False
    outcome = tc.like_tweet(POST)
    assert outcome is tc.LikeOutcome.FAILED and not outcome
    assert browser["recorded"] == []
    assert not tc._already_liked(POST)


@pytest.mark.parametrize("page_url, url", [
    (POST, ""),                                 # no URL: the open status page is not a target
    (POST, NEXT),                               # requested post not on the page
    (POST, "https://x.com/thebtctherapist"),    # URL without a status ID
])
def test_nothing_clicked_when_the_post_is_not_identified(browser, page_url, url):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page=page_url, posts=[{"url": POST, "liked": False}])
    outcome = tc.like_tweet(url)
    assert outcome is tc.LikeOutcome.FAILED and not outcome
    assert page.clicks == [] and browser["recorded"] == []


def test_dry_run_like_returns_dry_run_recorded_and_reads_nothing(browser, monkeypatch):
    """Log only what shipped: a dry-run like writes a dry-run ledger row and
    returns the falsy DRY_RUN_RECORDED, like every other chokepoint."""
    from src.guards import action_guard
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(tc, "_page_posts", lambda *a: pytest.fail("read the page"))
    assert tc.like_tweet(POST) is tc.DRY_RUN_RECORDED
    assert browser["recorded"] == [((action_guard.LIKE,), {"target": POST, "dry_run": True})]


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_blocked_account_post_is_never_liked(browser, monkeypatch, dry_run):
    """CONTEXT.md: a Blocked account is barred from any interaction. The
    handle comes from the URL and is matched as Reply admission matches it
    (case, underscores ignored); nothing is read, clicked or recorded, not
    even a dry-run row."""
    from src.core import config
    from src.x import twitter_client as tc

    monkeypatch.setattr(config, "BLOCKLIST", {"blockedone"})
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setattr(tc, "_page_posts", lambda *a: pytest.fail("read the page"))
    for url in (BLOCKED, "https://x.com/Blocked_One_FR/status/2063500000000000108"):
        outcome = tc.like_tweet(url)
        assert outcome is tc.LikeOutcome.BLOCKED and not outcome
        assert not tc._already_liked(url)
    assert browser["recorded"] == []


def test_blocked_reply_is_skipped_and_the_walk_goes_on(browser, monkeypatch):
    from src.core import config
    from src.x import twitter_client as tc

    monkeypatch.setattr(config, "BLOCKLIST", {"blockedone"})
    monkeypatch.setenv("NOTIFY_LIKE_REPLIES_COUNT", "3")
    page = browser["page"] = FakePage(page=OWN, posts=[
        {"url": BLOCKED, "liked": False},
        {"url": REPLY, "liked": False},
    ])
    assert tc.like_own_tweet_replies() == [tc.LikeOutcome.BLOCKED, tc.LikeOutcome.LIKED]
    assert page.clicks == [REPLY]


def test_profile_visit_likes_their_own_posts_and_reports_each(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(posts=[
        {"url": REPOST, "liked": False},    # a repost of someone else
        {"url": POST, "liked": True},
        {"url": NEXT, "liked": False},
    ])
    outcomes = tc.visit_profile_and_like("TheBTCTherapist", like_count=2)
    assert outcomes == [tc.LikeOutcome.ALREADY_LIKED, tc.LikeOutcome.LIKED]
    assert page.clicks == [NEXT]
    assert browser["closed"] == 1


@pytest.mark.parametrize("dry_run, like_count", [("0", 0), ("1", 2)])
def test_profile_visit_opens_nothing_for_zero_likes_or_dry_run(monkeypatch, dry_run, like_count):
    from src.x import twitter_client as tc

    # conftest fails the test on any webbrowser.open or _run_applescript.
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setattr(tc, "_page_posts", lambda *a: pytest.fail("read the page"))
    assert tc.visit_profile_and_like("TheBTCTherapist", like_count=like_count) == []


def test_notify_likes_replies_but_never_our_own_posts(browser, monkeypatch):
    from src.x import twitter_client as tc

    monkeypatch.setenv("NOTIFY_LIKE_REPLIES_COUNT", "3")
    page = browser["page"] = FakePage(page=OWN, posts=[
        {"url": OWN, "liked": False},       # our post the replies answer
        {"url": REPLY, "liked": False},
        {"url": OWN.replace("104", "106"), "liked": False},  # our reply in the thread
    ])
    assert tc.like_own_tweet_replies() == [tc.LikeOutcome.LIKED]
    assert page.clicks == [REPLY]
    assert browser["closed"] == 1


def test_notify_clicks_nothing_off_our_own_status_page(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page="https://x.com/TheAIShrink", posts=[
        {"url": REPOST, "liked": False},
    ])
    assert tc.like_own_tweet_replies() == [tc.LikeOutcome.FAILED]
    assert page.clicks == []


def test_tab_closes_when_the_walk_is_interrupted(browser, monkeypatch):
    from src.guards import action_guard
    from src.x import twitter_client as tc
    from src.core.state_errors import StateUnreadable

    def unreadable(*a, **k):
        raise StateUnreadable("ledger unreadable")
    monkeypatch.setattr(action_guard, "record", unreadable)
    browser["page"] = FakePage(posts=[{"url": POST, "liked": False}])
    with pytest.raises(StateUnreadable):
        tc.visit_profile_and_like("TheBTCTherapist", like_count=1)
    browser["page"] = FakePage(page=OWN, posts=[{"url": REPLY, "liked": False}])
    with pytest.raises(StateUnreadable):
        tc.like_own_tweet_replies()
    assert browser["closed"] == 2


def test_engager_likes_count_only_likes_that_shipped(monkeypatch):
    from src.replies import notify_bot as nb
    LikeOutcome = nb.LikeOutcome

    results = {"liker": [LikeOutcome.LIKED, LikeOutcome.ALREADY_LIKED],
               "stale": [LikeOutcome.ALREADY_LIKED], "broken": [LikeOutcome.FAILED]}
    monkeypatch.setattr(nb, "visit_profile_and_like", lambda h, **k: results[h])
    monkeypatch.setattr(nb.random, "random", lambda: 0.0)
    lines = []
    monkeypatch.setattr(nb.log, "info", lambda msg, *a, **k: lines.append(msg))
    replies = [{"user": f"@{h}", "url": f"https://x.com/{h}/status/1"} for h in results]
    nb._reciprocate_engagers(replies, set())
    assert "[RECIPROCATE] Engaged back with 1 engager(s): 1 like(s)." in lines
    assert "[RECIPROCATE] Nothing liked on @stale." in lines
    assert "[RECIPROCATE] Nothing liked on @broken." in lines


def test_page_posts_fills_the_mode_and_target_and_parses_json(monkeypatch):
    from src.x import twitter_client as tc

    seen = []

    def run_page_js(js):
        seen.append(js)
        return json.dumps({"url": POST, "result": "clicked"})
    monkeypatch.setattr(tc, "_run_page_js", run_page_js)
    assert tc._page_posts("press", "2063500000000000101") == {"url": POST, "result": "clicked"}
    assert seen[0].rstrip().endswith('("press", "2063500000000000101")')
    monkeypatch.setattr(tc, "_run_page_js", lambda js: "")
    assert tc._page_posts("read") == {}


def test_run_page_js_logs_failures_and_returns_empty(monkeypatch):
    from src.x import twitter_client as tc

    lines = []
    monkeypatch.setattr(tc.log, "info", lambda msg, *a, **k: lines.append(msg))
    monkeypatch.setattr(tc, "require_active", lambda: None)
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="", stderr="execution error: JavaScript from Apple Events is off\n"))
    assert tc._run_page_js("1") == ""
    assert lines == ["[LIKE] Page JavaScript failed (osascript exit 1): "
                     "execution error: JavaScript from Apple Events is off"]

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("osascript", 10)
    monkeypatch.setattr(tc.subprocess, "run", timeout)
    assert tc._run_page_js("1") == ""
    assert lines[-1].startswith("[LIKE] Page JavaScript failed: TimeoutExpired(")


# The JavaScript itself, run by node against a minimal fake DOM that knows
# only the selectors `_POSTS_JS` uses.
_FAKE_DOM_JS = r"""
var clicks = [];
function parseCompound(s) {
    var m = s.match(/^([a-z]*)(?:\[([\w-]+)(\*?=)"([^"]*)"\])?$/);
    if (!m) throw new Error('unsupported selector ' + s);
    return {tag: m[1], attr: m[2], op: m[3], val: m[4]};
}
function El(spec, parent) {
    this.tagName = spec.tag;
    this.attrs = spec.attrs || {};
    this.parent = parent || null;
    var self = this;
    this.children = (spec.children || []).map(function(c) { return new El(c, self); });
}
Object.defineProperty(El.prototype, 'href', {get: function() { return this.attrs.href || ''; }});
El.prototype.matchesCompound = function(c) {
    if (c.tag && c.tag !== this.tagName) return false;
    if (!c.attr) return true;
    var v = this.attrs[c.attr];
    if (v === undefined) return false;
    return c.op === '=' ? v === c.val : v.indexOf(c.val) >= 0;
};
El.prototype.matches = function(sel) {
    var parts = sel.trim().split(/\s+/).map(parseCompound);
    if (!this.matchesCompound(parts[parts.length - 1])) return false;
    var k = parts.length - 2, node = this.parent;
    while (k >= 0 && node) { if (node.matchesCompound(parts[k])) k--; node = node.parent; }
    return k < 0;
};
El.prototype.descendants = function() {
    var out = [];
    this.children.forEach(function(c) { out.push(c); out.push.apply(out, c.descendants()); });
    return out;
};
El.prototype.querySelectorAll = function(sel) {
    return this.descendants().filter(function(e) { return e.matches(sel); });
};
El.prototype.querySelector = function(sel) { return this.querySelectorAll(sel)[0] || null; };
El.prototype.closest = function(sel) {
    for (var n = this; n; n = n.parent) if (n.matches(sel)) return n;
    return null;
};
El.prototype.click = function() {
    clicks.push(this.attrs.id || '');
    if (this.attrs['data-testid'] === 'like') this.attrs['data-testid'] = 'unlike';
};
"""


def _article(url, button, id_, quoted="", quoted_first=False):
    children = [{"tag": "a", "attrs": {"href": url}, "children": [{"tag": "time"}]}]
    if quoted:
        card = {"tag": "div", "children": [{"tag": "article", "children": [
            {"tag": "a", "attrs": {"href": quoted}, "children": [{"tag": "time"}]}]}]}
        children.insert(0 if quoted_first else 1, card)
    children.append({"tag": "div", "children": [
        {"tag": "button", "attrs": {"data-testid": button, "id": f"{id_}-button"}}]})
    return {"tag": "article", "attrs": {"data-testid": "tweet", "id": id_}, "children": children}


def _run_posts_js(articles, mode, target_id="", path="/home"):
    from src.x import twitter_client as tc

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: _POSTS_JS cannot be run")
    snippet = tc._POSTS_JS.replace("__MODE__", mode).replace("__TARGET_ID__", target_id)
    program = _FAKE_DOM_JS + f"""
var root = new El({json.dumps({"tag": "html", "children": [{"tag": "body", "children": articles}]})});
var document = {{
    querySelectorAll: function(sel) {{ return root.querySelectorAll(sel); }}
}};
var location = {{pathname: {json.dumps(path)}, href: 'https://x.com' + {json.dumps(path)}}};
var out = eval({json.dumps(snippet)});
console.log(JSON.stringify({{out: JSON.parse(out), clicks: clicks}}));
"""
    res = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    return data["out"], data["clicks"]


POST_ID = "2063500000000000101"
NEXT_ID = "2063500000000000102"


def test_js_clicks_like_on_the_target_article_only():
    articles = [_article(NEXT, "like", "a"), _article(POST, "like", "b")]
    assert _run_posts_js(articles, "press", POST_ID) == ({"url": POST, "result": "clicked"}, ["b-button"])


def test_js_never_clicks_an_unlike_button():
    articles = [_article(POST, "unlike", "a")]
    assert _run_posts_js(articles, "press", POST_ID) == ({"url": POST, "result": "already_liked"}, [])


def test_js_read_mode_clicks_nothing():
    articles = [_article(POST, "like", "a")]
    assert _run_posts_js(articles, "read", POST_ID) == ({"url": POST, "result": "not_liked"}, [])


@pytest.mark.parametrize("articles, target, path", [
    ([_article(POST, "like", "a")], "", "/home"),                 # no target
    ([_article(POST, "like", "a")], "", f"/thebtctherapist/status/{POST_ID}"),  # not even the status page's post
    ([_article(POST, "like", "a")], NEXT_ID, "/home"),            # requested post absent
    ([_article(POST, "like", "a", quoted=NEXT)], NEXT_ID, "/home"),  # only quoted
    ([_article(POST, "like", "a", quoted=NEXT, quoted_first=True)], NEXT_ID, "/home"),
])
def test_js_fails_without_clicking_when_no_article_is_identified(articles, target, path):
    out, clicks = _run_posts_js(articles, "press", target, path=path)
    assert out == {"url": "", "result": "failed"} and clicks == []


def test_js_reads_the_quoting_post_url_even_when_the_quoted_card_comes_first():
    articles = [_article(POST, "like", "a", quoted=NEXT, quoted_first=True)]
    assert _run_posts_js(articles, "list")[0]["posts"] == [POST]
    assert _run_posts_js(articles, "press", POST_ID) == ({"url": POST, "result": "clicked"}, ["a-button"])


def test_js_lists_the_posts_in_page_order():
    articles = [_article(NEXT, "like", "a"), _article(POST, "unlike", "b", quoted=REPOST)]
    out, clicks = _run_posts_js(articles, "list")
    assert out == {"page": "https://x.com/home", "posts": [NEXT, POST]} and clicks == []
