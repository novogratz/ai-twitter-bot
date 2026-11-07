from dataclasses import replace
from datetime import timedelta

import pytest

from src.core import account
from src.editorial.slot_journal import MemoryJournal
from src.guards import action_guard
from src.video import config, profile, publisher, schedule
from tests.helpers import clock


@pytest.fixture
def mixed(video_cfg, monkeypatch):
    cfg = replace(video_cfg, news_enabled=True)
    monkeypatch.setattr(config, "load", lambda: cfg)
    return cfg


def test_live_account_has_both_cadences_and_only_five_cast_keys():
    cfg = config.load()
    assert len(schedule.clocks(cfg)) == 13
    minutes = [int(t[:2]) * 60 + int(t[3:]) for t in schedule.clocks(cfg)]
    assert {b - a for a, b in zip(minutes, minutes[1:])} == {90}
    news = [int(t[:2]) * 60 + int(t[3:]) for t, _ in account.current().editorial.slots]
    assert len(news) == 10 and {b - a for a, b in zip(news, news[1:])} == {120}
    assert set(cfg.targets) == {"elon", "trump", "jensen", "sam", "dario"}
    assert cfg.watermark == "@thesimaximalist" and cfg.auto_edit and cfg.bangers_only


def test_news_and_video_run_on_separate_executors(video_store, mixed):
    import main
    scheduler = main.build_scheduler()
    assert scheduler.get_job("editorial_job") and scheduler.get_job("video_health_job")
    assert scheduler.get_job("editorial_job").executor != scheduler.get_job("video_health_job").executor
    assert scheduler.get_job("direct_reply_job")
    assert not main.build_scheduler(reply_only=True).get_job("editorial_job")


def test_pending_news_blocks_video_but_own_news_claim_can_submit(video_store, mixed, at, monkeypatch):
    now = at(10)
    clock(monkeypatch, now)
    journal = MemoryJournal(); journal.roll_to(now.date())
    journal.reserve("09:30", "https://example.test/news", "Reviewed news", now)
    assert profile.refusal("video", now, mixed, store=video_store, journal=journal) == "unresolved profile submission"
    assert profile.refusal("news", now, mixed, store=video_store, journal=journal)
    with profile.claimed_news(f"{now.date()}/09:30", "Reviewed news\n\nhttps://example.test/news"):
        assert profile.refusal("news", now, mixed, store=video_store, journal=journal) == ""
        assert profile.matches_news_claim("Reviewed news\n\nhttps://example.test/news")
        assert not profile.matches_news_claim("different text")
    journal.roll_to(now.date() + timedelta(days=1))
    assert profile.refusal("video", now + timedelta(days=1), mixed, store=video_store, journal=journal)


def test_reserved_video_blocks_news_and_confirmed_video_enforces_spacing(video_store, mixed, ready, at, monkeypatch):
    from tests.video.test_publisher import shipped
    clock(monkeypatch, at())
    ready()
    reservation = publisher.reserve(video_store, at(), mixed)
    assert reservation
    assert "video publication" in profile.refusal("news", at(), mixed, store=video_store)
    shipped(video_store, reservation, at(), "123")
    assert "spacing" in profile.refusal("news", at() + timedelta(minutes=1), mixed, store=video_store)
    assert profile.refusal("news", at() + timedelta(minutes=30), mixed, store=video_store) == ""


def test_tenth_news_claim_fits_but_eleventh_refuses(video_store, mixed, at, monkeypatch):
    now = at(23, 30)
    clock(monkeypatch, now)
    journal = MemoryJournal(); journal.roll_to(now.date())
    for i in range(9):
        old = now - timedelta(hours=2 * (10 - i))
        journal.reserve(str(i), f"https://example.test/{i}", f"post {i}", old)
        journal.confirm(str(i), f"https://example.test/{i}", f"post {i}", "angle", old)
    journal.reserve("last", "https://example.test/last", "Last news", now)
    with profile.claimed_news(f"{now.date()}/last", "Last news\n\nhttps://example.test/last"):
        assert profile.refusal("news", now, mixed, store=video_store, journal=journal) == ""
    journal.confirm("last", "https://example.test/last", "Last news", "angle", now)
    assert "ceiling" in profile.refusal("news", now, mixed, store=video_store, journal=journal)


def test_news_write_requires_exact_editorial_claim(video_store, mixed):
    from src.x.twitter_client import post_tweet
    from src.x.confirmed_write import WriteOutcome
    assert post_tweet("A useful sourced SI update cannot bypass editorial admission.") is WriteOutcome.REFUSED
    assert not action_guard.can_post(action_guard.RETWEET)[0]


def test_stronger_reviewed_archive_banger_beats_a_weaker_recent_clip(video_store, video_cfg, ready, at):
    cfg = replace(video_cfg, bangers_only=True, max_age_hours=730 * 24)
    for ident, age, scores, hook in (("recent", 1, (18, 17, 12), 8), ("archive", 400, (20, 20, 15), 10)):
        doc = ready(ident)
        doc["published_at"] = at().timestamp() - age * 86400
        doc["qc"].update(doc["inspection"], **dict(zip(("fit_score", "entertainment_score", "quality_score"), scores)))
        doc["qc"].update(opening={"hook_score": hook, "cast_visible_first_second": True,
                                  "action_first_second": True, "no_dead_intro": True},
                         opening_samples_reviewed=True, opening_sample_times=[0, .2, .4, .6, .8])
        video_store.save_candidate(ident, doc, at().timestamp(), state="ready", score=95)
    assert publisher.reserve(video_store, at(), cfg)["candidate"] == "archive"
