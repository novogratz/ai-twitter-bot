"""The account jobs: curator, engage, likes, pin, follow_engagers."""
import json

import pytest

from tests.helpers import FRESH, OWN_BEST, SearchPage, pin_rows, stop_requested, fresh


# --- 2026-06-07 PM: self-curated tracking ----------------------------------


def test_curator_lane_gate_and_pins(monkeypatch, tmp_path):
    """Only ON-LANE engagements count as evidence (FR-era rows classify
    'other' and are ignored); pinned handles always lead the tracked list."""
    from datetime import datetime
    from src.account import account_curator as ac
    now = datetime.now().isoformat()
    log_file = tmp_path / "log.csv"
    rows = []
    # 3 on-lane engagements with an EN markets author
    for i in range(3):
        rows.append(f'{now},reply,"your drawdown is just the market invoicing your FOMO {i}",https://x.com/goodfinance/status/12345{i},SEARCH,,market_trauma')
    # 4 FR-era engagements (classify "other") with a legacy author
    for i in range(4):
        rows.append(f'{now},reply,"très intéressant merci pour le partage {i}",https://x.com/legacyfr/status/2345{i},PROFILE,,')
    log_file.write_text("\n".join(rows) + "\n")
    monkeypatch.setattr(ac, "ENGAGEMENT_LOG_FILE", str(log_file))
    (tmp_path / "whitelist.json").write_text(json.dumps({"tiers": {}}))

    ac.run_curator_cycle()
    handles = ac.tracked_handles(limit=10)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo", "pins lead"
    assert "goodfinance" in handles, "on-lane author must be tracked"
    assert "legacyfr" not in handles, "FR-era 'other' engagements must not count"


def test_curator_promotion_quality_bar():
    """Following is a higher bar than tracking: spam-pattern handles (long
    digit runs) and thin evidence never reach the whitelist."""
    from src.account.account_curator import _promotable
    assert _promotable({"handle": "unusual_whales", "engagements": 9})
    assert not _promotable({"handle": "bisdianora24202", "engagements": 9}), "digit-run spam"
    assert not _promotable({"handle": "goodname", "engagements": 4}), "below promote floor"


# --- engage_bot ----------------------------------------------------------------


def test_engage_cycle_skips_likes_for_non_allowlisted_handles():
    """2026-06-17: engage_bot's reciprocity-like step calls
    visit_profile_and_like, which is gated by PROFILE_VISIT_ALLOWLIST
    (home/search-only mandate, 2026-06-07). Non-allowlisted handles return
    instantly after logging '[LIKE] profile visit blocked' — but the engage
    cycle still logged '[ENGAGE] Liking @X's latest tweets...' and slept
    3-5s between each, producing ~50s of paired noise per cycle. Same shape
    as PR #49's trusted-news skip: pre-filter by `_profile_visit_allowed`
    before the like step. The follow_account call above is intentionally
    NOT gated (mechanically required to click the Follow button)."""
    import inspect
    from src.account import engage_bot as eb

    src = inspect.getsource(eb.run_engage_cycle)
    # Pin: the cycle imports the allowlist gate and uses it to skip likes
    # for non-allowlisted handles before logging/sleeping.
    assert "_profile_visit_allowed" in src, \
        "engage cycle must pre-filter the like step by the profile allowlist"
    # Pin: the gate runs BEFORE visit_profile_and_like (i.e. the skip path
    # exists in the same function that calls the like primitive).
    gate_idx = src.find("_profile_visit_allowed")
    like_idx = src.find("visit_profile_and_like(username")
    assert 0 < gate_idx < like_idx, \
        "_profile_visit_allowed check must run before visit_profile_and_like"


def _dry_run_follow_path(monkeypatch):
    from src.guards import action_guard
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(action_guard, "can_follow", lambda *a, **k: (True, ""))
    monkeypatch.setattr(tc, "_quality_reject_recent", lambda *_: False)
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    return recorded


def test_dry_run_engage_cycle_leaves_followed_accounts_unchanged(monkeypatch, tmp_path):
    """#123: follow_account returned True on a dry run, so engage_bot stored
    handles it never followed and no later live cycle followed them."""
    from src.guards import action_guard
    from src.account import engage_bot
    from src.core import evolution_store
    from src.x import twitter_client as tc

    recorded = _dry_run_follow_path(monkeypatch)
    followed_file = tmp_path / "followed_accounts.json"
    followed_file.write_text(json.dumps(["already"]))
    monkeypatch.setattr(engage_bot, "_build_pool", lambda: ["already", "newcomer", "other"])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda pool: pool)
    monkeypatch.setattr(engage_bot, "_profile_visit_allowed", lambda *_: False)
    monkeypatch.setattr(engage_bot.time, "sleep", lambda *_: None)

    engage_bot.run_engage_cycle()

    assert set(json.loads(followed_file.read_text())) == {"already"}
    assert sorted(k["target"] for a, k in recorded if a == (action_guard.FOLLOW,)) == ["newcomer", "other"]
    assert all(k["dry_run"] for _, k in recorded)
    assert not tc.DRY_RUN_RECORDED


# --- like_bot ------------------------------------------------------------------


def _stub_like_browser(monkeypatch, tmp_path):
    from src.account import like_bot
    from src.x import safari, twitter_client

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(twitter_client.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(twitter_client.time, "sleep", lambda *_: None)
    requested = []

    def like_posts(n, wanted, page_ok, outcomes, deadline):
        requested.append(n)
        return outcomes

    monkeypatch.setattr(twitter_client, "_like_posts_on_page", like_posts)
    return requested


def test_live_strategy_cannot_raise_likes_per_cycle(monkeypatch, tmp_path):
    from src.account import like_bot

    strategy = tmp_path / "live_strategy.json"
    strategy.write_text(json.dumps({"caps": {"LIKE_BOT_PER_CYCLE": 500}}))
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "10")
    requested = _stub_like_browser(monkeypatch, tmp_path)

    like_bot.run_like_cycle()

    assert sum(requested) == 10


def test_like_caps_are_read_at_call_time(monkeypatch, tmp_path):
    from src.account import like_bot

    requested = _stub_like_browser(monkeypatch, tmp_path)
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "6")
    monkeypatch.setenv("LIKE_BOT_DAILY_CAP", "4")

    like_bot.run_like_cycle()

    assert sum(requested) == 4


def test_like_clicks_refused_after_stop(monkeypatch, tmp_path):
    import pytest
    from src.account import like_bot
    from src.guards.active_hours import OutsideActiveHours

    requested = _stub_like_browser(monkeypatch, tmp_path)
    stop_requested(monkeypatch)

    with pytest.raises(OutsideActiveHours):
        like_bot.run_like_cycle()
    assert requested == []


def test_like_count_survives_a_stop_between_batches(monkeypatch, tmp_path):
    from src.account import like_bot
    from src.guards.active_hours import OutsideActiveHours
    import pytest

    from src.x import twitter_client

    _stub_like_browser(monkeypatch, tmp_path)
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "10")

    def like_posts(n, wanted, page_ok, outcomes, deadline):
        outcomes.extend([twitter_client.LikeOutcome.LIKED] * 5)
        raise OutsideActiveHours("stop")

    monkeypatch.setattr(twitter_client, "_like_posts_on_page", like_posts)

    with pytest.raises(OutsideActiveHours):
        like_bot.run_like_cycle()
    assert like_bot._load_daily_state()["count"] == 5


# like_job writes through `like_tweet` for each like (issue #142).

FRESH_2 = "https://x.com/infra_two/status/2063500000000000202"
CACHED = "https://x.com/infra_three/status/2063500000000000203"
SHOWN_LIKED = "https://x.com/infra_four/status/2063500000000000204"
BLOCKED = "https://x.com/BlockedOne/status/2063500000000000205"
OWN = "https://x.com/TheAIShrink/status/2063500000000000206"
OWN_OTHER = "https://x.com/TheAIShrink/status/2063500000000000302"


def _like_rows(like_job):
    from src.guards import action_guard
    return [r for r in like_job["ledger"].rows if r["action"] == action_guard.LIKE]


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
    assert [r["target"] for r in _like_rows(like_job)] == [FRESH.lower(), FRESH_2.lower()]
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
    assert _like_rows(like_job) == []
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
    assert len(_like_rows(like_job)) == expected
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
    assert len(_like_rows(like_job)) == expected
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


def test_like_job_dry_run_opens_nothing(like_job, monkeypatch):
    from src.account import like_bot
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: pytest.fail("opened Safari"))
    monkeypatch.setattr(tc, "_page_posts", lambda *a: pytest.fail("read the page"))

    like_bot.run_like_cycle()

    assert _like_rows(like_job) == []


# --- pin_bot -------------------------------------------------------------------


def test_pin_rotation_url_ground_truth_and_stale_override():
    """2026-07-19: the pin never rotated. Root cause = 4th hit of the
    display-name-vs-handle family: pin_bot compared scraper `author` (the
    DISPLAY NAME) to BOT_HANDLE, filtering every own post. Pin: ownership
    must come from is_own_post (URL ground truth), and a pin older than
    PIN_MAX_AGE_DAYS must stop defending its slot via the 1.3x beat rule."""
    import inspect
    from src.account import pin_bot
    src = inspect.getsource(pin_bot.run_pin_cycle)
    assert "is_own_post" in src, "pin candidates must be filtered by URL ground truth"
    assert 'author != BOT_HANDLE' not in src and 'author and author !=' not in src, \
        "display-name-vs-handle compare must be gone"
    assert "PIN_MAX_AGE_DAYS" in src and "pin_is_stale" in src, \
        "a stale pin must rotate instead of defending with the 1.3x rule"
    assert pin_bot.MIN_LIKES_TO_PIN <= 2 or "PIN_MIN_LIKES" in inspect.getsource(pin_bot), \
        "likes floor must be reachable at this account size"


# pin_job writes through `pin_own_tweet` (issue #142).


@pytest.fixture
def pin_job(monkeypatch, tmp_path):
    """pin_job with a scripted profile scrape and its state in tmp_path."""
    from src.account import pin_bot

    monkeypatch.setattr(pin_bot.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pin_bot, "scrape_profile_tweets", lambda *a, **k: [
        {"url": OWN_OTHER, "likes": 3, "replies": 0, "text": "other post"},
        {"url": OWN_BEST, "likes": 9, "replies": 1, "text": "best post"},
        {"url": FRESH, "likes": 500, "replies": 9, "text": "not ours"},
    ])
    return tmp_path


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


def test_pin_job_dry_run_records_a_dry_run_row_without_spending_the_attempt(pin_job, monkeypatch,
                                                                           memory_ledger):
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

    rows = pin_rows(memory_ledger)
    assert [(r["target"], r["dry_run"]) for r in rows] == [(OWN_BEST.lower(), True)]
    assert memory_ledger.count(action_guard.PIN, action_guard.now_local().date()) == 0
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


# --- follow_engagers (Engagers from the ledger) -----------------------------


def test_engagers_are_debate_turn_authors_newest_first_then_the_frozen_file():
    import json
    from src.guards import action_guard
    from src.account import follow_engagers_bot as fe

    for author in ("oldfan", "newfan", "oldfan"):
        action_guard.record(action_guard.DEBATE_TURN, target=author)
    action_guard.record(action_guard.DEBATE_TURN, target="simulated", dry_run=True)
    action_guard.record(action_guard.REPLY, target=fresh("replied_to"))
    with open(fe.FROZEN_REPLIED_BACK.path, "w") as f:
        json.dump([fresh("agedout", minutes=91 * 24 * 60), fresh("frozenfan", n=1), "text:no url",
                   fresh("i", n=3), fresh("newfan", n=2)], f)

    assert fe._engager_handles() == ["oldfan", "newfan", "frozenfan"], \
        "the frozen file ages out with the ledger's 90 days; an /i/ URL names nobody"


def test_follow_engagers_lane_and_gate_bypass(monkeypatch, tmp_path):
    """2026-07-19 likes+follows push: (1) the engager quality path skips
    size/niche (behavior proves both; small engagers follow back at the
    highest rate) but KEEPS the English gate; (2) follow_engagers_bot pulls
    Engagers from the ledger's Debate turns (newest first), never retries an
    attempted handle, respects caps, and routes through follow_account
    with engager=True."""
    from src.x.twitter_client import _follow_quality_decision
    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "10000")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")
    monkeypatch.setenv("FOLLOW_REQUIRE_ENGLISH", "1")
    ok, _ = _follow_quality_decision(42, "just a person who likes computers", "Sam", False, engager=True)
    assert ok, "engager must bypass min-followers and niche gates"
    ok, why = _follow_quality_decision(42, "Analyse crypto et IA pour les investisseurs. Avec vous dans les marchés.", "Jean", False, engager=True)
    assert not ok and "non-English" in why, "engager must NOT bypass the English gate"
    ok, _ = _follow_quality_decision(42, "just a person", "Sam", False)
    assert not ok, "non-engager path keeps the size gate"

    from src.guards import action_guard as ag
    from src.account import follow_engagers_bot as fe
    for engager in ("oldguy", "business", "freshfan"):  # business: big-media skip
        ag.record(ag.DEBATE_TURN, target=engager)
    followed = []
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h, engager=False: followed.append((h, engager)) or True)
    monkeypatch.setattr(ag, "can_follow", lambda h, reciprocal=False: (True, ""))
    monkeypatch.setenv("ENABLE_FOLLOW_ENGAGERS", "1")
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_CYCLE", "1")
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_DAY", "10")
    fe.run_follow_engagers_cycle()
    assert followed == [("freshfan", True)], "newest engager first, media skipped, engager flag set"
    fe.run_follow_engagers_cycle()
    assert [h for h, _ in followed] == ["freshfan", "oldguy"], \
        "attempted handles never retried; next cycle takes the next engager"


def test_dry_run_follow_engagers_leaves_its_state_unchanged(monkeypatch, tmp_path):
    """A dry-run follow neither counts toward the day nor burns the Engager,
    and still stops the cycle at its per-cycle bound."""
    from src.account import follow_engagers_bot as fe

    recorded = _dry_run_follow_path(monkeypatch)
    state_file = tmp_path / "follow_engagers_state.json"
    monkeypatch.setattr(fe, "_engager_handles", lambda: ["fan1", "fan2", "fan3"])
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_CYCLE", "2")

    fe.run_follow_engagers_cycle()

    state = json.loads(state_file.read_text())
    assert state["count_today"] == 0 and state["attempted"] == []
    assert [k["target"] for _, k in recorded] == ["fan1", "fan2"]


def test_pin_job_actually_scheduled_and_transient_refusals_dont_burn(monkeypatch, tmp_path):
    """2026-07-28 nine-day health read — shipped features were dead:
    (1) pin_bot was the DEAD-IMPORT family again (imported + in the
    hot-reload map, scheduler.add_job never called, zero [PIN] lines ever)
    — pin that main.py registers pin_job; (2) follow_engagers burned 262
    candidates into its attempted-forever set via TRANSIENT policy
    refusals (the 3500 total-following ceiling) — a transient refusal must
    end the cycle WITHOUT burning candidates."""
    from main import build_scheduler
    assert build_scheduler().get_job("pin_job") is not None

    from src.guards import action_guard as ag
    from src.account import follow_engagers_bot as fe
    ag.record(ag.DEBATE_TURN, target="somefan")
    called = []
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h, engager=False: called.append(h) or True)
    monkeypatch.setattr("src.guards.action_guard.can_follow",
                        lambda h, reciprocal=False: (False, "total following ceiling reached (3500 >= 3500)"))
    monkeypatch.setenv("ENABLE_FOLLOW_ENGAGERS", "1")
    fe.run_follow_engagers_cycle()
    assert called == [], "transient refusal must not reach follow_account"
    st = fe._load_state()
    assert st.get("attempted", []) == [], \
        "transient policy refusal must NOT burn the candidate"
