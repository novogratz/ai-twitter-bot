"""The account jobs: curator, engage, followback, likes, pin, follow_engagers."""
import json
import os
import time
from datetime import datetime

import pytest

from tests.helpers import (FRESH, OWN_BEST, TORONTO, SearchPage, clock, pin_rows, stop_requested,
                           fresh)

# 02:30 on 2026-10-15 in Paris.
TORONTO_EVENING = datetime(2026, 10, 14, 20, 30, tzinfo=TORONTO)
# The day each clock gives: Toronto's, and the one the Mac stamped before #191.
STAMPED_DAYS = ["2026-10-14", "2026-10-15"]


@pytest.fixture
def mac_in_paris(monkeypatch):
    """The Mac's clock in Paris just after midnight, when it is still the
    evening before in Toronto (issue #191)."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Paris"
    time.tzset()
    clock(monkeypatch, TORONTO_EVENING)
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


# --- 2026-06-07 PM: self-curated tracking ----------------------------------


def test_curator_lane_gate_and_pins(monkeypatch, tmp_path, operator_folder):
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
    monkeypatch.setattr("src.core.config.ENGAGEMENT_LOG_FILE", str(log_file))
    (operator_folder / "whitelist.json").write_text(json.dumps({"tiers": {}}))

    ac.run_curator_cycle()
    handles = ac.tracked_handles(limit=10)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo", "pins lead"
    assert "goodfinance" in handles, "on-lane author must be tracked"
    assert "legacyfr" not in handles, "FR-era 'other' engagements must not count"


def test_a_negative_tracked_max_tracks_nobody(monkeypatch, tmp_path, settings_override):
    """#201: CURATOR_TRACKED_MAX has no floor, so an Account cannot set it in
    [limits]; a negative value read as scored[:-1] tracked all but one."""
    from datetime import datetime
    from src.account import account_curator as ac
    settings_override(CURATOR_TRACKED_MAX=-1)
    now = datetime.now().isoformat()
    rows = [f'{now},reply,"your drawdown is just the market invoicing your FOMO {i}",'
            f'https://x.com/{author}/status/12345{i},SEARCH,,market_trauma'
            for author in ("goodfinance", "otherfinance") for i in range(6)]
    log_file = tmp_path / "log.csv"
    log_file.write_text("\n".join(rows) + "\n")
    monkeypatch.setattr("src.core.config.ENGAGEMENT_LOG_FILE", str(log_file))

    ac.run_curator_cycle()

    handles = ac.tracked_handles(limit=10)
    assert "goodfinance" not in handles and "otherfinance" not in handles


def test_curator_never_tracks_nor_promotes_a_blocked_account(monkeypatch, tmp_path, operator_folder):
    """#188: the curator compared the BLOCKLIST by exact equality, so a
    handle holding a blocked token could reach the whitelist."""
    from datetime import datetime
    from src.account import account_curator as ac
    from src.guards import follow_policy
    from src.core import config
    monkeypatch.setattr(config, "BLOCKLIST", {"la pique"})
    now = datetime.now().isoformat()
    rows = [f'{now},reply,"your drawdown is just the market invoicing your FOMO {i}",'
            f'https://x.com/{author}/status/12345{i},SEARCH,,market_trauma'
            for author in ("la_pique_off", "goodfinance") for i in range(6)]
    log_file = tmp_path / "log.csv"
    log_file.write_text("\n".join(rows) + "\n")
    monkeypatch.setattr("src.core.config.ENGAGEMENT_LOG_FILE", str(log_file))
    (operator_folder / "whitelist.json").write_text(json.dumps({"tiers": {}}))

    ac.run_curator_cycle()

    assert "la_pique_off" not in ac.tracked_handles(limit=10)
    assert follow_policy.DISCOVERED.read() == ["goodfinance"]
    assert json.loads((operator_folder / "whitelist.json").read_text()) == {"tiers": {}}


def test_curator_promotion_quality_bar():
    """Following is a higher bar than tracking: spam-pattern handles (long
    digit runs) and thin evidence never reach the whitelist."""
    from src.account.account_curator import _promotable
    assert _promotable({"handle": "unusual_whales", "engagements": 9})
    assert not _promotable({"handle": "bisdianora24202", "engagements": 9}), "digit-run spam"
    assert not _promotable({"handle": "goodname", "engagements": 4}), "below promote floor"


@pytest.mark.parametrize("stamped, count, promoted", [
    ("2026-10-15", 3, []),              # the Mac's day, ahead of Toronto's: quota spent
    ("2026-10-14", 3, []),              # Toronto's day: quota spent
    ("2026-10-13", 3, ["deep_macro"]),  # yesterday: a fresh quota
])
def test_curator_promotion_quota_follows_the_toronto_day(mac_in_paris, settings_override, stamped, count,
                                                        promoted, operator_folder):
    """#191: the daily promotion quota, stamped by either clock, stays spent
    until the next Toronto day."""
    from src.account import account_curator as ac
    from src.guards import follow_policy

    settings_override(CURATOR_DISCOVERED_PER_DAY=3)
    (operator_folder / "whitelist.json").write_text(json.dumps({"tiers": {}}))
    doc = {"promotion_meta": {"date": stamped, "count": count}}
    cand = {"handle": "deep_macro", "engagements": 9, "score": 9.0, "weight": 1.0}

    ac._promote_to_whitelist([cand], doc)

    assert follow_policy.DISCOVERED.read() == promoted
    assert doc["promotion_meta"] == {"date": "2026-10-14", "count": count if not promoted else 1}


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
    from src.guards import action_guard, follow_policy

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(follow_policy, "judge", lambda *a, **k: follow_policy.ADMITTED)
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    return recorded


def test_dry_run_engage_cycle_leaves_followed_accounts_unchanged(monkeypatch, tmp_path, operator_folder):
    """#123: follow_account returned True on a dry run, so engage_bot stored
    handles it never followed and no later live cycle followed them."""
    from src.guards import action_guard
    from src.account import engage_bot
    from src.core import evolution_store
    from src.x import twitter_client as tc

    recorded = _dry_run_follow_path(monkeypatch)
    followed_file = tmp_path / "followed_accounts.json"
    followed_file.write_text(json.dumps(["already"]))
    (operator_folder / "whitelist.json").write_text(json.dumps({"tiers": {"tier1": ["newcomer", "other"]}}))
    monkeypatch.setattr(engage_bot, "_build_pool", lambda: ["already", "newcomer", "other"])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda pool: pool)
    monkeypatch.setattr(engage_bot, "_profile_visit_allowed", lambda *_: False)
    monkeypatch.setattr(engage_bot.time, "sleep", lambda *_: None)

    engage_bot.run_engage_cycle()

    assert set(json.loads(followed_file.read_text())) == {"already"}
    assert sorted(k["target"] for a, k in recorded if a == (action_guard.FOLLOW,)) == ["newcomer", "other"]
    assert all(k["dry_run"] for _, k in recorded)
    assert not tc.FollowOutcome.DRY_RUN


# --- like_bot ------------------------------------------------------------------


def _stub_like_browser(monkeypatch, tmp_path):
    from src.account import like_bot
    from src.x import safari, twitter_client

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(twitter_client.time, "sleep", lambda *_: None)
    requested = []

    def like_posts(n, wanted, page_ok, outcomes, deadline):
        requested.append(n)
        return outcomes

    monkeypatch.setattr(twitter_client, "_like_posts_on_page", like_posts)
    return requested


def test_like_caps_are_read_at_call_time(monkeypatch, tmp_path, settings_override):
    from src.account import like_bot

    requested = _stub_like_browser(monkeypatch, tmp_path)
    settings_override(LIKE_BOT_PER_CYCLE=6, LIKE_BOT_DAILY_CAP=4)

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


def test_like_count_survives_a_stop_between_batches(monkeypatch, tmp_path, settings_override):
    from src.account import like_bot
    from src.guards.active_hours import OutsideActiveHours
    import pytest

    from src.x import twitter_client

    _stub_like_browser(monkeypatch, tmp_path)
    settings_override(LIKE_BOT_PER_CYCLE=10)

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
    (3, 0, 3),        # LIKE_BOT_PER_CYCLE caps the cycle
    (40, 98, 2),      # the daily cap leaves 2
    (40, 100, 0),     # the daily cap is reached: nothing opens
])
def test_like_job_volume_stays_under_its_caps(like_job, settings_override, per_cycle, already_today,
                                              expected):
    """Criterion: no volume increase; the per-cycle and daily caps still
    bound the likes that ship."""
    from src.account import like_bot
    from src.guards import active_hours

    settings_override(LIKE_BOT_PER_CYCLE=per_cycle, LIKE_BOT_DAILY_CAP=100)
    like_bot._save_daily_state({"date": active_hours.today_iso(), "count": already_today})
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
    from src.account import like_bot
    from src.guards import active_hours

    like_bot._save_daily_state({"date": active_hours.today_iso(), "count": already_today})
    posts = [{"url": f"https://x.com/infra_{i}/status/{2063500000000000400 + i}", "liked": False}
             for i in range(20)]
    page = like_job["page"] = SearchPage(posts)

    like_bot.run_like_cycle()

    assert len(page.clicks) == expected


@pytest.mark.parametrize("stamped", STAMPED_DAYS)
def test_like_quota_reached_stays_reached_for_the_toronto_day(like_job, mac_in_paris, monkeypatch,
                                                             stamped):
    """#191: a Mac in Europe opened a second quota of likes in the Toronto
    evening. A quota reached today in Toronto stays reached, whichever clock
    stamped it, until the next Toronto day."""
    from src.account import like_bot

    like_bot._save_daily_state({"date": stamped, "count": 500})
    page = like_job["page"] = SearchPage(
        [{"url": "https://x.com/infra_1/status/2063500000000000401", "liked": False}])

    like_bot.run_like_cycle()

    assert page.clicks == []
    assert like_bot._load_daily_state() == {"date": "2026-10-14", "count": 500}
    clock(monkeypatch, datetime(2026, 10, 15, 10, tzinfo=TORONTO))
    assert like_bot._load_daily_state() == {"date": "2026-10-15", "count": 0}


@pytest.mark.parametrize("cycle_seconds, expected", [
    (None, 2),    # 30 s by default: clicks at 0 s and 20 s, none at 40 s
    (50.0, 3),    # read at each cycle
    (0.0, 0),     # time is up before the first like
])
def test_like_job_starts_no_like_after_its_cycle_deadline(like_job, monkeypatch, settings_override,
                                                          cycle_seconds, expected):
    """The walk holds the Safari lock: past LIKE_BOT_CYCLE_SECONDS it
    clicks nothing more, so the reply jobs get the browser back."""
    from src.account import like_bot
    from src.x import twitter_client as tc

    if cycle_seconds is not None:
        settings_override(LIKE_BOT_CYCLE_SECONDS=cycle_seconds)
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
    from src.x import safari, twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: pytest.fail("opened Safari"))
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
    from src.core import settings
    src = inspect.getsource(pin_bot.run_pin_cycle)
    assert "is_own_post" in src, "pin candidates must be filtered by URL ground truth"
    assert 'author != BOT_HANDLE' not in src and 'author and author !=' not in src, \
        "display-name-vs-handle compare must be gone"
    assert "PIN_MAX_AGE_DAYS" in src and "pin_is_stale" in src, \
        "a stale pin must rotate instead of defending with the 1.3x rule"
    assert settings.DECLARED["PIN_MIN_LIKES"].default <= 2, \
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


@pytest.mark.parametrize("stamped", STAMPED_DAYS)
def test_pin_attempt_spent_stays_spent_for_the_toronto_day(pin_job, mac_in_paris, monkeypatch,
                                                          stamped):
    """#191: today's pin attempt, stamped by either clock, is spent until
    the next Toronto day, and only until then."""
    from src.account import pin_bot

    monkeypatch.setenv("DRY_RUN", "0")
    pin_bot.PIN_STATE.write({"date": stamped})
    monkeypatch.setattr(pin_bot, "scrape_profile_tweets",
                        lambda *a, **k: pytest.fail("pinned twice the same Toronto day"))

    pin_bot.run_pin_cycle()

    clock(monkeypatch, datetime(2026, 10, 15, 10, tzinfo=TORONTO))
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
    from src.guards import action_guard, follow_policy

    for author in ("oldfan", "newfan", "oldfan"):
        action_guard.record(action_guard.DEBATE_TURN, target=author)
    action_guard.record(action_guard.DEBATE_TURN, target="simulated", dry_run=True)
    action_guard.record(action_guard.REPLY, target=fresh("replied_to"))
    with open(follow_policy.FROZEN_REPLIED_BACK.path, "w") as f:
        json.dump([fresh("agedout", minutes=91 * 24 * 60), fresh("frozenfan", n=1), "text:no url",
                   fresh("i", n=3), fresh("newfan", n=2)], f)

    assert follow_policy.engagers() == ["oldfan", "newfan", "frozenfan"], \
        "the frozen file ages out with the ledger's 90 days; an /i/ URL names nobody"


def test_follow_engagers_lane_and_gate_bypass(monkeypatch, tmp_path, settings_override):
    """2026-07-19 likes+follows push: (1) the engager quality path skips
    size/niche (behavior proves both; small engagers follow back at the
    highest rate) but KEEPS the English gate; (2) follow_engagers_bot pulls
    Engagers from the ledger's Debate turns (newest first), never retries an
    attempted handle, respects caps, and routes through follow_account,
    which finds the Engager itself (#173)."""
    from src.guards.follow_policy import _quality_decision as _follow_quality_decision
    from src.x.twitter_client import FollowOutcome
    settings_override(FOLLOW_MIN_FOLLOWERS=10000, FOLLOW_REQUIRE_NICHE=True, FOLLOW_REQUIRE_ENGLISH=True)
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
                        lambda h: followed.append(h) or FollowOutcome.FOLLOWED)
    settings_override(ENABLE_FOLLOW_ENGAGERS=True, FOLLOW_ENGAGERS_PER_CYCLE=1, FOLLOW_ENGAGERS_PER_DAY=10)
    fe.run_follow_engagers_cycle()
    assert followed == ["freshfan"], "newest engager first, media skipped"
    fe.run_follow_engagers_cycle()
    assert followed == ["freshfan", "oldguy"], \
        "attempted handles never retried; next cycle takes the next engager"


@pytest.mark.parametrize("stamped", STAMPED_DAYS)
def test_follow_engagers_cap_reached_stays_reached_for_the_toronto_day(mac_in_paris, monkeypatch,
                                                                      settings_override, stamped):
    """#191: the daily Engager follows, stamped by either clock, stay
    counted until the next Toronto day."""
    from src.account import follow_engagers_bot as fe
    from src.guards import follow_policy
    from src.x.twitter_client import FollowOutcome

    settings_override(ENABLE_FOLLOW_ENGAGERS=True, FOLLOW_ENGAGERS_PER_DAY=10)
    monkeypatch.setattr(follow_policy, "engagers", lambda: ["fan1"])
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h: pytest.fail("followed past the Toronto day's cap"))
    fe.STATE.write({"date": stamped, "count_today": 10, "attempted": []})

    fe.run_follow_engagers_cycle()

    assert fe._load_state()["count_today"] == 10
    followed = []
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h: followed.append(h) or FollowOutcome.FOLLOWED)
    clock(monkeypatch, datetime(2026, 10, 15, 10, tzinfo=TORONTO))
    fe.run_follow_engagers_cycle()
    assert followed == ["fan1"]


def test_dry_run_follow_engagers_leaves_its_state_unchanged(monkeypatch, tmp_path, settings_override):
    """A dry-run follow neither counts toward the day nor burns the Engager,
    and still stops the cycle at its per-cycle bound."""
    from src.account import follow_engagers_bot as fe
    from src.guards import follow_policy

    recorded = _dry_run_follow_path(monkeypatch)
    state_file = tmp_path / "follow_engagers_state.json"
    monkeypatch.setattr(follow_policy, "engagers", lambda: ["fan1", "fan2", "fan3"])
    settings_override(FOLLOW_ENGAGERS_PER_CYCLE=2)

    fe.run_follow_engagers_cycle()

    state = json.loads(state_file.read_text())
    assert state["count_today"] == 0 and state["attempted"] == []
    assert [k["target"] for _, k in recorded] == ["fan1", "fan2"]


def test_pin_job_actually_scheduled_and_transient_refusals_dont_burn(monkeypatch, tmp_path,
                                                                     settings_override):
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
    from src.x.twitter_client import FollowOutcome
    for fan in ("otherfan", "somefan"):
        ag.record(ag.DEBATE_TURN, target=fan)
    called = []
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h: called.append(h) or FollowOutcome.CAP_REACHED)
    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    fe.run_follow_engagers_cycle()
    assert called == ["somefan"], "a transient refusal ends the cycle"
    st = fe._load_state()
    assert st.get("attempted", []) == [], \
        "transient policy refusal must NOT burn the candidate"


def _follow_engagers_on(monkeypatch, settings_override, outcomes):
    """follow_engagers over fan1..fan3 with follow_account answering
    `outcomes` in turn; returns the handles it was asked to follow."""
    from src.account import follow_engagers_bot as fe
    from src.guards import follow_policy

    answers = iter(outcomes)
    asked = []
    settings_override(ENABLE_FOLLOW_ENGAGERS=True, FOLLOW_ENGAGERS_PER_CYCLE=2)
    monkeypatch.setattr(follow_policy, "engagers", lambda: ["fan1", "fan2", "fan3"])
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h: asked.append(h) or next(answers))
    fe.run_follow_engagers_cycle()
    return asked, fe._load_state()


@pytest.mark.parametrize("budget", ["TOO_SOON", "CAP_REACHED"])
def test_follow_engagers_ends_the_cycle_on_the_follow_budget(monkeypatch, settings_override, budget):
    """#172: the job read the cause from can_follow's message ("too soon",
    "cap reached", "ceiling"); it now reads the outcome's cause."""
    from src.x.twitter_client import FollowOutcome as F

    asked, state = _follow_engagers_on(monkeypatch, settings_override, [F.FOLLOWED, F[budget]])

    assert asked == ["fan1", "fan2"]
    assert state["attempted"] == ["fan1"] and state["count_today"] == 1


def test_follow_engagers_burns_a_candidate_on_any_other_outcome(monkeypatch, settings_override):
    from src.x.twitter_client import FollowOutcome as F

    asked, state = _follow_engagers_on(
        monkeypatch, settings_override, [F.QUALITY_REJECTED, F.ALREADY_FOLLOWED, F.REFUSED])

    assert asked == ["fan1", "fan2", "fan3"]
    assert sorted(state["attempted"]) == ["fan1", "fan2", "fan3"] and state["count_today"] == 0


def test_follow_engagers_keeps_the_candidate_the_real_spacing_refuses(monkeypatch, memory_ledger,
                                                                      tmp_path, settings_override):
    """Through the real chokepoint and policy: the spacing refuses before
    any page opens (conftest fails the test on open_url), and the Engager
    stays for a later cycle."""
    from src.core import config
    from src.guards import action_guard as ag
    from src.account import follow_engagers_bot as fe

    monkeypatch.setenv("DRY_RUN", "0")
    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    (tmp_path / "following_count.json").write_text(json.dumps({"count": 10}))
    ag.record(ag.FOLLOW, "earlier")
    ag.record(ag.DEBATE_TURN, "somefan")

    fe.run_follow_engagers_cycle()

    assert fe._load_state()["attempted"] == []
    assert [r["action"] for r in memory_ledger.rows] == [ag.FOLLOW, ag.DEBATE_TURN]


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_follow_engagers_stops_on_an_unreadable_whitelist_without_marking_a_candidate(
        monkeypatch, memory_ledger, tmp_path, settings_override, dry_run, operator_folder):
    """#172: judge refused on an unreadable whitelist.json and the job
    marked each Engager tried, about 200 in one cycle. The cycle now stops
    at the first candidate, reported as a failure, with no candidate marked,
    no page opened (conftest fails on open_url) and no ledger row."""
    from src.core import health
    from src.guards import action_guard as ag
    from src.account import follow_engagers_bot as fe

    monkeypatch.setenv("DRY_RUN", dry_run)
    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    (tmp_path / "following_count.json").write_text(json.dumps({"count": 10}))
    whitelist = operator_folder / "whitelist.json"
    whitelist.write_text('{"tiers": {"tier1": ["karp')
    for fan in ("fan1", "fan2", "fan3"):
        ag.record(ag.DEBATE_TURN, fan)
    failures = []
    monkeypatch.setattr(health, "record_failure", failures.append)
    monkeypatch.setattr(health, "record_success", lambda label: pytest.fail("cycle reported done"))

    fe.safe_run_follow_engagers_cycle()

    assert failures == ["follow_engagers"]
    assert fe._load_state()["attempted"] == []
    assert [r["action"] for r in memory_ledger.rows] == [ag.DEBATE_TURN] * 3
    assert whitelist.read_text() == '{"tiers": {"tier1": ["karp'


# --- followback ------------------------------------------------------------------


@pytest.fixture
def live_follow(monkeypatch, settings_override, memory_ledger, tmp_path):
    """The real follow chokepoint and policy, in the live whitelist mode,
    over a scripted browser: the tab shows `state["page"]`, a followers
    page listing `state["followers"]`, every profile answers
    `state["profile"]` to the Follow script and shows a big AI profile to
    the quality gate; `state["visits"]` lists the pages opened."""
    from src.core import config
    from src.x import safari, scraper, twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    settings_override(FOLLOW_WHITELIST_ONLY=True, FOLLOWBACK_BYPASS_WHITELIST=True)
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 0)
    monkeypatch.setattr(config, "FOLLOW_SPACING_JITTER_SECONDS", 0)
    monkeypatch.setattr(config, "FOLLOW_ACTION_JITTER_SECONDS", 0)
    (tmp_path / "following_count.json").write_text(json.dumps({"count": 10}))
    state = {"page": "/TheAIShrink/followers", "followers": [], "profile": "CLICKED",
             "visits": []}
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "open_url", lambda url, *a, **k: state["visits"].append(url) or True)
    monkeypatch.setattr(safari, "_run_js", lambda js, *a, **k: (
        json.dumps({"path": state["page"], "handles": state["followers"]})
        if "UserCell" in js else state["profile"]))
    monkeypatch.setattr(scraper, "_scrape_profile_quality",
                        lambda: {"followers": "50K", "bio": "AI investor", "name": "Fan"})
    return state


def _follow_outcomes(monkeypatch, module):
    """Spy on `module.follow_account`: each (handle, outcome) the real
    chokepoint returned to the job."""
    from src.x import twitter_client as tc

    seen = []
    real = tc.follow_account
    monkeypatch.setattr(module, "follow_account", lambda h: seen.append((h, real(h))) or seen[-1][1])
    return seen


def _no_follow_written(memory_ledger, tmp_path):
    assert memory_ledger.rows == []
    assert not (tmp_path / "followed_accounts.json").exists()
    assert not (tmp_path / "follow_quality_rejects.json").exists()


@pytest.fixture
def followback(monkeypatch, live_follow):
    """Live followback_job over the scripted followers page."""
    from src.account import followback_bot as fb
    from src.x import safari

    live_follow.update(followers=["Alreadyfan"], profile="ALREADY")
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(fb.time, "sleep", lambda *_: None)
    return fb, live_follow


def test_followback_never_revisits_an_account_found_already_followed(followback, memory_ledger,
                                                                     tmp_path):
    """#172: an account already followed never entered the followed
    accounts, so followback_job visited its profile every 20 minutes. The
    chokepoint records it now, without a ledger row, and the next cycle
    skips it."""
    fb, state = followback
    followers_page = "https://x.com/TheAIShrink/followers"

    fb.run_followback_cycle()
    assert state["visits"] == [followers_page, "https://x.com/Alreadyfan"]
    assert json.loads((tmp_path / "followed_accounts.json").read_text()) == ["Alreadyfan"]
    assert memory_ledger.rows == []

    fb.run_followback_cycle()
    assert state["visits"] == [followers_page, "https://x.com/Alreadyfan", followers_page]


def test_followback_never_spends_a_pick_on_an_invalid_handle(followback, monkeypatch, settings_override):
    """#172: an invalid handle took one of the cycle's picks before the
    policy refused it; the job drops it with the policy's own check."""
    fb, state = followback
    settings_override(FOLLOWBACK_CAP=1)
    monkeypatch.setattr(fb.random, "shuffle", lambda seq: None)
    state["followers"] = ["averyverylonghandle", "Realfan"]

    fb.run_followback_cycle()

    assert state["visits"] == ["https://x.com/TheAIShrink/followers", "https://x.com/Realfan"]


def test_followback_never_spends_a_pick_on_a_blocked_account(followback, monkeypatch, memory_ledger,
                                                             settings_override):
    """#188: without the job's filter, a Blocked follower stayed fresh every
    cycle and took a pick and a pause before the chokepoint refused it."""
    from src.core import config
    fb, state = followback
    monkeypatch.setattr(config, "BLOCKLIST", {"la pique"})
    settings_override(FOLLOWBACK_CAP=1)
    monkeypatch.setattr(fb.random, "shuffle", lambda seq: None)
    asked = _follow_outcomes(monkeypatch, fb)
    state.update(followers=["La_Pique_Off", "Realfan"], profile="CLICKED")

    fb.run_followback_cycle()

    assert [h for h, _ in asked] == ["Realfan"]
    assert state["visits"] == ["https://x.com/TheAIShrink/followers", "https://x.com/Realfan"]


def test_followback_records_a_follow_it_shipped(followback, memory_ledger, tmp_path):
    fb, state = followback
    state["profile"] = "CLICKED"

    fb.run_followback_cycle()

    assert json.loads((tmp_path / "followed_accounts.json").read_text()) == ["Alreadyfan"]
    assert [(r["action"], r["target"]) for r in memory_ledger.rows] == [("follow", "alreadyfan")]
    assert json.loads((tmp_path / "following_count.json").read_text())["count"] == 11


def test_followback_stops_on_an_unreadable_whitelist(followback, memory_ledger, monkeypatch,
                                                      operator_folder):
    """An unreadable guarded file stops the job that needs it: followback
    no longer logs a traceback per pick and reports the cycle a success."""
    from src.core import health

    fb, state = followback
    state["followers"] = ["Realfan", "Otherfan"]
    (operator_folder / "whitelist.json").write_text("{not json")
    failures = []
    monkeypatch.setattr(health, "record_failure", failures.append)
    monkeypatch.setattr(health, "record_success", lambda name: pytest.fail("cycle reported ok"))

    fb.safe_run_followback_cycle()

    assert failures == ["followback"]
    assert state["visits"] == ["https://x.com/TheAIShrink/followers"]
    assert memory_ledger.rows == []
    assert (operator_folder / "whitelist.json").read_text() == "{not json"


# --- #173: the policy finds the relation; a Stranger is never followed -------


def test_followback_never_follows_a_stranger_its_scrape_hands_over(followback, monkeypatch,
                                                                   memory_ledger, tmp_path):
    """#173: followback_job declared every scraped handle a follow-back, so a
    suggested account scraped with them would have been followed. The
    policy reads its own record of the followers: a handle the scrape never
    recorded is a Stranger, refused before its profile opens."""
    from src.x.twitter_client import FollowOutcome

    fb, state = followback
    monkeypatch.setattr(fb, "_scrape_followers_list", lambda max_handles=30: ["Suggested"])
    outcomes = _follow_outcomes(monkeypatch, fb)

    fb.run_followback_cycle()

    assert outcomes == [("Suggested", FollowOutcome.REFUSED)]
    assert state["visits"] == ["https://x.com/TheAIShrink/followers"]
    _no_follow_written(memory_ledger, tmp_path)


def test_followback_follows_no_one_off_the_followers_page(followback, monkeypatch, memory_ledger,
                                                          tmp_path):
    """#173 review: a login wall or a redirect left another page in the tab,
    and its profile links were recorded as followers and followed back."""
    fb, state = followback
    state.update(page="/i/flow/login", followers=["Walluser"])
    outcomes = _follow_outcomes(monkeypatch, fb)

    fb.run_followback_cycle()

    assert outcomes == []
    assert state["visits"] == ["https://x.com/TheAIShrink/followers"]
    assert not (tmp_path / "followers_seen.json").exists()
    _no_follow_written(memory_ledger, tmp_path)


def test_the_chokepoint_never_follows_a_stranger(live_follow, memory_ledger, tmp_path):
    """Whoever calls it, the manual follow skill included."""
    from src.x import twitter_client as tc

    assert tc.follow_account("notanengager") is tc.FollowOutcome.REFUSED
    assert live_follow["visits"] == []
    _no_follow_written(memory_ledger, tmp_path)


def test_follow_engagers_follows_an_engager_through_the_real_policy(live_follow, monkeypatch,
                                                                    memory_ledger, tmp_path,
                                                                    settings_override):
    """The policy finds the Engager in the ledger's Debate turns, lets it
    through the whitelist gate and skips the quality gate's size check."""
    from src.account import follow_engagers_bot as fe
    from src.guards import action_guard as ag
    from src.x import scraper

    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    monkeypatch.setattr(scraper, "_scrape_profile_quality",
                        lambda: {"followers": "12", "bio": "hi", "name": "Sam"})
    ag.record(ag.DEBATE_TURN, "SmallFan")

    fe.run_follow_engagers_cycle()

    assert live_follow["visits"] == ["https://x.com/smallfan"]
    assert [(r["action"], r["target"]) for r in memory_ledger.rows] == [
        (ag.DEBATE_TURN, "smallfan"), (ag.FOLLOW, "smallfan")]
    assert fe._load_state()["count_today"] == 1


def test_follow_engagers_opens_no_profile_of_a_followed_account(live_follow, monkeypatch,
                                                                memory_ledger, tmp_path,
                                                                settings_override):
    """#260: follow_engagers never read the followed accounts, so an
    Engager followed more than 30 days ago cost a profile visit every
    cycle. The ledger names it in lower case; the record keeps its case."""
    from src.account import follow_engagers_bot as fe
    from src.guards import action_guard as ag

    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h: pytest.fail(f"asked to follow @{h}"))
    (tmp_path / "followed_accounts.json").write_text(json.dumps(["SmallFan"]))
    ag.record(ag.DEBATE_TURN, "SmallFan")

    fe.run_follow_engagers_cycle()

    assert live_follow["visits"] == []
    assert [r["action"] for r in memory_ledger.rows] == [ag.DEBATE_TURN]


def test_follow_engagers_keeps_going_past_a_failed_pick(monkeypatch, settings_override):
    """#260: an unexpected error ended the cycle; it now costs the one pick,
    counted in the per-cycle bound, and the Engager stays for a later cycle.
    The cycle still reports the error to the health watchdog."""
    from src.account import follow_engagers_bot as fe
    from src.core import health
    from src.guards import follow_policy
    from src.x.twitter_client import FollowOutcome

    def follow(handle):
        asked.append(handle)
        if handle == "fan1":
            raise RuntimeError("osascript died")
        return FollowOutcome.FOLLOWED
    asked, failures = [], []
    settings_override(ENABLE_FOLLOW_ENGAGERS=True, FOLLOW_ENGAGERS_PER_CYCLE=2)
    monkeypatch.setattr(follow_policy, "engagers", lambda: ["fan1", "fan2", "fan3"])
    monkeypatch.setattr("src.x.twitter_client.follow_account", follow)
    monkeypatch.setattr(health, "record_failure", failures.append)
    monkeypatch.setattr(health, "record_success", lambda name: pytest.fail("cycle reported ok"))

    fe.safe_run_follow_engagers_cycle()

    state = fe._load_state()
    assert asked == ["fan1", "fan2"]
    assert state["attempted"] == ["fan2"] and state["count_today"] == 1
    assert failures == ["follow_engagers"]


def test_follow_engagers_failed_picks_count_in_the_per_cycle_bound(monkeypatch,
                                                                   settings_override):
    """#260 review: a pick that raises every time would otherwise open up
    to 200 profiles in one cycle."""
    from src.account import follow_engagers_bot as fe
    from src.guards import follow_policy

    def follow(handle):
        asked.append(handle)
        raise RuntimeError("judge_profile broke")
    asked = []
    settings_override(ENABLE_FOLLOW_ENGAGERS=True, FOLLOW_ENGAGERS_PER_CYCLE=2)
    monkeypatch.setattr(follow_policy, "engagers", lambda: [f"fan{i}" for i in range(10)])
    monkeypatch.setattr("src.x.twitter_client.follow_account", follow)

    with pytest.raises(RuntimeError, match="judge_profile broke"):
        fe.run_follow_engagers_cycle()

    state = fe._load_state()
    assert asked == ["fan0", "fan1"]
    assert state["attempted"] == [] and state["count_today"] == 0


@pytest.fixture
def engage(monkeypatch, live_follow):
    """Live engage_job over a scripted pool, its like step skipped."""
    from src.account import engage_bot as eb
    from src.core import evolution_store

    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda pool: pool)
    monkeypatch.setattr(eb, "_profile_visit_allowed", lambda *_: False)
    monkeypatch.setattr(eb.time, "sleep", lambda *_: None)
    return eb, live_follow


@pytest.mark.parametrize("whitelist_only", [True, False])
@pytest.mark.parametrize("bypass", [True, False])
def test_engage_never_tries_to_follow_a_stranger_from_the_feed(
        engage, monkeypatch, settings_override, memory_ledger, tmp_path, whitelist_only, bypass):
    """#173: engage_job's pool comes from the feeds; an account there with
    no relation to ours never reaches the chokepoint, whatever the mode."""
    eb, state = engage
    settings_override(FOLLOW_WHITELIST_ONLY=whitelist_only, FOLLOWBACK_BYPASS_WHITELIST=bypass)
    monkeypatch.setattr(eb, "_build_pool", lambda: ["feedaccount"])
    outcomes = _follow_outcomes(monkeypatch, eb)

    eb.run_engage_cycle()

    assert outcomes == []
    assert state["visits"] == []
    _no_follow_written(memory_ledger, tmp_path)


@pytest.mark.parametrize("whitelist_only", [True, False])
@pytest.mark.parametrize("bypass", [True, False])
def test_engage_leaves_its_followers_and_engagers_to_their_own_jobs(
        engage, monkeypatch, settings_override, memory_ledger, tmp_path, whitelist_only, bypass):
    """#173 review: engage_job followed any follower or Engager of its pool
    past the whitelist, the engager quality gate and the caps of
    followback_job and follow_engagers_job. It follows Seed accounts only."""
    from src.guards import action_guard as ag, follow_policy

    eb, state = engage
    settings_override(FOLLOW_WHITELIST_ONLY=whitelist_only, FOLLOWBACK_BYPASS_WHITELIST=bypass)
    follow_policy.record_followers(["poolfan"])
    ag.record(ag.DEBATE_TURN, "pooldebater")
    monkeypatch.setattr(eb, "_build_pool", lambda: ["poolfan", "pooldebater"])
    outcomes = _follow_outcomes(monkeypatch, eb)

    eb.run_engage_cycle()

    assert outcomes == []
    assert state["visits"] == []
    assert [r["action"] for r in memory_ledger.rows] == [ag.DEBATE_TURN]
    assert not (tmp_path / "followed_accounts.json").exists()


def test_engage_follows_a_seed_account_from_its_pool(engage, monkeypatch, memory_ledger,
                                                     operator_folder):
    from src.x.twitter_client import FollowOutcome

    eb, state = engage
    (operator_folder / "whitelist.json").write_text(json.dumps({"tiers": {"tier1": ["Graphseo"]}}))
    monkeypatch.setattr(eb, "_build_pool", lambda: ["Graphseo", "feedaccount"])
    outcomes = _follow_outcomes(monkeypatch, eb)

    eb.run_engage_cycle()

    assert outcomes == [("Graphseo", FollowOutcome.FOLLOWED)]
    assert state["visits"] == ["https://x.com/Graphseo"]
    assert [(r["action"], r["target"]) for r in memory_ledger.rows] == [("follow", "graphseo")]


# The followers page script, run by node against a page whose sidebar holds
# a "Who to follow" block, and whose user cells hold the account's avatar
# and name links, then a bio that may @mention other accounts.
_FOLLOWERS_PAGE_JS = r"""
function El(tag, attrs, kids) { this.tag = tag; this.attrs = attrs; this.kids = kids || []; }
El.prototype.getAttribute = function(n) { return n in this.attrs ? this.attrs[n] : null; };
El.prototype.all = function() {
    var out = [];
    this.kids.forEach(function(k) { out.push(k); out.push.apply(out, k.all()); });
    return out;
};
El.prototype.querySelectorAll = function(sel) {
    return this.all().filter(function(e) {
        if (sel === '[data-testid="primaryColumn"]') return e.attrs['data-testid'] === 'primaryColumn';
        if (sel === '[data-testid="UserCell"]') return e.attrs['data-testid'] === 'UserCell';
        if (sel === 'a[role="link"][href^="/"]')
            return e.tag === 'a' && e.attrs.role === 'link' && (e.attrs.href || '').indexOf('/') === 0;
        throw new Error('unsupported selector ' + sel);
    });
};
El.prototype.querySelector = function(sel) { return this.querySelectorAll(sel)[0] || null; };
function link(href) { return new El('a', {role: 'link', href: href}); }
function cell(handle, mentions) {
    var bio = new El('div', {}, (mentions || []).map(function(m) { return link('/' + m); }));
    return new El('div', {'data-testid': 'UserCell'}, [link('/' + handle), link('/' + handle), bio]);
}
var nav = new El('header', {}, [link('/home'), link('/explore'), link('/TheAIShrink')]);
var sidebar = new El('div', {'data-testid': 'sidebarColumn'}, [
    new El('aside', {'aria-label': 'Who to follow'}, [cell('suggested_one'), cell('suggested_two')])]);
"""


def _followers_page(primary_column: bool = True, path: str = "/TheAIShrink/followers") -> str:
    column = ("new El('div', {'data-testid': 'primaryColumn'}, ["
              "link('/TheAIShrink'), link('/TheAIShrink/followers'), "
              "cell('fan_one', ['mentioned_one']), cell('fan_two'), cell('xkprz9821'), "
              "cell('fan_one')])") if primary_column else "null"
    return _FOLLOWERS_PAGE_JS + f"""
var parts = [nav, {column}, sidebar].filter(Boolean);
var page = new El('body', {{}}, parts);
var location = {{pathname: {json.dumps(path)}}};
var document = {{
    querySelector: function(s) {{ return page.querySelector(s); }},
    querySelectorAll: function(s) {{ return page.querySelectorAll(s); }}
}};
"""


def _run_followers_script(monkeypatch, page_js):
    import shutil
    import subprocess
    from src.x import safari

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the followers page script cannot be run")

    def run_js(js, *a, **k):
        program = page_js + f"\nconsole.log(eval({json.dumps(js)}));"
        res = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=20)
        assert res.returncode == 0, res.stderr
        return res.stdout.strip()
    monkeypatch.setattr(safari, "_run_js", run_js)


def test_the_followers_scrape_reads_the_account_of_each_primary_column_cell(monkeypatch,
                                                                           tmp_path):
    """#173: the scrape took every profile link of the page, so the "Who to
    follow" block, and the @mentions of a follower's bio, would have passed
    for followers. It reads the first profile link of each user cell of the
    primary column, and records only the real-looking handles."""
    from src.account import followback_bot as fb
    from src.guards import follow_policy

    _run_followers_script(monkeypatch, _followers_page())

    assert fb._scrape_followers_list(50) == ["fan_one", "fan_two"]
    assert set(json.loads((tmp_path / "followers_seen.json").read_text())) == {"fan_one", "fan_two"}
    for handle in ("suggested_one", "mentioned_one", "xkprz9821"):
        assert follow_policy.relation(handle) is follow_policy.Relation.STRANGER, handle


@pytest.mark.parametrize("page", [
    _followers_page(primary_column=False),
    _followers_page(path="/i/flow/login"),
    _followers_page(path="/someoneelse/followers"),
    _followers_page(path="/TheAIShrink/following"),
])
def test_the_followers_scrape_reads_nothing_off_our_followers_page(monkeypatch, tmp_path, page):
    """A redirect, a login wall or a failed page load leaves another page in
    the tab: its accounts are no followers of ours."""
    from src.account import followback_bot as fb

    _run_followers_script(monkeypatch, page)

    assert fb._scrape_followers_list(50) == []
    assert not (tmp_path / "followers_seen.json").exists()


def test_the_followers_scrape_accepts_a_trailing_slash_and_any_case(monkeypatch, tmp_path):
    from src.account import followback_bot as fb

    _run_followers_script(monkeypatch, _followers_page(path="/theaishrink/followers/"))

    assert fb._scrape_followers_list(50) == ["fan_one", "fan_two"]
