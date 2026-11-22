"""Fresh ordinary sources stay bounded through drafting and final submission."""
from datetime import datetime, timedelta

import pytest

from src.core import account, engagement_log
from src.guards import replied_store, reply_admission, reply_budget, reply_selection, watch_curation
from src.replies import reply_pipeline as pipeline
from src.replies.reply_generator import Generation, Outcome
from src.x import safari, twitter_client as tc, x_urls
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, clock


NOW = datetime(2026, 11, 21, 12, tzinfo=TORONTO)
SOURCE = "This AI model is finally working."
DRAFT = "The model is faster, but the evidence still needs a stronger baseline."


def parent(seconds, author="builder"):
    at = NOW - timedelta(seconds=seconds)
    sid = (int(at.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22
    return f"https://x.com/{author}/status/{sid}"


@pytest.fixture(autouse=True)
def for_you_mode(monkeypatch, settings_override, memory_ledger):
    clock(monkeypatch, NOW)
    settings_override(REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_FOR_YOU_FIRST=True, REPLY_INVITED_ONLY=True,
                      REPLY_MANUAL_ORDINARY=False, DIRECT_REPLY_MAX_AGE_MINUTES=60,
                      MAX_REPLIES_PER_DAY=1400, MIN_SECONDS_BETWEEN_REPLIES=8,
                      REPLY_JITTER_SECONDS=0)
    monkeypatch.setattr(reply_selection, "_sources", {})
    monkeypatch.setattr(reply_selection.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(pipeline, "_skipped", {})
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: [])


@pytest.mark.parametrize("seconds,allowed", [(-1, False), (0, True), (1799, True),
                                             (3599, True), (3600, True), (3601, False), (7200, False)])
def test_source_and_parent_admission_share_the_configured_deadline(seconds, allowed):
    url = parent(seconds)
    assert (reply_selection.basic_refusal(url, SOURCE) == "") is allowed
    verdict = reply_admission.judge_parent(url)
    assert bool(verdict) is allowed
    if not allowed:
        assert verdict.refusal is reply_admission.Refusal.STALE_CANDIDATE
        assert "60 minutes" in verdict.reason
    assert not replied_store.load_replied() and reply_budget.entries() == {}


def test_unknown_timestamp_is_not_a_fresh_source():
    url = "https://x.com/builder/status/" + "9" * 100
    assert x_urls.age(url, NOW) is None
    assert reply_selection.freshness_refusal(url)
    assert reply_admission.judge_parent(url).refusal is reply_admission.Refusal.STALE_CANDIDATE


@pytest.mark.parametrize("configured,seconds,allowed", [(10, 600, True), (10, 601, False),
                                                        (240, 3600, True), (240, 3601, False)])
def test_tighter_limit_is_kept_and_longer_config_cannot_exceed_one_hour(settings_override, configured, seconds, allowed):
    settings_override(DIRECT_REPLY_MAX_AGE_MINUTES=configured)
    assert bool(reply_admission.judge_parent(parent(seconds))) is allowed


@pytest.mark.parametrize("disabled", ["REPLY_FOR_YOU_FIRST", "REPLY_BROAD_DISCOVERY", "REPLY_CURATED_MODE"])
def test_freshness_rule_does_not_change_other_modes(settings_override, disabled):
    settings_override(**{disabled: False, "DIRECT_REPLY_MAX_AGE_MINUTES": 5})
    url = parent(7200)
    assert reply_selection.freshness_refusal(url) == ""
    assert reply_selection.basic_refusal(url, SOURCE) == ""
    assert reply_admission.judge_parent(url)


def test_watched_sources_keep_their_existing_first_minute_deadline(watched_account):
    author = account.current().auto_engage_handles[0]
    assert reply_selection.freshness_refusal(parent(59, author)) == ""
    assert watch_curation.fresh(parent(59, author))
    assert reply_selection.freshness_refusal(parent(61, author)) == ""
    assert not watch_curation.fresh(parent(61, author))


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("pipelined", [False, True])
def test_old_sources_cannot_generate_or_use_prepared_text(monkeypatch, prepared, pipelined):
    def forbidden(*args, **kwargs):
        pytest.fail("stale source reached a browser, generator or sender")
    monkeypatch.setattr(tc, "read_reply_source", forbidden)
    monkeypatch.setattr(tc, "reply_to_tweet", forbidden)
    monkeypatch.setattr(pipeline.reply_generator, "generate", forbidden)
    candidate = pipeline.Candidate(parent(3601), SOURCE, "FEED",
        reply=DRAFT if prepared else "", likes=50, expires_at=NOW.timestamp()+1800)
    job = pipeline.Job("freshness", "FRESHNESS", None if prepared else lambda author: None,
                       pipelined=pipelined)
    assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    assert not replied_store.load_replied() and reply_budget.entries() == {}


@pytest.mark.parametrize("pipelined", [False, True])
def test_model_result_crossing_source_deadline_never_reaches_sender(monkeypatch, pipelined):
    url = parent(3599)
    monkeypatch.setattr(tc, "read_reply_source", lambda target: {"url": target, "text": SOURCE, "likes": 50})
    generated = []
    def generate(*args, **kwargs):
        generated.append(kwargs["text"])
        clock(monkeypatch, NOW + timedelta(seconds=2))
        return Generation(Outcome.WRITTEN, "en", DRAFT)
    monkeypatch.setattr(pipeline.reply_generator, "generate", generate)
    monkeypatch.setattr(tc, "reply_to_tweet", lambda *a, **k: pytest.fail("expired model result reached sender"))
    candidate = pipeline.Candidate(url, SOURCE, "FEED", likes=50)
    job = pipeline.Job("freshness", "FRESHNESS", lambda author: None, pipelined=pipelined)
    assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    assert generated == [SOURCE]
    assert not replied_store.load_replied() and reply_budget.entries() == {}


def test_alternate_sender_cannot_bypass_freshness_without_expected_source(monkeypatch, settings_override, memory_ledger):
    settings_override(REPLY_INVITED_ONLY=False)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc, "_activate_or_abort", lambda *a, **k: pytest.fail("stale alternate sender opened Safari"))
    refusals = []
    assert tc.reply_to_tweet(parent(3601), DRAFT, on_refused=refusals.append) is WriteOutcome.REFUSED
    assert refusals == [reply_admission.Refusal.STALE_CANDIDATE]
    assert not replied_store.load_replied() and reply_budget.entries() == {} and memory_ledger.rows == []


@pytest.mark.parametrize("limit", [10, 60])
def test_final_browser_check_crossing_deadline_releases_unsubmitted_claim(monkeypatch, settings_override, memory_ledger, limit):
    settings_override(DIRECT_REPLY_MAX_AGE_MINUTES=limit)
    url = parent(limit*60-1)
    reply_selection.remember(url, SOURCE, "share", {})
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    for name in ("_activate_or_abort", "_open_or_abort", "_paste_or_abort", "_reply_target"):
        monkeypatch.setattr(tc, name, lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda *a: pytest.fail("invited transport liked parent"))
    checks = []
    def last_browser_check(*args):
        checks.append(True)
        clock(monkeypatch, NOW + timedelta(seconds=2))
        return True
    monkeypatch.setattr(tc, "_reply_engagement_ok", last_browser_check)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("expired source was submitted"))
    refusals = []
    assert tc.reply_to_tweet(url, DRAFT, expected_text=SOURCE, on_refused=refusals.append) is WriteOutcome.REFUSED
    assert checks == [True]
    assert refusals == [reply_admission.Refusal.STALE_CANDIDATE]
    assert not replied_store.load_replied() and reply_budget.entries() == {} and memory_ledger.rows == []
