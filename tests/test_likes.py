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


class FakePage:
    """Answers `_page_posts` like `_POSTS_JS` would on a page of posts."""

    def __init__(self, page="https://x.com/thebtctherapist", posts=(), focused=None):
        self.page = page
        self.posts = [dict(p) for p in posts]
        self.focused = focused
        self.clicks = []
        self.click_sticks = True

    def _find(self, target_id):
        from src.x import x_urls
        if not target_id and self.focused is not None:
            return self.posts[self.focused]
        target_id = target_id or x_urls.status_id(self.page)
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
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc, "_liked_cache_path", lambda: str(tmp_path / "liked_tweets.json"))
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(tc, "_navigate_to_first_tweet", lambda: None)
    state = {"page": FakePage(), "recorded": [], "closed": 0}
    monkeypatch.setattr(tc, "_page_posts", lambda *a: state["page"](*a))
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: state["recorded"].append((a, k)))

    def close_front_tab():
        state["closed"] += 1
    monkeypatch.setattr(tc, "close_front_tab", close_front_tab)
    return state


def test_no_like_path_presses_the_l_shortcut():
    from src.x import twitter_client as tc
    assert 'keystroke "l"' not in inspect.getsource(tc)


def test_already_liked_post_is_never_clicked(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": True}])
    assert tc.like_tweet() is tc.LikeOutcome.ALREADY_LIKED
    assert tc.like_tweet(POST) is tc.LikeOutcome.ALREADY_LIKED
    assert page.clicks == [] and browser["recorded"] == []


def test_cached_like_is_never_clicked_even_if_the_page_says_not_liked(browser):
    from src.x import twitter_client as tc

    tc._mark_liked(POST)
    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": False}])
    assert tc.like_tweet() is tc.LikeOutcome.ALREADY_LIKED
    assert tc.like_tweet(POST) is tc.LikeOutcome.ALREADY_LIKED
    assert page.clicks == []


def test_like_clicks_the_identified_post_once_and_records_the_read_url(browser):
    from src.guards import action_guard
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(page=POST, posts=[{"url": POST, "liked": False}])
    outcome = tc.like_tweet()
    assert outcome is tc.LikeOutcome.LIKED and outcome
    assert page.clicks == [POST]
    assert browser["recorded"] == [((action_guard.LIKE,), {"target": POST})]
    assert tc._already_liked(POST)


def test_a_given_url_clicks_that_post_not_the_focused_one(browser):
    from src.x import twitter_client as tc

    page = browser["page"] = FakePage(
        posts=[{"url": POST, "liked": False}, {"url": NEXT, "liked": False}], focused=0)
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
    ("https://x.com/home", ""),                 # no identifiable post
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


def test_reciprocity_likes_their_own_posts_and_reports_each(browser):
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
def test_reciprocity_opens_nothing_for_zero_likes_or_dry_run(monkeypatch, dry_run, like_count):
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


def test_reciprocity_counts_only_likes_that_shipped(monkeypatch):
    from src.replies import notify_bot as nb
    LikeOutcome = nb.LikeOutcome  # test_editorial reloads twitter_client

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
El.prototype.find = function(id) {
    if (this.attrs.id === id) return this;
    for (var i = 0; i < this.children.length; i++) {
        var f = this.children[i].find(id);
        if (f) return f;
    }
    return null;
};
El.prototype.click = function() {
    clicks.push(this.attrs.id || '');
    if (this.attrs['data-testid'] === 'like') this.attrs['data-testid'] = 'unlike';
};
"""


def _article(url, button, id_, quoted=""):
    children = [{"tag": "a", "attrs": {"href": url}, "children": [{"tag": "time"}]}]
    if quoted:
        children.append({"tag": "div", "children": [
            {"tag": "a", "attrs": {"href": quoted}, "children": [{"tag": "time"}]}]})
    children.append({"tag": "div", "children": [
        {"tag": "button", "attrs": {"data-testid": button, "id": f"{id_}-button"}}]})
    return {"tag": "article", "attrs": {"data-testid": "tweet", "id": id_}, "children": children}


def _run_posts_js(articles, mode, target_id="", path="/home", focus_id=""):
    from src.x import twitter_client as tc

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: _POSTS_JS cannot be run")
    snippet = tc._POSTS_JS.replace("__MODE__", mode).replace("__TARGET_ID__", target_id)
    program = _FAKE_DOM_JS + f"""
var root = new El({json.dumps({"tag": "html", "children": [{"tag": "body", "children": articles}]})});
var body = root.children[0];
var focusId = {json.dumps(focus_id)};
var document = {{
    documentElement: root, body: body,
    activeElement: focusId ? root.find(focusId) : body,
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


@pytest.mark.parametrize("articles, target, path, focus", [
    ([_article(POST, "like", "a")], "", "/home", ""),             # nothing identifies a post
    ([_article(POST, "like", "a")], NEXT_ID, "/home", ""),        # requested post absent
    ([_article(POST, "like", "a", quoted=NEXT)], NEXT_ID, "/home", ""),  # only quoted
    ([{"tag": "div", "attrs": {"id": "nav"}}, _article(POST, "like", "a")], "", "/home", "nav"),
])
def test_js_fails_without_clicking_when_no_article_is_identified(articles, target, path, focus):
    out, clicks = _run_posts_js(articles, "press", target, path=path, focus_id=focus)
    assert out == {"url": "", "result": "failed"} and clicks == []


def test_js_falls_back_to_the_focused_then_the_status_page_post():
    articles = [_article(NEXT, "like", "a"), _article(POST, "like", "b")]
    focused, clicks = _run_posts_js(articles, "press", focus_id="b-button")
    assert focused["url"] == POST and clicks == ["b-button"]
    own, clicks = _run_posts_js(articles, "press", path=f"/thebtctherapist/status/{NEXT_ID}")
    assert own["url"] == NEXT and clicks == ["a-button"]


def test_js_lists_the_posts_in_page_order():
    articles = [_article(NEXT, "like", "a"), _article(POST, "unlike", "b", quoted=REPOST)]
    out, clicks = _run_posts_js(articles, "list")
    assert out == {"page": "https://x.com/home", "posts": [NEXT, POST]} and clicks == []
