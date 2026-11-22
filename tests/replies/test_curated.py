"""Selection, final-write limits and scarce engagement survive alternate callers."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
import json

import pytest

from src.core import account, engagement_log
from src.guards import action_guard, watch_curation, reply_admission, reply_budget, reply_intent, reply_selection, repost_store
from src.replies import curated, curated_reposts, priority_watch, reply_pipeline
from src.video import artist_review as video_review
from src.x import profile_evidence, safari, twitter_client, x_urls
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, clock

NOW = datetime(2026, 11, 20, 12, tzinfo=TORONTO)


def url(author="artist", n=0):
    stamp = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    return f"https://x.com/{author}/status/{((stamp - x_urls._TWITTER_EPOCH_MS) << 22) + n}"


@pytest.fixture(autouse=True)
def mode(monkeypatch, settings_override, memory_ledger):
    clock(monkeypatch, NOW)
    profile = replace(account.current(), auto_engage_all_topics=False)
    monkeypatch.setattr(account, "current", lambda: profile)
    settings_override(REPLY_CURATED_MODE=True, REPLY_INVITED_ONLY=True, REPLY_PUBLIC_REQUESTS=True,
                      MAX_REPLIES_PER_DAY=100, REPLY_MIN_LIKES=20, REPLY_MIN_FOLLOWERS=5000,
                      MIN_SECONDS_BETWEEN_REPLIES=600, REPLY_JITTER_SECONDS=0,
                      CURATED_WATCH_REPLIES_PER_DAY=3, CURATED_WATCH_REPOSTS_PER_DAY=3)
    monkeypatch.setattr(reply_selection.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(reply_selection, "_profiles", {})
    monkeypatch.setattr(reply_selection, "_sources", {})
    monkeypatch.setattr(watch_curation, "_reviews", {})
    monkeypatch.setattr(curated, "_pending", {})
    monkeypatch.setattr(curated, "_done", {})
    monkeypatch.setattr(curated, "_poll", 0)
    monkeypatch.setattr(curated, "_cursors", Counter())
    monkeypatch.setattr(curated_reposts, "_checked", {})
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: [])


def audience(author="artist", count=10000):
    reply_selection._profiles[author] = dict(handle=author, followers=count, observed_at=NOW.timestamp())


def approved_video(parent=None, text="My slopcore AI video"):
    from src.guards.meme_repost_store import digest
    from src.video.repost_review import frame_digest
    parent = parent or url()
    frames = [{"at": i + .5, "sha256": "a" * 64} for i in range(6)]
    verdict = dict(approved=True, ai_related=True, artist_work=True, style_fit=True,
                   safe=True, all_samples_reviewed=True, needs_unavailable_audio=False, quality=9,
                   observations=[dict(at=i+.5, observation="A clay moon changes into a smiling face") for i in (0, 2, 4)])
    return dict(purpose="artist_reply_v1", url=parent, source_hash=digest(text), media_id="12345",
                duration=6, frames=frames, fingerprint=frame_digest(frames), verdict=verdict,
                observed_at=NOW.timestamp())


def selected(lane="technical", author="artist", text="How does LLM retrieval fail?"):
    parent = url(author)
    audience(author)
    reply_selection.remember(parent, text, lane, approved_video(parent, text) if lane == "artist" else None)
    return parent, text


@pytest.mark.parametrize("count,ok", [(100, False), (4999, False), (None, False), (True, False), (5000, True)])
def test_verified_audience_floor_is_not_a_manual_vip_label(count, ok):
    audience(count=count)
    assert (not reply_selection.audience_refusal("artist")) is ok
    assert reply_selection.audience_refusal("unobserved")


def test_profile_expiry_or_clock_rollback_refuses():
    audience()
    reply_selection._profiles["artist"]["observed_at"] -= 21601
    assert reply_selection.audience_refusal("artist")
    audience()
    reply_selection._profiles["artist"]["observed_at"] += 1
    assert reply_selection.audience_refusal("artist")


@pytest.mark.parametrize("raw,want", [("12.3K", 12300), ("5,000", 5000), ("1,00", None),
    ("unknown", None), ("-5", None), ("1.5", None), ("2M", 2000000), ("5K followers of @else", None)])
def test_profile_counter_does_not_guess(raw, want):
    assert profile_evidence.count(raw) == want


def test_other_jobs_cannot_skip_source_evidence_or_ai_scope():
    parent, text = selected(author="elonmusk")
    assert reply_intent.source_refusal(parent, text) == ""
    assert reply_intent.source_refusal(parent, "The weather is lovely")
    reply_selection.remember(parent, "The weather is lovely", "technical")
    assert "AI/SI" in reply_intent.source_refusal(parent, "The weather is lovely")
    reply_selection._sources.clear()
    assert "evidence" in reply_intent.source_refusal(parent, text)


def test_opt_out_overrides_audience_and_review():
    parent, text = selected()
    assert reply_intent.remember_opt_out(parent, "No bots please")
    assert "no contact" in reply_intent.source_refusal(parent, text)


def test_artist_credit_is_not_a_question_to_another_recipient():
    assert not reply_selection.basic_refusal(url(), "My new slopcore video, inspired by @anotherartist")
    assert reply_selection.basic_refusal(url(), "How can I fix my AI video? @anotherartist")


def test_watched_source_opt_out_also_stops_likes():
    parent = url("elonmusk")
    assert not twitter_client._priority_source_ok(dict(url=parent, text="No bots please"))
    assert not action_guard.can_post(action_guard.LIKE, target=parent)[0]


def test_artist_needs_review_not_a_question_and_final_media_must_match(monkeypatch):
    parent, text = selected("artist", text="My slopcore AI video")
    assert reply_intent.source_refusal(parent, text) == ""
    page = dict(url=parent, text=text, outer_text=text, clicked=False, has_video=True, media_id="12345")
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(page))
    monkeypatch.setattr(twitter_client, "_reply_engagement_ok", lambda *a: True)
    assert twitter_client._reply_target(parent, expected_text=text)
    page["media_id"] = "54321"
    assert not twitter_client._reply_target(parent, expected_text=text)
    page["media_id"] = "12345"
    reply_selection._sources[parent]["evidence"]["verdict"]["quality"] = 7
    assert not twitter_client._reply_target(parent, expected_text=text)


@pytest.mark.parametrize("bad", ["audio", "unsampled", "stale", "wrong_text", "wrong_media", "low_quality", "unsafe"])
def test_video_evidence_cannot_be_reused_or_replace_missing_observation(bad):
    evidence = approved_video()
    if bad == "audio": evidence["verdict"]["needs_unavailable_audio"] = True
    if bad == "unsampled": evidence["verdict"]["observations"][0]["at"] = .75
    if bad == "stale": evidence["observed_at"] -= 1801
    if bad == "wrong_text": evidence["source_hash"] = "0" * 64
    if bad == "wrong_media": evidence["media_id"] = "999"
    if bad == "low_quality": evidence["verdict"]["quality"] = 7
    if bad == "unsafe": evidence["verdict"]["safe"] = False
    assert not video_review.valid(evidence, url(), "My slopcore AI video", "12345")


def test_weak_posts_skip_before_profile_reads_or_generation(monkeypatch):
    monkeypatch.setattr(profile_evidence, "read", lambda *a: pytest.fail("read weak author's profile"))
    rows = [dict(url=url(n=n), text="My slopcore AI video", is_reply=False, has_video=True, likes=likes)
            for n, likes in enumerate([1, 2, None, 19, 20])]
    reasons = Counter()
    curated.offer(rows, "artist", reasons)
    assert list(curated._pending) == [rows[-1]["url"]]
    assert sum(reasons.values()) == 4


def test_discovery_gives_artists_more_turns_and_preserves_opt_out_reads():
    turns = [curated.discovery() for _ in range(15)]
    counts = Counter(lane for _, lane in turns)
    assert counts == {"artist": 8, "technical": 4, "mentions": 3}
    assert all("min_faves:20" in query for query, lane in turns if lane != "mentions")


def test_short_limit_is_final_admission_not_only_prompt():
    parent, _ = selected()
    for draft in ["word " * 30, "x" * 141, "First point. Second point.", "First\nSecond"]:
        verdict = reply_admission.judge_text("artist", draft, manual_review=True, source_url=parent)
        assert not verdict and verdict.refusal is reply_admission.Refusal.TEXT


def test_artist_is_shorter_and_hearts_are_spaced_even_after_uncertain_send():
    parent, _ = selected("artist")
    assert not reply_selection.text_refusal("artist", "That little moon has my heart 💙", url=parent)
    assert reply_budget.begin(parent, "That little moon has my heart 💙") == ""
    assert reply_budget.entries()[x_urls.status_id(parent)]["status"] == "pending"
    assert not reply_selection.heart_allowed()
    assert reply_selection.text_refusal("another", "The moon is lovely 💙")
    assert reply_selection.text_refusal("elonmusk", "A useful improvement 💙")
    assert reply_selection.text_refusal("artist", "word " * 13, url=parent)
    assert reply_selection.preferred_lane() == "artist"


def test_hard_hundred_cap_counts_pending_even_when_environment_is_higher(settings_override):
    settings_override(MAX_REPLIES_PER_DAY=1400)
    reply_budget.STATE.write({x_urls.status_id(url(f"a{i}", i)): dict(target=url(f"a{i}", i), status="pending",
        submitted_at=(NOW-timedelta(hours=1)).isoformat()) for i in range(100)})
    assert "100/100" in reply_budget.refusal()
    assert not action_guard.can_post(action_guard.REPLY)[0]


def test_elon_author_exception_still_counts_inside_hundred_and_waits_six_hours():
    reply_budget.STATE.write({x_urls.status_id(url("elonmusk")): dict(target=url("elonmusk"), status="pending",
        submitted_at=(NOW-timedelta(hours=1)).isoformat())})
    assert "six-hour" in reply_budget.refusal(url("elonmusk", 1))
    row = reply_budget.entries(); next(iter(row.values()))["submitted_at"] = (NOW-timedelta(hours=7)).isoformat()
    reply_budget.STATE.write(row)
    assert reply_budget.refusal(url("elonmusk", 1)) == ""
    assert reply_budget.used_today() == 1


def test_final_composer_checks_actual_video_identity_and_parent_likes(monkeypatch):
    from tests.x.test_reply_target import mock_page
    parent, text = selected("artist", text="My slopcore AI video")
    articles = [dict(url=parent, text=text, mediaId="12345"),
                dict(url=parent, text=text, noTime=True, dialog=True)]
    likes = {"value": 20}
    monkeypatch.setattr(twitter_client, "_page_posts", lambda *a: dict(url=parent, likes=likes["value"]))
    mock_page(monkeypatch, articles, "https://x.com/compose/post")
    assert twitter_client._reply_target(parent, expected_text=text, composing=True)
    likes["value"] = 19
    assert not twitter_client._reply_target(parent, expected_text=text, composing=True)
    likes["value"] = 20
    articles[0]["mediaId"] = "98765"
    assert not twitter_client._reply_target(parent, expected_text=text, composing=True)


def test_parallel_submitters_share_the_last_slot():
    from concurrent.futures import ThreadPoolExecutor
    reply_budget.STATE.write({x_urls.status_id(url(f"a{i}", i)): dict(target=url(f"a{i}", i), status="pending",
        submitted_at=(NOW-timedelta(hours=1)).isoformat()) for i in range(99)})
    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(lambda n: reply_budget.begin(url(f"new{n}", n+1000), f"Test retrieval quality on example {n}."), range(2)))
    assert results.count("") == 1
    assert reply_budget.used_today() == 100


def test_uncertain_words_cannot_be_sent_to_a_different_author():
    parent, _ = selected()
    assert reply_budget.begin(parent, "Check retrieval before increasing the context window.") == ""
    assert "unresolved" in reply_selection.text_refusal("other", "Check retrieval before increasing the context window!")


def test_three_watched_replies_and_reposts_is_a_ceiling_including_legacy_receipts(memory_ledger):
    for i in range(2):
        memory_ledger.append(action_guard.REPLY, url("elonmusk", i), False, NOW-timedelta(hours=8))
        memory_ledger.append(action_guard.WATCH_REPOST, url("elonmusk", i), False, NOW-timedelta(hours=8))
    reply_budget.STATE.write({x_urls.status_id(url("elonmusk", 2)): dict(target=url("elonmusk", 2), status="pending",
        submitted_at=(NOW-timedelta(hours=7)).isoformat())})
    repost_store.STATE.write({x_urls.status_id(url("elonmusk", 2)): dict(url=url("elonmusk", 2), status="pending",
        ts=(NOW-timedelta(hours=7)).isoformat(), independent=True)})
    assert "cap" in reply_budget.refusal(url("elonmusk", 3))
    assert "cap" in watch_curation.refusal(url("elonmusk", 3))


def test_scoped_elon_actions_never_open_other_authors_or_profile_posts():
    assert action_guard.can_post(action_guard.LIKE, target=url("elonmusk"))[0]
    for action, target in [(action_guard.LIKE, url("artist")), (action_guard.LIKE, ""),
                           (action_guard.RETWEET, url("artist")), (action_guard.POST, ""), (action_guard.FOLLOW, "artist")]:
        assert not action_guard.can_post(action, target=target)[0]


def test_elon_reposts_require_exact_review_and_count_ambiguous_claims():
    parent = url("elonmusk")
    assert not repost_store.claim(parent)
    page = dict(url=parent, text="Grok now supports an explicit evaluation workflow", media_id="")
    verdict = dict(approved=True, useful=True, supported=True, ai_related=True, quality=8)
    watch_curation.remember(page, verdict)
    assert repost_store.claim(parent)
    assert "six-hour" in watch_curation.refusal(url("elonmusk", 1))
    assert not repost_store.claim(parent)
    page["text"] += " changed"
    assert not watch_curation.reviewed(page)


def test_watch_actions_like_but_cannot_blanket_repost(monkeypatch):
    from src.x.twitter_client import LikeOutcome
    candidate = reply_pipeline.Candidate(url("elonmusk"), "AI progress", "WATCH")
    monkeypatch.setattr(priority_watch, "discovered", lambda: [candidate])
    monkeypatch.setattr(priority_watch, "_ready", lambda *a: True)
    likes = []
    monkeypatch.setattr(twitter_client, "like_priority_post", lambda target: likes.append(target) or LikeOutcome.LIKED)
    monkeypatch.setattr(twitter_client, "repost_tweet", lambda *a: pytest.fail("blanket repost"))
    priority_watch.run_priority_actions_cycle()
    assert likes == [candidate.url]


def test_stop_still_overrides_scoped_like(monkeypatch):
    from tests.helpers import stop_requested
    stop_requested(monkeypatch)
    assert not action_guard.can_post(action_guard.LIKE, target=url("elonmusk"))[0]
