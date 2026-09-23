"""The account jobs: curator, engage, likes, pin, follow_engagers."""
import json

import pytest

from tests.helpers import _stop_requested, fresh


# --- 2026-06-07 PM: self-curated tracking ----------------------------------


@pytest.mark.usefixtures("isolate_dedup")
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
    monkeypatch.setattr(ac, "TARGETS_LOG_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(ac, "WHITELIST_FILE", str(tmp_path / "wl.json"))
    monkeypatch.setattr(ac, "TRACKED_FILE", str(tmp_path / "tracked.json"))
    (tmp_path / "wl.json").write_text(json.dumps({"tiers": {}}))

    ac.run_curator_cycle()
    handles = ac.tracked_handles(limit=10)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo", "pins lead"
    assert "goodfinance" in handles, "on-lane author must be tracked"
    assert "legacyfr" not in handles, "FR-era 'other' engagements must not count"


@pytest.mark.usefixtures("isolate_dedup")
def test_curator_promotion_quality_bar():
    """Following is a higher bar than tracking: spam-pattern handles (long
    digit runs) and thin evidence never reach the whitelist."""
    from src.account.account_curator import _promotable
    assert _promotable({"handle": "unusual_whales", "engagements": 9})
    assert not _promotable({"handle": "bisdianora24202", "engagements": 9}), "digit-run spam"
    assert not _promotable({"handle": "goodname", "engagements": 4}), "below promote floor"


# --- engage_bot ----------------------------------------------------------------


@pytest.mark.usefixtures("isolate_dedup")
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
    monkeypatch.setattr(engage_bot, "FOLLOWED_FILE", str(followed_file))
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
    monkeypatch.setattr(like_bot, "LIKE_BOT_STATE_FILE", str(tmp_path / "like_state.json"))
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
    from src.core import config
    from src.account import like_bot

    strategy = tmp_path / "live_strategy.json"
    strategy.write_text(json.dumps({"caps": {"LIKE_BOT_PER_CYCLE": 500}}))
    monkeypatch.setattr(config, "_LIVE_STRATEGY_FILE", str(strategy))
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
    _stop_requested(monkeypatch)

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


# --- pin_bot -------------------------------------------------------------------


@pytest.mark.usefixtures("isolate_dedup")
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


# --- follow_engagers (Engagers from the ledger) -----------------------------


def test_engagers_are_debate_turn_authors_newest_first_then_the_frozen_file():
    import json
    from src.guards import action_guard
    from src.account import follow_engagers_bot as fe

    for author in ("oldfan", "newfan", "oldfan"):
        action_guard.record(action_guard.DEBATE_TURN, target=author)
    action_guard.record(action_guard.DEBATE_TURN, target="simulated", dry_run=True)
    action_guard.record(action_guard.REPLY, target=fresh("replied_to"))
    with open(fe.FROZEN_REPLIED_BACK_FILE, "w") as f:
        json.dump([fresh("agedout", minutes=91 * 24 * 60), fresh("frozenfan", n=1), "text:no url",
                   fresh("i", n=3), fresh("newfan", n=2)], f)

    assert fe._engager_handles() == ["oldfan", "newfan", "frozenfan"], \
        "the frozen file ages out with the ledger's 90 days; an /i/ URL names nobody"


@pytest.mark.usefixtures("isolate_dedup")
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
    monkeypatch.setattr(fe, "STATE_FILE", str(tmp_path / "fe_state.json"))
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
    monkeypatch.setattr(fe, "STATE_FILE", str(state_file))
    monkeypatch.setattr(fe, "_engager_handles", lambda: ["fan1", "fan2", "fan3"])
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_CYCLE", "2")

    fe.run_follow_engagers_cycle()

    state = json.loads(state_file.read_text())
    assert state["count_today"] == 0 and state["attempted"] == []
    assert [k["target"] for _, k in recorded] == ["fan1", "fan2"]


@pytest.mark.usefixtures("isolate_dedup")
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
    monkeypatch.setattr(fe, "STATE_FILE", str(tmp_path / "fe_state.json"))
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
