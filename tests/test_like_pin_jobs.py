"""like_job and pin_job write through their chokepoints (issue #142):
`like_tweet` for each like, `pin_own_tweet` for the pin."""
import pytest

SEARCH = "https://x.com/search?q=gpu&f=live"
FRESH = "https://x.com/infra_one/status/2063500000000000201"
FRESH_2 = "https://x.com/infra_two/status/2063500000000000202"
CACHED = "https://x.com/infra_three/status/2063500000000000203"
SHOWN_LIKED = "https://x.com/infra_four/status/2063500000000000204"
BLOCKED = "https://x.com/BlockedOne/status/2063500000000000205"
OWN = "https://x.com/TheAIShrink/status/2063500000000000206"
OWN_BEST = "https://x.com/TheAIShrink/status/2063500000000000301"
OWN_OTHER = "https://x.com/TheAIShrink/status/2063500000000000302"


class SearchPage:
    """Answers `_page_posts` like `_POSTS_JS` would on a search page."""

    def __init__(self, posts, page=SEARCH):
        self.page = page
        self.posts = [dict(p) for p in posts]
        self.clicks = []
        self.click_sticks = True
        self.stop_after_clicks = None
        self.on_click = lambda: None

    def __call__(self, mode, target_id=""):
        from src.guards.active_hours import OutsideActiveHours
        from src.x import x_urls

        if mode == "list":
            return {"page": self.page, "posts": [p["url"] for p in self.posts]}
        if mode == "press" and self.stop_after_clicks is not None \
                and len(self.clicks) >= self.stop_after_clicks:
            raise OutsideActiveHours("stop requested")
        post = next((p for p in self.posts if x_urls.status_id(p["url"]) == target_id), None)
        if post is None:
            return {"url": "", "result": "failed"}
        if post["liked"]:
            return {"url": post["url"], "result": "already_liked"}
        if mode != "press":
            return {"url": post["url"], "result": "not_liked"}
        self.clicks.append(post["url"])
        post["liked"] = self.click_sticks
        self.on_click()
        return {"url": post["url"], "result": "clicked"}


@pytest.fixture
def like_job(monkeypatch, tmp_path):
    """Live like_job on a scripted search page; the real walk and like_tweet run."""
    from src.account import like_bot
    from src.x import safari, twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    for name in ("LIKE_BOT_PER_CYCLE", "LIKE_BOT_DAILY_CAP", "LIKE_BOT_CYCLE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(like_bot, "LIKE_BOT_STATE_FILE", str(tmp_path / "like_state.json"))
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tc, "_liked_cache_path", lambda: str(tmp_path / "liked_tweets.json"))
    state = {"page": SearchPage([]), "closed": 0}
    monkeypatch.setattr(tc, "_page_posts", lambda *a: state["page"](*a))

    def close_front_tab():
        state["closed"] += 1
    monkeypatch.setattr(safari, "close_front_tab", close_front_tab)
    return state


def _like_rows():
    from src.guards import action_guard
    return [r for r in action_guard._load_ledger() if r["action"] == action_guard.LIKE]


def test_like_job_likes_through_like_tweet_and_counts_only_liked(like_job, monkeypatch):
    """Criterion: like_job inherits the liked cache, the Blocked account
    refusal and the page check of like_tweet, and counts LIKED only."""
    from src.account import like_bot
    from src.core import config
    from src.x import twitter_client as tc

    monkeypatch.setattr(config, "BLOCKLIST", {"blockedone"})
    tc._mark_liked(CACHED)
    page = like_job["page"] = SearchPage([
        {"url": OWN, "liked": False},
        {"url": BLOCKED, "liked": False},
        {"url": CACHED, "liked": False},
        {"url": SHOWN_LIKED, "liked": True},
        {"url": FRESH, "liked": False},
        {"url": FRESH_2, "liked": False},
    ])
    through = []
    real_like_tweet = tc.like_tweet
    monkeypatch.setattr(tc, "like_tweet", lambda url: through.append(url) or real_like_tweet(url))

    like_bot.run_like_cycle()

    assert through == [BLOCKED, CACHED, SHOWN_LIKED, FRESH, FRESH_2]
    assert page.clicks == [FRESH, FRESH_2]
    assert [r["target"] for r in _like_rows()] == [FRESH.lower(), FRESH_2.lower()]
    assert like_bot._load_daily_state()["count"] == 2


def test_like_job_counts_an_unconfirmed_click_toward_its_cap_without_a_ledger_row(like_job):
    """A click the page does not confirm may have landed on X: it counts
    toward like_job's daily cap, but it is not a shipped like, so it has no
    ledger row. It ends the walk."""
    from src.account import like_bot

    page = like_job["page"] = SearchPage([{"url": FRESH, "liked": False},
                                          {"url": FRESH_2, "liked": False}])
    page.click_sticks = False

    like_bot.run_like_cycle()

    assert page.clicks == [FRESH]
    assert _like_rows() == []
    assert like_bot._load_daily_state()["count"] == 1


def test_like_job_likes_nothing_off_the_search_page(like_job):
    from src.account import like_bot

    page = like_job["page"] = SearchPage([{"url": FRESH, "liked": False}],
                                         page="https://x.com/home")

    like_bot.run_like_cycle()

    assert page.clicks == []
    assert like_bot._load_daily_state()["count"] == 0


@pytest.mark.parametrize("per_cycle, already_today, expected", [
    ("3", 0, 3),        # LIKE_BOT_PER_CYCLE caps the cycle
    ("40", 98, 2),      # the daily cap leaves 2
    ("40", 100, 0),     # the daily cap is reached: nothing opens
])
def test_like_job_volume_stays_under_its_caps(like_job, monkeypatch, per_cycle, already_today, expected):
    """Criterion: no volume increase; the per-cycle and daily caps still
    bound the likes that ship."""
    from datetime import date
    from src.account import like_bot

    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", per_cycle)
    monkeypatch.setenv("LIKE_BOT_DAILY_CAP", "100")
    like_bot._save_daily_state({"date": date.today().isoformat(), "count": already_today})
    posts = [{"url": f"https://x.com/infra_{i}/status/{2063500000000000400 + i}", "liked": False}
             for i in range(10)]
    page = like_job["page"] = SearchPage(posts)

    like_bot.run_like_cycle()

    assert len(page.clicks) == expected
    assert len(_like_rows()) == expected
    assert like_bot._load_daily_state()["count"] == already_today + expected


@pytest.mark.parametrize("already_today, expected", [
    (0, 10),      # LIKE_BOT_PER_CYCLE defaults to 10
    (497, 3),     # LIKE_BOT_DAILY_CAP defaults to 500
])
def test_like_job_default_caps(like_job, already_today, expected):
    from datetime import date
    from src.account import like_bot

    like_bot._save_daily_state({"date": date.today().isoformat(), "count": already_today})
    posts = [{"url": f"https://x.com/infra_{i}/status/{2063500000000000400 + i}", "liked": False}
             for i in range(20)]
    page = like_job["page"] = SearchPage(posts)

    like_bot.run_like_cycle()

    assert len(page.clicks) == expected


@pytest.mark.parametrize("cycle_seconds, expected", [
    (None, 2),    # 30 s by default: clicks at 0 s and 20 s, none at 40 s
    ("50", 3),    # read from the environment at each cycle
    ("0", 0),     # time is up before the first like
])
def test_like_job_starts_no_like_after_its_cycle_deadline(like_job, monkeypatch, cycle_seconds, expected):
    """The walk holds the Safari lock: past LIKE_BOT_CYCLE_SECONDS it
    clicks nothing more, so the reply jobs get the browser back."""
    from src.account import like_bot
    from src.x import twitter_client as tc

    if cycle_seconds is not None:
        monkeypatch.setenv("LIKE_BOT_CYCLE_SECONDS", cycle_seconds)
    clock = [1000.0]
    monkeypatch.setattr(tc.time, "monotonic", lambda: clock[0])
    posts = [{"url": f"https://x.com/infra_{i}/status/{2063500000000000400 + i}", "liked": False}
             for i in range(5)]
    page = like_job["page"] = SearchPage(posts)
    page.on_click = lambda: clock.__setitem__(0, clock[0] + 20)

    like_bot.run_like_cycle()

    assert len(page.clicks) == expected
    assert len(_like_rows()) == expected
    assert like_bot._load_daily_state()["count"] == expected
    assert like_job["closed"] == 1


def test_like_job_counts_shipped_likes_when_a_stop_ends_the_walk(like_job):
    """A stop mid-walk keeps the likes already clicked in the daily count
    and still closes the search tab."""
    from src.account import like_bot
    from src.guards.active_hours import OutsideActiveHours

    page = like_job["page"] = SearchPage([{"url": FRESH, "liked": False},
                                          {"url": FRESH_2, "liked": False}])
    page.stop_after_clicks = 1

    with pytest.raises(OutsideActiveHours):
        like_bot.run_like_cycle()

    assert page.clicks == [FRESH]
    assert like_bot._load_daily_state()["count"] == 1
    assert like_job["closed"] == 1


def test_like_tweet_reads_and_clicks_under_the_safari_lock(like_job, monkeypatch):
    """like_tweet takes the Safari lock itself, so a caller that forgot it
    cannot interleave its click with another job's browser work."""
    from src.x import safari, twitter_client as tc

    held = []

    class RecordingLock:
        def __enter__(self):
            held.append(True)

        def __exit__(self, *exc):
            held.pop()

    monkeypatch.setattr(safari, "_safari_lock", RecordingLock())
    page = like_job["page"] = SearchPage([{"url": FRESH, "liked": False}])
    seen = []
    monkeypatch.setattr(tc, "_page_posts", lambda *a: seen.append(bool(held)) or page(*a))

    assert tc.like_tweet(FRESH) is tc.LikeOutcome.LIKED
    assert seen == [True, True]
    assert held == []


def test_like_job_dry_run_opens_nothing(like_job, monkeypatch):
    from src.account import like_bot
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: pytest.fail("opened Safari"))
    monkeypatch.setattr(tc, "_page_posts", lambda *a: pytest.fail("read the page"))

    like_bot.run_like_cycle()

    assert _like_rows() == []


# --- pin_job ---------------------------------------------------------------

@pytest.fixture
def pin_job(monkeypatch, tmp_path):
    """pin_job with a scripted profile scrape and its state in tmp_path."""
    from src.account import pin_bot

    monkeypatch.setattr(pin_bot, "PIN_HISTORY_FILE", str(tmp_path / "pin_history.json"))
    monkeypatch.setattr(pin_bot, "PIN_STATE_FILE", str(tmp_path / "pin_daily_state.json"))
    monkeypatch.setattr(pin_bot.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pin_bot, "scrape_profile_tweets", lambda *a, **k: [
        {"url": OWN_OTHER, "likes": 3, "replies": 0, "text": "other post"},
        {"url": OWN_BEST, "likes": 9, "replies": 1, "text": "best post"},
        {"url": FRESH, "likes": 500, "replies": 9, "text": "not ours"},
    ])
    return tmp_path


def _pin_rows():
    from src.guards import action_guard
    return [r for r in action_guard._load_ledger() if r["action"] == action_guard.PIN]


@pytest.mark.parametrize("shipped", [True, False])
def test_pin_job_pins_through_pin_own_tweet(pin_job, monkeypatch, shipped):
    """Criterion: pin_job pins through the chokepoint. A live attempt spends
    the day whatever its outcome (one attempt per day); only a shipped pin
    enters the history."""
    from src.account import pin_bot
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    calls = []
    monkeypatch.setattr(tc, "pin_own_tweet", lambda url: calls.append(url) or shipped)

    pin_bot.run_pin_cycle()

    assert calls == [OWN_BEST]
    assert pin_bot._already_ran_today()
    assert (pin_bot._load_history().get("pinned") == [OWN_BEST]) is shipped


def test_pin_job_dry_run_records_a_dry_run_row_without_spending_the_attempt(pin_job, monkeypatch):
    """Criterion: a dry run writes a dry-run ledger row and leaves today's
    live attempt unspent. It marks its own day, so the next hourly run
    neither scrapes the profile nor records again. conftest fails the test
    if Safari is driven."""
    from src.account import pin_bot
    from src.guards import action_guard

    monkeypatch.setenv("DRY_RUN", "1")

    pin_bot.run_pin_cycle()
    monkeypatch.setattr(pin_bot, "scrape_profile_tweets",
                        lambda *a, **k: pytest.fail("scraped again the same day"))
    pin_bot.run_pin_cycle()

    rows = _pin_rows()
    assert [(r["target"], r["dry_run"]) for r in rows] == [(OWN_BEST.lower(), True)]
    assert action_guard.count_today(action_guard.PIN) == 0
    assert pin_bot._load_history().get("pinned", []) == []
    assert pin_bot._already_ran_today()
    monkeypatch.setenv("DRY_RUN", "0")
    assert not pin_bot._already_ran_today()


def test_pin_job_dry_run_without_a_candidate_leaves_the_live_attempt(pin_job, monkeypatch):
    from src.account import pin_bot

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(pin_bot, "scrape_profile_tweets", lambda *a, **k: [
        {"url": OWN_BEST, "likes": 0, "replies": 0, "text": "no likes yet"}])

    pin_bot.run_pin_cycle()

    assert pin_bot._already_ran_today()
    monkeypatch.setenv("DRY_RUN", "0")
    assert not pin_bot._already_ran_today()


def _scripted_pin_js(monkeypatch, steps):
    """Live pin_own_tweet with each osascript call answering the next step."""
    from src.x import safari, twitter_client as tc

    answers = iter(steps)

    class Done:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: Done(next(answers)))


@pytest.mark.parametrize("steps, shipped", [
    (["MORE_CLICKED", "PIN_CLICKED", "CONFIRMED"], True),
    (["MORE_CLICKED", "PIN_CLICKED", "NO_CONFIRM"], False),
    (["MORE_CLICKED", "PIN_NOT_FOUND_4"], False),
    (["NO_ARTICLE"], False),
    (["MORE_CLICKED", "PIN_CLICKED", ""], False),
])
def test_pin_own_tweet_records_only_a_shipped_pin(monkeypatch, steps, shipped):
    """Log only what shipped: one ledger row when the confirm dialog was
    clicked, none when a step failed or no confirm dialog appeared. A pin
    is not a profile publication."""
    from src.guards import action_guard
    from src.x import twitter_client as tc

    _scripted_pin_js(monkeypatch, steps)

    assert tc.pin_own_tweet(OWN_BEST) is shipped
    assert [r["target"] for r in _pin_rows()] == ([OWN_BEST.lower()] if shipped else [])
    assert action_guard.profile_count_today() == 0
