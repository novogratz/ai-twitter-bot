"""src/x/scraper: profile-visit allowlist and blank-page restarts."""
import pytest


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


def test_ownership_recognizes_new_and_historical_handles_but_not_display_names():
    from src.x import scraper
    for handle in ("thesimaximalist", "TheAIShrink", "THEAISHrink"):
        assert scraper.is_own_post({"url": f"https://x.com/{handle}/status/123", "author": "Some display name"})
        assert scraper.is_own_post({"url": f"https://twitter.com/{handle}/status/123?s=20"})
    assert not scraper.is_own_post({"url": "https://x.com/other/status/123", "author": "The SI Maximalist"})
    assert not scraper.is_own_post({"url": "https://example.com/thesimaximalist/status/123"})


@pytest.mark.parametrize("surface", ["profile", "home", "following", "search"])
def test_reply_scrape_surfaces_forward_the_parent_text_limit(monkeypatch, surface):
    from src.x import scraper, safari
    monkeypatch.setattr(scraper, "_profile_visit_allowed", lambda username: True)
    monkeypatch.setattr(scraper.time, "sleep", lambda *a: None)
    for name in ("open_url", "_scroll_page", "close_front_tab"):
        monkeypatch.setattr(safari, name, lambda *a, **k: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: "CLICKED")
    seen = []
    monkeypatch.setattr(scraper, "_scrape_tweets_from_page", lambda label, count, limit:
                        seen.append((count, limit)) or [])
    calls = {"profile": lambda: scraper.scrape_profile_tweets("builder", 3, text_limit=4000),
             "home": lambda: scraper.scrape_home_feed(3, text_limit=4000),
             "following": lambda: scraper.scrape_following_feed(3, text_limit=4000),
             "search": lambda: scraper.scrape_x_search("SI research", 3, text_limit=4000)}
    assert calls[surface]() == []
    assert seen == [(3, 4000)]


@pytest.mark.parametrize("text", ["SI research.\n" * 30, "SI " + "🙂" * 4000])
def test_scraped_visible_text_retains_long_evidence_and_counts_unicode_characters(monkeypatch, text):
    import json
    import shutil
    import subprocess
    from src.x import scraper, safari
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the browser script fixture")
    harness = r"""
const input = JSON.parse(process.argv[1]);
const article = {
  innerHTML: '', innerText: input.text,
  querySelector: selector => selector === '[data-testid="tweetText"]'
    ? {innerText: input.text, textContent: 'Hidden or differently formatted content'} : null,
  querySelectorAll: () => [{getAttribute: () => '/builder/status/123'}]
};
global.document = {querySelectorAll: () => [article]};
process.stdout.write(eval(input.js));
"""
    def run(js, *args, **kwargs):
        return subprocess.run([node, "-e", harness, json.dumps({"text": text, "js": js})],
                              capture_output=True, text=True, check=True).stdout
    monkeypatch.setattr(safari, "_run_js", run)
    rows = scraper._scrape_tweets_from_page("test", 1, 4000)
    assert rows[0]["text"] == text.strip()[:4000]
    assert len(rows[0]["text"]) > 200
