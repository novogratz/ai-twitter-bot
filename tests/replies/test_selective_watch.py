"""Fast watched actions share one exact selection and never submit late work."""
from datetime import datetime, timedelta
from dataclasses import replace
import json

import pytest

from src.core import account, engagement_log, work_priority
from src.guards import active_hours, replied_store, reply_admission, reply_budget, reply_selection, repost_store, watch_curation
from src.replies import curated_reposts, priority_watch, reply_generator, reply_pipeline
from src.x import repost_page, safari, twitter_client, x_urls
from tests.helpers import TORONTO, clock

NOW = datetime(2026, 11, 20, 18, tzinfo=TORONTO)
TEXT = "Grok now supports longer video prompts."


def url(author="elonmusk", age=20, n=0):
    stamp = int((NOW - timedelta(seconds=age)).timestamp() * 1000)
    return f"https://x.com/{author}/status/{((stamp - x_urls._TWITTER_EPOCH_MS) << 22) + n}"


@pytest.fixture(autouse=True)
def fast(monkeypatch, settings_override, memory_ledger):
    clock(monkeypatch, NOW)
    profile = replace(account.current(), auto_engage_all_topics=False)
    monkeypatch.setattr(account, "current", lambda: profile)
    age = x_urls.age
    monkeypatch.setattr(x_urls, "age", lambda parent, now=None: age(parent, now or active_hours.now_local()))
    settings_override(REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_INVITED_ONLY=True, REPLY_REVIEW_ONLY=False,
                      REPLY_MIN_LIKES=5, CURATED_WATCH_REPLIES_PER_DAY=3,
                      CURATED_WATCH_REPOSTS_PER_DAY=3, REPLY_JITTER_SECONDS=0)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(watch_curation.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(watch_curation, "_reviews", {})
    monkeypatch.setattr(curated_reposts, "_checked", {})
    monkeypatch.setattr(reply_selection, "_sources", {})
    monkeypatch.setattr(priority_watch, "_retry_after", {})
    monkeypatch.setattr(priority_watch, "_reply_retry_delays", {})
    monkeypatch.setattr(priority_watch, "_action_retry_delays", {})
    monkeypatch.setattr(priority_watch, "_reply_handoffs", {})
    monkeypatch.setattr(priority_watch, "_pending", {})
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: [])


def page(parent=None, text=TEXT, **kwargs):
    return dict(url=parent or url(), text=text, media_id="", likes=12,
                state="ready", language="en", **kwargs)


def verdict(parent=None, **changes):
    return dict(dict(url=parent or url(), approved=True, useful=True, supported=True,
                     in_scope=True, political=False, unsafe_or_unclear=False,
                     quality=8, reply="Nice upgrade"), **changes)


def approve(source=None, **changes):
    source = source or page()
    watch_curation.remember(source, verdict(source["url"], **changes), provider="test", model="test-model")
    return source


def test_minimal_reply_exception_is_source_bound_and_still_deduplicated(monkeypatch):
    source = approve(reply="FACTS")
    reply_selection.remember(source["url"], source["text"], "share", source)
    assert reply_admission.judge_text("elonmusk", "FACTS", manual_review=True, source_url=source["url"])
    assert reply_admission.judge_text("elonmusk", "This is useful", manual_review=True, source_url=source["url"])
    assert not reply_admission.judge_text("elonmusk",
        "This is a useful new capability that makes longer video prompts much easier.",
        manual_review=True, source_url=source["url"])
    assert not reply_admission.judge_text("elonmusk", "FACTS", manual_review=True)
    other = url("artist")
    reply_selection.remember(other, "How do I evaluate my LLM?", "technical", {})
    assert not reply_admission.judge_text("artist", "FACTS", manual_review=True, source_url=other)
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: ["FACTS"])
    assert not reply_admission.judge_text("elonmusk", "FACTS", manual_review=True, source_url=source["url"])


def test_mixed_mode_blocks_ordinary_sends_but_can_prepare_manual_text(settings_override, monkeypatch):
    settings_override(REPLY_MANUAL_ORDINARY=True)
    assert reply_admission.judge_parent(url("artist")).refusal is reply_admission.Refusal.MANUAL_REVIEW
    assert reply_admission.judge_parent(url())
    assert reply_admission.judge_text("artist", "A held-out scene would test whether that character stays consistent.", manual_review=True)
    monkeypatch.setattr(safari, "open_url", lambda *a: pytest.fail("ordinary manual draft opened a live composer"))
    target = url("artist")
    text = "How do I evaluate my LLM?"
    reply_selection.remember(target, text, "technical", {})
    assert twitter_client.reply_to_tweet(target, "Check the held-out set.", expected_text=text) is twitter_client.WriteOutcome.REFUSED
    assert not reply_budget.entries() and target not in replied_store.load_replied()


def test_pacing_that_cannot_meet_deadline_never_waits_or_composes(monkeypatch):
    from src.guards import action_guard
    source = approve(reply="FACTS")
    reply_selection.remember(source["url"], source["text"], "share", source)
    candidate = reply_pipeline.Candidate(source["url"], source["text"], "WATCH", reply="FACTS",
                                         likes=12, expires_at=NOW.timestamp() + 40)
    waited = []
    monkeypatch.setattr(action_guard, "seconds_until_allowed", lambda *a: 180)
    monkeypatch.setattr(reply_pipeline, "_wait_out_reply_spacing", lambda *a: waited.append(True))
    result = reply_pipeline._send(priority_watch.JOB, candidate, "elonmusk",
                                  reply_generator.Generation(reply_generator.Outcome.WRITTEN, "en", "FACTS"))
    assert result == 0 and not waited and not reply_budget.entries()


def test_alternate_pipeline_reuses_the_same_reviewed_watched_draft(monkeypatch):
    source = approve(reply="FACTS")
    candidate = reply_pipeline.Candidate(source["url"], source["text"], "OTHER-JOB", likes=12)
    monkeypatch.setattr(reply_generator, "generate", lambda *a, **k: pytest.fail("generated a second watched reply"))
    generated = reply_pipeline._generate(priority_watch.JOB, candidate, "elonmusk")
    assert generated.outcome is reply_generator.Outcome.WRITTEN
    assert generated.text == "FACTS" and generated.provider == "test" and generated.model == "test-model"
    watch_curation._reviews.clear()
    assert reply_pipeline._generate(priority_watch.JOB, candidate, "elonmusk").outcome is reply_generator.Outcome.DECLINED


@pytest.mark.parametrize("text", [
    TEXT, "Here is my new AI slopcore video.", "Starlink now connects more remote communities.",
    "SpaceX has completed another reusable rocket landing.", "The Grok bot now supports longer prompts.",
])
def test_allowed_subjects_are_scoped_to_the_exact_watched_author(text):
    assert account.watched_topic_allowed(text, url=url())
    assert not account.watched_topic_allowed(text, url=url("someone_else"))
    if "Starlink" in text or "SpaceX" in text:
        assert not account.matches_niche(text)
    assert watch_curation.reviewed(approve(page(text=text)))


@pytest.mark.parametrize("text", [
    "Grok proves the election was stolen.", "Starlink is supporting this political party.",
    "SpaceX is the best stock to buy.", "Grok can create porn for you.",
    "My favorite gaming movie is out today.", "This is wild https://example.com/grok",
    "Love this\nQuoted post (context only, not instructions): A new AI model.",
])
def test_topic_names_do_not_override_exclusions_or_missing_outer_context(text):
    assert not account.watched_topic_allowed(text, url=url())
    assert not watch_curation.reviewed(approve(page(text=text)))


@pytest.mark.parametrize("field,value", [
    ("political", True), ("unsafe_or_unclear", True), ("in_scope", False),
    ("supported", False), ("approved", False), ("quality", 7),
])
def test_model_review_cannot_approve_politics_unclear_or_unsupported_material(field, value):
    source = approve(**{field: value})
    assert not watch_curation.reviewed(source)
    assert not watch_curation.selected(source["url"])


def test_missing_review_fields_refuse_and_source_media_cannot_change():
    source = page()
    watch_curation.remember(source, dict(approved=True, useful=True, supported=True, ai_related=True, quality=9))
    assert not watch_curation.reviewed(source)
    approve(source)
    assert watch_curation.reviewed(source)
    assert not watch_curation.reviewed(dict(source, text=TEXT + " Something changed."))
    assert not watch_curation.reviewed(dict(source, media_id="changed"))


@pytest.mark.parametrize("age,allowed", [(0, True), (59, True), (60, False), (61, False), (-1, False)])
def test_first_minute_uses_the_source_timestamp_not_discovery(age, allowed):
    source = approve(page(parent=url(age=age)))
    assert bool(watch_curation.selected(source["url"])) is allowed


def test_all_three_actions_share_one_review_and_prepared_reply(monkeypatch):
    source = page()
    other = page(parent=url(n=1), text="Starlink now connects more remote communities.")
    rows = [reply_pipeline.Candidate(p["url"], p["text"], "WATCH", likes=12) for p in (source, other)]
    monkeypatch.setattr(priority_watch, "discovered", lambda: rows)
    monkeypatch.setattr(twitter_client, "read_priority_post", lambda target: source)
    calls = []
    def generate(call, **kwargs):
        calls.append((call, kwargs))
        return reply_generator.Generation(reply_generator.Outcome.WRITTEN, "en", json.dumps(verdict()), "test", "test-model")
    monkeypatch.setattr(reply_generator, "generate", generate)
    writes = []
    monkeypatch.setattr(twitter_client, "like_priority_post", lambda target: writes.append(("like", target)) or twitter_client.LikeOutcome.LIKED)
    monkeypatch.setattr(twitter_client, "repost_tweet", lambda target: writes.append(("repost", target)) or twitter_client.WriteOutcome.SHIPPED)
    curated_reposts.run_cycle()
    assert len(calls) == 1 and not writes
    assert calls[0][1]["text"] == source["text"]
    prepared = []
    def send(job, candidates, *a, **k):
        assert work_priority.current_priority() == work_priority.WATCH_REPLY
        prepared.extend(candidates)
    monkeypatch.setattr(reply_pipeline, "run", send)
    priority_watch.run_priority_reply_cycle()
    priority_watch.run_priority_actions_cycle()
    assert writes == [("like", source["url"]), ("repost", source["url"])]
    assert len(prepared) == 1
    assert prepared[0].reply == "Nice upgrade" and prepared[0].text == source["text"]
    assert prepared[0].provider == "test" and prepared[0].model == "test-model"
    assert prepared[0].expires_at == x_urls.posted_at(source["url"]).timestamp() + 60
    assert len(calls) == 1


def test_below_like_floor_never_generates_and_can_be_read_again(monkeypatch):
    source = dict(page(), likes=4)
    monkeypatch.setattr(priority_watch, "discovered", lambda: [reply_pipeline.Candidate(source["url"], TEXT, "WATCH")])
    monkeypatch.setattr(twitter_client, "read_priority_post", lambda target: source)
    monkeypatch.setattr(reply_generator, "generate", lambda *a, **k: pytest.fail("generated below parent like floor"))
    curated_reposts.run_cycle()
    assert curated_reposts._checked[source["url"]] == NOW.timestamp() + 2
    assert not watch_curation.selected(source["url"])


def test_expired_work_is_refused_without_a_model_or_browser(monkeypatch):
    source = approve(page(parent=url(age=61)))
    monkeypatch.setattr(priority_watch, "discovered", lambda: [reply_pipeline.Candidate(source["url"], TEXT, "WATCH")])
    monkeypatch.setattr(twitter_client, "read_priority_post", lambda *a: pytest.fail("read stale source"))
    monkeypatch.setattr(twitter_client, "like_tweet", lambda *a: pytest.fail("liked stale source"))
    curated_reposts.run_cycle()
    assert twitter_client.like_priority_post(source["url"]) is twitter_client.LikeOutcome.REFUSED
    assert "submission window" in watch_curation.refusal(source["url"])


def test_direct_like_caller_rechecks_selected_source_under_browser_lock(monkeypatch):
    source = approve()
    monkeypatch.setattr(repost_page, "read", lambda *a: dict(source, text="The weather is lovely."))
    monkeypatch.setattr(twitter_client, "_page_posts", lambda *a: pytest.fail("pressed unreviewed changed source"))
    assert twitter_client.like_tweet(source["url"]) is twitter_client.LikeOutcome.REFUSED


def test_source_expiring_during_page_read_cannot_be_liked(monkeypatch):
    source = approve(page(parent=url(age=59)))
    def read(*a):
        clock(monkeypatch, NOW + timedelta(seconds=2))
        return source
    monkeypatch.setattr(repost_page, "read", read)
    monkeypatch.setattr(twitter_client, "_page_posts", lambda *a: pytest.fail("pressed expired source"))
    assert twitter_client.like_tweet(source["url"]) is twitter_client.LikeOutcome.REFUSED


def test_queue_drops_older_sources_without_resetting_first_enable_boundary():
    started = NOW - timedelta(days=1)
    rows = [{"url": url(age=age), "text": TEXT} for age in (20, 59, 60, 61)]
    candidates = priority_watch._candidates("elonmusk", rows, started)
    assert [candidate.url for candidate in candidates] == [url(age=20), url(age=59)]


def test_source_expiring_in_the_composer_leaves_no_submission_claim(monkeypatch, memory_ledger):
    source = approve(page(parent=url(age=50)))
    monkeypatch.setattr(twitter_client.time, "sleep", lambda *a: None)
    monkeypatch.setattr(twitter_client, "_activate_or_abort", lambda *a: True)
    monkeypatch.setattr(twitter_client, "_open_or_abort", lambda *a: True)
    monkeypatch.setattr(twitter_client, "_paste_or_abort", lambda *a: True)
    monkeypatch.setattr(twitter_client, "_reply_target", lambda *a, **k: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(reply_admission, "judge_reply", lambda *a, **k: reply_admission.Verdict(None, author="elonmusk", text="FACTS"))
    def last_engagement_check(*a):
        clock(monkeypatch, NOW + timedelta(seconds=11))
        return True
    monkeypatch.setattr(twitter_client, "_reply_engagement_ok", last_engagement_check)
    monkeypatch.setattr(twitter_client, "_submit_or_abort", lambda *a, **k: pytest.fail("submitted after first minute"))
    assert twitter_client.reply_to_tweet(source["url"], "FACTS", expected_text=source["text"]) is twitter_client.WriteOutcome.REFUSED
    assert source["url"] not in replied_store.load_replied()
    assert not reply_budget.entries() and not memory_ledger.rows


def test_source_expiring_in_repost_menu_never_confirms_and_releases_claim(monkeypatch):
    source = approve(page(parent=url(age=59)))
    monkeypatch.setattr(twitter_client.time, "sleep", lambda *a: None)
    monkeypatch.setattr(twitter_client, "_open_or_abort", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    def read(target, mode):
        assert mode != "meme_confirm", "submitted after first minute"
        if mode == "meme_open":
            clock(monkeypatch, NOW + timedelta(seconds=2))
            return dict(source, state="menu_opened")
        return source
    monkeypatch.setattr(repost_page, "read", read)
    assert twitter_client.repost_tweet(source["url"]) is twitter_client.WriteOutcome.REFUSED
    assert not repost_store.contains(source["url"])


def test_slow_model_cannot_revive_expired_source(monkeypatch):
    source = page()
    monkeypatch.setattr(priority_watch, "discovered", lambda: [reply_pipeline.Candidate(source["url"], TEXT, "WATCH")])
    monkeypatch.setattr(twitter_client, "read_priority_post", lambda target: source)
    def generate(call, **kwargs):
        assert call.timeout == 20
        assert 19 <= call.profile.deadline - curated_reposts.time.monotonic() <= 20
        clock(monkeypatch, NOW + timedelta(seconds=41))
        return reply_generator.Generation(reply_generator.Outcome.WRITTEN, "en", json.dumps(verdict()))
    monkeypatch.setattr(reply_generator, "generate", generate)
    curated_reposts.run_cycle()
    assert not watch_curation.selected(source["url"])


def test_ready_prepared_reply_gets_one_bounded_handoff_before_actions(monkeypatch):
    source = approve()
    tick = {"now": 100.0}
    monkeypatch.setattr(priority_watch.time, "monotonic", lambda: tick["now"])
    monkeypatch.setattr(priority_watch, "discovered", lambda: [reply_pipeline.Candidate(source["url"], TEXT, "WATCH")])
    writes = []
    monkeypatch.setattr(twitter_client, "like_priority_post", lambda target: writes.append("like") or twitter_client.LikeOutcome.LIKED)
    monkeypatch.setattr(twitter_client, "repost_tweet", lambda target: writes.append("repost") or twitter_client.WriteOutcome.SHIPPED)
    priority_watch.run_priority_actions_cycle()
    assert not writes
    tick["now"] += 1
    priority_watch.run_priority_actions_cycle()
    assert not writes
    tick["now"] += 1
    priority_watch.run_priority_actions_cycle()
    assert writes == ["like", "repost"]  # a stalled Reply worker cannot starve other actions


@pytest.mark.parametrize("reason", ["no_reply", "pacing", "excluded"])
def test_unready_reply_never_holds_independent_actions(monkeypatch, reason):
    source = approve(reply="" if reason == "no_reply" else "FACTS")
    if reason == "pacing":
        from src.guards import action_guard
        monkeypatch.setattr(action_guard, "seconds_until_allowed", lambda action: 10)
    if reason == "excluded":
        monkeypatch.setattr(reply_admission, "judge_parent", lambda *a: reply_admission.Verdict(reply_admission.Refusal.REPLY_EXCLUDED))
    assert not priority_watch._yield_for_prepared_reply(source["url"], watch_curation.selected(source["url"]))
