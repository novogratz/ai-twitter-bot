"""src/x/scraper: profile-visit allowlist and blank-page restarts."""
import pytest


def test_profile_visits_blocked_outside_allowlist(monkeypatch, settings_override):
    """The operator's AI profile list is read at call time; exclusions always win."""
    from src.x import safari, scraper, twitter_client as tc
    from src.core import account
    from src.core.config import BOT_HANDLE
    default = ",".join(account.current().network.profile_visits)
    assert default.startswith("elonmusk,SpaceXSI,karpathy,")
    settings_override(PROFILE_VISIT_ALLOWLIST=default)
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: pytest.fail("opened excluded profile"))
    for handle in ("TheBTCTherapist", "Graphseo", "unusual_whales", "unlisted"):
        assert scraper.scrape_profile_tweets(handle) == []
        assert tc.visit_profile_and_like(handle) == []
    assert scraper._profile_visit_allowed(BOT_HANDLE)
    assert scraper._profile_visit_allowed(f"{BOT_HANDLE}/with_replies")
    assert scraper._profile_visit_allowed("@ElonMusk")
    assert scraper._profile_visit_allowed("karpathy")
    assert not scraper._profile_visit_allowed("")
    settings_override(PROFILE_VISIT_ALLOWLIST="xai,TheBTCTherapist,Graphseo")
    assert scraper._profile_visit_allowed("xai")
    assert not scraper._profile_visit_allowed("elonmusk")
    assert not scraper._profile_visit_allowed("TheBTCTherapist")
    assert not scraper._profile_visit_allowed("Graphseo")


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
@pytest.mark.parametrize("query", ["from:someone", "Grok OR Claude", "bitcoin OR lunch"])
def test_every_search_gets_account_scope_before_safari_opens(monkeypatch, query):
    from urllib.parse import parse_qs, urlparse
    from src.core import account
    from src.x import safari, scraper
    opened = []
    monkeypatch.setattr(safari, "open_url", opened.append)
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(scraper.time, "sleep", lambda *a: None)
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", lambda *a: [])
    assert scraper.scrape_x_search(query) == []
    actual = parse_qs(urlparse(opened[0]).query)["q"][0]
    assert actual == account.current().searches.scoped(query)
    assert "SI OR AI" in actual and "-crypto" in actual and "-bitcoin" in actual
    assert "-bittensor" in actual and "-filter:replies" in actual


@pytest.fixture
def feed_browser(monkeypatch):
    from src.x import safari, scraper
    calls = {"closed": 0, "scraped": 0, "scrolled": 0}
    monkeypatch.setattr(safari, "open_url", lambda url: True)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: calls.update(closed=calls["closed"] + 1))
    monkeypatch.setattr(safari, "_scroll_page", lambda: calls.update(scrolled=calls["scrolled"] + 1))
    def scrape(*args):
        calls["scraped"] += 1
        return [{"url": "https://x.com/builder/status/123", "text": "software release"}]
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", scrape)
    return calls


@pytest.mark.parametrize("answers", [
    ["MISSING"], ["CLICKED", "UNSELECTED"],
    ["SELECTED", "NO_MENU"], ["SELECTED", "MENU", "MISSING", "SELECTED"],
    ["SELECTED", "MENU", "CLICKED", "MENU", "UNSELECTED", "SELECTED"],
])
def test_following_never_scrapes_an_unverified_sort(monkeypatch, feed_browser, answers):
    from src.x import safari, scraper
    responses = iter(answers)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: next(responses, "MISSING"))
    assert scraper.scrape_following_feed(sort="popular") == []
    assert feed_browser == {"closed": 1, "scraped": 0, "scrolled": 0}


@pytest.mark.parametrize("sort", ["recent", "popular"])
def test_following_verifies_sort_after_clicking(monkeypatch, feed_browser, sort):
    from src.x import safari, scraper
    answers = iter(["SELECTED", "MENU", "CLICKED", "MENU", "SELECTED", "SELECTED"])
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: next(answers))
    assert len(scraper.scrape_following_feed(1, sort=sort)) == 1
    assert feed_browser["closed"] == feed_browser["scraped"] == 1


def test_feed_closes_its_tab_when_a_scrape_raises(monkeypatch, feed_browser):
    from src.x import safari, scraper
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: "SELECTED")
    def fail(*a):
        raise RuntimeError("scrape failed")
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", fail)
    with pytest.raises(RuntimeError, match="scrape failed"):
        scraper.scrape_home_feed()
    assert feed_browser["closed"] == 1


def test_scrolling_keeps_prior_viewports_and_deduplicates_status_ids(monkeypatch, feed_browser):
    from src.x import scraper
    def post(key, author="builder", text="software"):
        return {"url": f"https://x.com/{author}/status/{key}", "text": text}
    pages = iter([[post(1), post(2)], [post(2, "renamed", "software release details"), post(3)], [post(4)]])
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", lambda *a: next(pages))
    rows = scraper._collect_scrolling_tweets("feed", 4, 2000, max_scrolls=8)
    assert [r["url"].split("/")[-1] for r in rows] == ["1", "2", "3", "4"]
    assert rows[1]["text"] == "software release details"
    assert feed_browser["scrolled"] == 2


def test_scrolling_stops_when_no_new_posts_arrive(feed_browser):
    from src.x import scraper
    assert len(scraper._collect_scrolling_tweets("feed", 80, 2000, max_scrolls=8)) == 1
    assert feed_browser["scrolled"] == 2


@pytest.mark.parametrize("handle", ["TheAIShrink", "THESIMAXIMALIST"])
def test_renamed_account_still_recognizes_its_own_saved_posts(handle):
    from src.x import scraper
    from src.guards.reply_admission import judge_parent, Refusal
    url = f"https://x.com/{handle}/status/123"
    assert scraper.is_own_post({"url": url})
    assert judge_parent(url).refusal is Refusal.OWN_POST
