"""src/x/scraper: profile-visit allowlist and blank-page restarts, and the
page sessions its scrapes read through (#254)."""
import json
import threading
import time

import pytest

PROFILE = "https://x.com/TheAIShrink"
HOME = "https://x.com/home"
SEARCH = "https://x.com/search?q=ai&src=typed_query&f=top"
OWN_STATUS = "https://x.com/TheAIShrink/status/2063500000000000301"


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


def test_the_scraper_applescript_runs_have_a_bound(monkeypatch):
    """#257: a restart waits for the Safari lock, so an osascript that never
    returns under it would freeze the bot. The activate before a page read's
    second JavaScript try, the Replyback tab walk and its scroll carry a
    bound."""
    import subprocess
    from src.x import safari, scraper

    runs = []
    monkeypatch.setattr(safari, "_run_applescript",
                        lambda script, *a, **k: runs.append(k.get("timeout_s")) or True)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    def timed_out(*a, **k):
        raise subprocess.TimeoutExpired("osascript", 30)
    monkeypatch.setattr(safari, "_run_js", timed_out)
    monkeypatch.setattr(scraper, "_record_timed_out_scrape", lambda label: None)
    assert scraper._scrape_tweets_from_page("search 'ai'") == []

    monkeypatch.setattr(safari, "_run_js",
                        lambda js, *a, **k: OWN_STATUS if js == scraper._LOCATION_JS else "")
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
    monkeypatch.setattr(safari, "_close_session_tab", lambda: None)
    assert scraper.scrape_own_tweet_and_replies() is None

    assert runs == [safari.ACTIVATE_TIMEOUT_S, safari.KEYSTROKE_TIMEOUT_S,
                    safari.SCROLL_TIMEOUT_S]


# The scrapes on the memory page.

def _tweet(author, n):
    return {"u": f"https://x.com/{author}/status/{n}", "t": "hello", "a": author}


def test_only_the_visitable_profiles_open(memory_page, settings_override):
    """The visit list gates the page itself: a profile off it opens no page,
    ours and the listed ones do."""
    from src.x import scraper

    settings_override(PROFILE_VISIT_ALLOWLIST="TheBTCTherapist")
    friend = "https://x.com/TheBTCTherapist"
    memory_page.pages[friend] = [json.dumps([_tweet("TheBTCTherapist", 1)])]
    memory_page.pages[PROFILE] = ["[]"]

    assert scraper.scrape_profile_tweets("karpathy") == []
    assert scraper.scrape_profile_tweets("Graphseo") == []
    assert [t["url"] for t in scraper.scrape_profile_tweets("TheBTCTherapist")] \
        == ["https://x.com/TheBTCTherapist/status/1"]
    assert scraper.scrape_profile_tweets("TheAIShrink") == []
    assert memory_page.opened == [friend, PROFILE]
    assert memory_page.closed == 2


def test_a_blank_page_storm_restarts_safari_inside_the_session(memory_page, monkeypatch):
    """Three pages blank in a row: the third scrape restarts Safari from
    inside its own session, which holds the reentrant Safari lock (#257),
    without deadlocking, and each session still closes its tab once."""
    from src.x import scraper
    from src.x import safari_hygiene as sh

    bounced = []
    monkeypatch.setattr(sh, "_last_run_ts", lambda: time.time() - 3600)
    monkeypatch.setattr(sh, "_quit_safari", lambda: bounced.append(memory_page.closed))
    monkeypatch.setattr(sh, "_launch_safari", lambda: True)
    monkeypatch.setattr(sh, "_mark_ran", lambda: None)
    for url in (HOME, SEARCH, PROFILE):
        memory_page.pages[url] = ["NO_ARTICLES"]
    scraper._reset_blank_page_count()

    results = []
    worker = threading.Thread(daemon=True, target=lambda: results.extend([
        scraper.scrape_home_feed(), scraper.scrape_x_search("ai"),
        scraper.scrape_profile_tweets("TheAIShrink")]))
    worker.start()
    worker.join(5)

    assert not worker.is_alive(), "the restart inside the scrape's session deadlocked"
    assert results == [[], [], []]
    assert bounced == [2], "the third session restarts Safari before its tab close"
    assert memory_page.opened == [HOME, SEARCH, PROFILE]
    assert memory_page.closed == 3
    scraper._reset_blank_page_count()


def _safari_lock_free():
    from src.x import safari

    seen = []

    def probe():
        got = safari._safari_lock._lock.acquire(blocking=False)
        if got:
            safari._safari_lock._lock.release()
        seen.append(got)
    worker = threading.Thread(target=probe)
    worker.start()
    worker.join()
    return seen[0]


def test_feed_scrapes_scroll_lower_for_the_default_reply_depth(memory_page):
    from src.x import scraper

    memory_page.pages[HOME] = ["[]", "CLICKED", "[]"]

    assert scraper.scrape_home_feed(max_tweets=120) == []
    assert scraper.scrape_following_feed(max_tweets=120) == []
    assert memory_page.scrolls == 37  # 20 For You + 17 Following


def test_a_tweet_page_that_does_not_open_counts_as_a_blank_page(memory_page, monkeypatch):
    """A wedged Safari times out on `open location` as on a read: the
    tweet scrapes count a page that did not open as a timed-out read, once
    their session has closed its tab and released the Safari lock. The feed
    refresh and our latest post do not count it."""
    from src.x import scraper

    counted = []
    monkeypatch.setattr(scraper, "_record_timed_out_scrape", lambda label: counted.append(
        (label, memory_page.closed, _safari_lock_free())))
    assert scraper.scrape_home_feed() == []
    assert scraper.scrape_following_feed() == []
    assert scraper.scrape_x_search("ai") == []
    assert scraper.scrape_mentions() == []
    assert scraper.scrape_profile_tweets("TheAIShrink") == []
    assert scraper.refresh_feed() is None
    assert scraper.scrape_own_tweet_and_replies() is None
    assert counted == [("home feed", 1, True), ("following feed", 2, True),
                       ("search 'ai' (top)", 3, True), ("mentions", 4, True),
                       ("@TheAIShrink", 5, True)]
    assert memory_page.scripts == []


def test_pages_that_do_not_open_on_two_labels_restart_safari(memory_page, monkeypatch):
    """Failed opens run the blank-page guards: mentions never counts, and
    three in a row on two distinct pages restart Safari, after the last
    session has closed its tab, without deadlocking."""
    from src.x import scraper
    from src.x import safari_hygiene as sh

    bounced = []
    monkeypatch.setattr(sh, "_last_run_ts", lambda: time.time() - 3600)
    monkeypatch.setattr(sh, "_quit_safari", lambda: bounced.append(memory_page.closed))
    monkeypatch.setattr(sh, "_launch_safari", lambda: True)
    monkeypatch.setattr(sh, "_mark_ran", lambda: None)
    scraper._reset_blank_page_count()

    results = []
    worker = threading.Thread(daemon=True, target=lambda: results.extend([
        scraper.scrape_mentions(), scraper.scrape_x_search("ai"),
        scraper.scrape_x_search("ai"), scraper.scrape_profile_tweets("TheAIShrink")]))
    worker.start()
    worker.join(5)

    assert not worker.is_alive(), "the restart after a failed open deadlocked"
    assert results == [[], [], [], []]
    assert bounced == [4], "the restart runs once the fourth session closed its tab"
    assert memory_page.scripts == []
    scraper._reset_blank_page_count()


def test_a_blank_page_restart_that_succeeded_resets_the_health_counter(memory_page, monkeypatch):
    """#302: the health failure counter is reset after every restart that
    succeeded, the blank-page recovery's included."""
    from src.core import health
    from src.x import scraper
    from src.x import safari_hygiene as sh

    monkeypatch.setattr(sh, "_last_run_ts", lambda: time.time() - 3600)
    monkeypatch.setattr(sh, "_quit_safari", lambda: None)
    monkeypatch.setattr(sh, "_launch_safari", lambda: True)
    monkeypatch.setattr(sh, "_mark_ran", lambda: None)
    health.HEALTH.write({"consecutive_failures": 2, "last_recovery_ts": 0, "total_recoveries": 0})

    scraper._trigger_black_screen_recovery("home_feed_blank_2")

    assert health.HEALTH.read()["consecutive_failures"] == 0


def test_replyback_presses_nothing_when_our_profile_does_not_open(memory_page):
    """The tab walk used to run whatever the open gave, pressing Tab Tab
    Tab Return on the tab in front."""
    from src.x import scraper

    memory_page.pages["https://x.com/front"] = ['{"own_tweet": "theirs", "replies": []}']
    memory_page.front = "https://x.com/front"
    assert scraper.scrape_own_tweet_and_replies() is None
    assert (memory_page.pressed, memory_page.scripts) == ([], [])


def test_replyback_walks_to_our_latest_post_and_reads_its_replies(memory_page):
    from src.x import safari, scraper

    answer = {"own_tweet": "ours", "replies": [{"user": "a", "text": "hi", "url": ""}]}
    memory_page.pages[PROFILE] = [OWN_STATUS, json.dumps(answer)]
    assert scraper.scrape_own_tweet_and_replies() == answer
    walk, scroll = memory_page.pressed
    assert walk == safari.FIRST_TWEET_KEYS
    assert "key code 125" in scroll
    assert memory_page.waits == [5, 5, 2]
    assert memory_page.closed == 1


def test_replyback_reads_nothing_when_the_walk_to_our_latest_post_fails(monkeypatch):
    """#301: a failed tab walk leaves our profile in front, whose first
    post the read would take for ours and the others for its replies."""
    from src.x import page_session, safari, scraper
    from tests.helpers import WritePage

    page = WritePage(answers=[OWN_STATUS, '{"own_tweet": "ours", "replies": []}'],
                     fail={"keys"})
    monkeypatch.setattr(page_session, "BROWSER", page)
    assert scraper.scrape_own_tweet_and_replies() is None
    assert (page.pressed, page.scripts) == ([safari.FIRST_TWEET_KEYS], [])
    assert page.closed == 1


@pytest.mark.parametrize("reached", [
    PROFILE, "", "https://x.com/someone/status/2063500000000000301",
    "https://x.com/TheAIShrink/with_replies",
], ids=["our_profile", "no_location", "their_post", "our_replies_tab"])
def test_replyback_reads_nothing_off_one_of_our_status_pages(memory_page, reached):
    from src.x import scraper

    memory_page.pages[PROFILE] = [reached, '{"own_tweet": "ours", "replies": []}']
    assert scraper.scrape_own_tweet_and_replies() is None
    assert len(memory_page.pressed) == 1, "no scroll past the walk"
    assert [s.js for s in memory_page.scripts] == [scraper._LOCATION_JS]
    assert memory_page.closed == 1
