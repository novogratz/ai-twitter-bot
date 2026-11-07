from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.core import account
from src.editorial import editorial_bot as editorial
from src.editorial.slot_journal import MemoryJournal
from src.video import config as video_config, profile
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, clock


@pytest.fixture
def news(monkeypatch, tmp_path):
    now = datetime(2026, 11, 7, 9, 55, tzinfo=TORONTO)
    clock(monkeypatch, now)
    monkeypatch.setattr(editorial, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(editorial.content_guard, "is_duplicate", lambda text: False)
    quote = "The model runs on the device and supports offline audio transcription in multiple languages."
    source = {"id": "0", "title": "A new SI model", "url": "https://huggingface.co/blog/new-model",
              "publisher": "Hugging Face", "body": quote, "kind": "news", "published_at": now.isoformat()}
    draft = {"source_id": "0", "text": "This SI model transcribes audio offline on your device. That means the audio can stay local while you work without a connection.",
             "evidence": [quote], "angle": "local audio", "takeaway": "offline transcription"}
    review = {key: True for key in editorial.schemas.review_flags()}
    review.update(newsworthiness=4, reader_impact=4, opening_hook=4, reason="Concrete, sourced release.")
    monkeypatch.setattr(editorial, "_json_call", lambda *args: review)
    return now, source, draft, review


@pytest.mark.parametrize("field,value", [("newsworthiness", 3), ("reader_impact", None),
    ("opening_hook", True), ("opening_hook", 6), ("grounded", False)])
def test_banger_news_requires_all_quality_scores_and_factual_approval(news, field, value):
    _, source, draft, review = news
    assert editorial.review_draft(draft, [source], [])[0]
    review[field] = value
    assert not editorial.review_draft(draft, [source], [])[0]


@pytest.mark.parametrize("age,kind", [(49, "news"), (-1, "news"), (0, "knowledge")])
def test_news_never_fills_slots_with_stale_future_or_evergreen_content(news, age, kind):
    now, source, draft, _ = news
    source.update(published_at=(now - timedelta(hours=age)).isoformat(), kind=kind)
    assert not editorial.review_draft(draft, [source], [])[0]


def test_approved_news_survives_video_spacing_without_regeneration(news, monkeypatch, settings_override):
    now, source, draft, _ = news
    settings_override(VIDEO_ENABLED=True, VIDEO_LIVE=True, DRY_RUN=False)
    journal = MemoryJournal(); journal.roll_to(now.date())
    calls = []
    monkeypatch.setattr(editorial, "collect_sources", lambda *a, **k: [source])
    monkeypatch.setattr(editorial, "draft_post", lambda *a: calls.append("draft") or draft)
    monkeypatch.setattr(editorial, "_pending_refusal", lambda *a: "video spacing")
    slot = editorial.Slot("09:30", "A consequential update")
    editorial._run_slot(slot, journal, now.date(), False)
    assert journal.ready_draft("09:30", now.date())
    assert journal.attempts("09:30", now.date()) == 1
    monkeypatch.setattr(editorial, "_pending_refusal", lambda *a: "")
    monkeypatch.setattr(profile, "refusal", lambda *a, **k: "")
    from src.x import twitter_client
    monkeypatch.setattr(twitter_client, "post_tweet", lambda text: calls.append("send") or WriteOutcome.SHIPPED)
    editorial._run_slot(slot, journal, now.date(), False)
    assert calls == ["draft", "send"]
    assert journal.closed("09:30", now.date()) and not journal.ready_draft("09:30", now.date())


def test_cached_news_expires_at_slot_end(news, monkeypatch, settings_override):
    now, source, draft, review = news
    settings_override(VIDEO_ENABLED=True)
    journal = MemoryJournal(); journal.roll_to(now.date())
    journal.keep_draft("09:30", {"approved": True, "draft": draft}, source)
    clock(monkeypatch, now.replace(hour=10, minute=15))
    assert editorial.open_slots(journal=journal) == []
