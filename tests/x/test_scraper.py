"""src/x/scraper: profile-visit allowlist and blank-page restarts."""
import pytest


@pytest.fixture
def feed_browser(monkeypatch, settings_override):
    from types import SimpleNamespace
    from src.x import scraper, safari
    settings_override(FEED_SCROLL_PASSES=20)
    trace = SimpleNamespace(opened=[], closed=[], scrolls=[], tabs=[], pages=[])
    monkeypatch.setattr(safari, "open_url", lambda url: trace.opened.append(url) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: trace.closed.append(True))
    monkeypatch.setattr(safari, "_scroll_page", lambda: trace.scrolls.append(True))
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(scraper, "_feed_tab", lambda labels, click:
                        trace.tabs.append((labels, click)) or "SELECTED")
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page",
                        lambda *a: trace.pages.pop(0) if trace.pages else [])
    return trace


def _post(number, host="x.com"):
    return {"url": f"https://{host}/builder/status/{2063500000000000000 + number}",
            "text": f"SI post {number}"}


@pytest.mark.parametrize("name, label", [("scrape_home_feed", "for you"),
                                         ("scrape_following_feed", "following")])
def test_deep_feeds_select_the_right_tab_and_keep_each_viewport(feed_browser, name, label):
    from src.x import scraper
    feed_browser.pages = [[_post(i), _post(i + 1)] for i in range(20)]
    feed_browser.pages.append([_post(20, "twitter.com"), _post(21)])
    posts = getattr(scraper, name)(160)
    assert [p["text"] for p in posts] == [f"SI post {i}" for i in range(22)]
    assert len(feed_browser.scrolls) == 20
    assert [click for labels, click in feed_browser.tabs if labels[0] == label] == [True, False]
    assert feed_browser.closed == [True]


def test_feed_stops_at_candidate_budget_without_extra_scrolls(feed_browser):
    from src.x import scraper
    feed_browser.pages = [[_post(1), _post(2)], [_post(3)], [_post(4)]]
    assert len(scraper.scrape_home_feed(3)) == 3
    assert len(feed_browser.scrolls) == 1


def test_feed_stops_after_three_duplicate_or_empty_viewports(feed_browser):
    from src.x import scraper
    feed_browser.pages = [[_post(1)], [_post(1, "twitter.com")], [], [_post(1)], [_post(2)]]
    assert scraper.scrape_home_feed(160) == [_post(1)]
    assert len(feed_browser.scrolls) == 3


@pytest.mark.parametrize("answers", [("NO_TAB",), ("NOT_SELECTED",), ("CLICKED", "NOT_SELECTED")])
def test_wrong_or_missing_feed_tab_never_reads_posts(feed_browser, monkeypatch, answers):
    from src.x import scraper
    answers = iter(answers)
    monkeypatch.setattr(scraper, "_feed_tab", lambda *a, **k: next(answers))
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page",
                        lambda *a: pytest.fail("read an unverified feed"))
    assert scraper.scrape_following_feed(160) == []
    assert feed_browser.closed == [True]


def test_feed_exception_closes_tab_and_releases_lock(feed_browser, monkeypatch):
    from src.x import scraper
    def fail(*args):
        raise RuntimeError("scrape failed")
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", fail)
    with pytest.raises(RuntimeError, match="scrape failed"):
        scraper.scrape_home_feed(160)
    assert feed_browser.closed == [True]


@pytest.mark.parametrize("selected, click, expected, clicks", [
    (False, True, "CLICKED", 1), (False, False, "NOT_SELECTED", 0),
    (True, True, "SELECTED", 0), (True, False, "SELECTED", 0),
])
def test_feed_tab_script_checks_selection_before_clicking(monkeypatch, selected, click, expected, clicks):
    import json
    import shutil
    import subprocess
    from src.x import scraper, safari
    if not shutil.which("node"):
        pytest.skip("node is needed to run the page script")
    captured = []
    monkeypatch.setattr(safari, "_run_js", lambda script, *a, **k: captured.append(script))
    scraper._feed_tab(("for you", "pour vous"), click=click)
    script = f"""
    let clicks = 0;
    const tab = {{textContent: '  For You  ',
      getAttribute: () => {json.dumps(str(selected).lower())}, click: () => clicks++}};
    const document = {{querySelectorAll: () => [tab]}};
    const result = {captured[0]};
    console.log(JSON.stringify([result, clicks]));
    """
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [expected, clicks]


def test_profile_visits_blocked_outside_allowlist(monkeypatch, settings_override):
    """Operator mandate 2026-06-07 PM: NO profile visits for discovery —
    scrape surfaces are @TheBTCTherapist + Home (For You/Following) + search.
    A non-allowlisted profile must return [] BEFORE any Safari work, and the
    allowlist must be read at call time (side-effect-gate rule)."""
    from src.x import safari, scraper, twitter_client as tc
    from src.core import account
    from src.core.config import BOT_HANDLE

    default = ",".join(account.current().network.profile_visits)
    assert default == "TheBTCTherapist,Graphseo"
    settings_override(PROFILE_VISIT_ALLOWLIST=default)  # whatever .env says
    monkeypatch.setattr(
        safari, "open_url",
        lambda *a, **k: pytest.fail("Safari was opened for a blocked profile"))
    assert scraper.scrape_profile_tweets("unusual_whales") == []
    assert scraper.scrape_profile_tweets("karpathy") == []
    tc.visit_profile_and_like("unusual_whales")  # must not open Safari either

    # Allowlist semantics (pure check, no Safari), on the Account's list
    # pinned above: the two reply-everything friends (operator 2026-06-07).
    assert scraper._profile_visit_allowed(BOT_HANDLE)
    assert scraper._profile_visit_allowed(f"{BOT_HANDLE}/with_replies")
    assert scraper._profile_visit_allowed("TheBTCTherapist")
    assert scraper._profile_visit_allowed("@thebtctherapist")
    assert scraper._profile_visit_allowed("Graphseo")
    assert not scraper._profile_visit_allowed("zerohedge")
    assert not scraper._profile_visit_allowed("")

    # Read at CALL time: a later override reaches the next check.
    settings_override(PROFILE_VISIT_ALLOWLIST="TheBTCTherapist")
    assert not scraper._profile_visit_allowed("graphseo")
    assert scraper._profile_visit_allowed("thebtctherapist")


def test_blank_page_storm_post_restart_grace_and_label_diversity(monkeypatch):
    """2026-07-19: 7 reactive Safari restarts in 2.2h. Two structural causes:
    (1) scrapes queued behind a hygiene restart hit the cold Safari, blank,
    and re-trip the threshold — a self-perpetuating ~15-min loop. Blanks
    within the post-restart grace window must not count. (2) one page
    legitimately empty in a loop (e.g. a quiet Following tab) is NOT a
    wedged Safari — a true wedge blanks EVERY page, so the restart needs
    >=2 distinct labels among the consecutive blanks."""
    import time as _time
    from src.x import scraper
    from src.x import safari_hygiene as sh

    restarts = []
    monkeypatch.setattr(sh, "restart_safari", lambda reason="": restarts.append(reason) or True)

    # (1) grace: blanks right after a restart don't count
    scraper._reset_blank_page_count()
    monkeypatch.setattr(sh, "_last_run_ts", lambda: _time.time())
    for _ in range(5):
        scraper._record_blank_page(label="search 'x'")
    assert restarts == [], "blanks during post-restart grace must not restart Safari"

    # (2) out of grace: same-label loop holds, diverse labels restart
    monkeypatch.setattr(sh, "_last_run_ts", lambda: _time.time() - 3600)
    scraper._reset_blank_page_count()
    for _ in range(4):
        scraper._record_blank_page(label="following feed")
    assert restarts == [], "single-page empty loop is not a wedge — no restart"
    scraper._reset_blank_page_count()
    scraper._record_blank_page(label="following feed")
    scraper._record_blank_page(label="search 'ai'")
    scraper._record_blank_page(label="@TheAIShrink")
    assert restarts == ["black_screen_recovery"], "diverse-label blanks = wedge = restart"
    scraper._reset_blank_page_count()
