"""Operator's coach, 2026-11-25: viral AI videos from X posted with a two to four word take, in four windows."""
from datetime import datetime, timedelta

import pytest

from src.account import video_share_bot
from src.guards import video_share_store as store
from src.video import repost_review
from src.x import twitter_client
from src.x.confirmed_write import WriteOutcome

URL = "https://x.com/creator/status/2125590588900921732"


@pytest.fixture
def sharing(settings_override, monkeypatch):
    settings_override(VIDEO_SHARE_ENABLED=True, DRY_RUN=False, HOURLY_BREAK_MINUTES=0)
    clock = {"now": datetime.fromisoformat("2026-11-25T08:10:00-05:00")}
    monkeypatch.setattr(store.active_hours, "now_local", lambda: clock["now"])
    monkeypatch.setattr(store.x_urls, "age", lambda url, *a: timedelta(hours=2))
    from src.video import config as video_config
    monkeypatch.setattr(video_config, "legacy_usage", lambda now: (0, None))
    return clock


@pytest.mark.parametrize("take,ok", [("Jensen cooked 🔥", True), ("Peak AI cinema", True), ("This is so good 😂", True),
    ("Wow", False), ("one two three four five", False), ("Nice one @creator", False), ("So good #AI", False),
    ("Too good https://x.com", False), ("Best one 😂🔥💀", False), ("", False), (None, False)])
def test_take_is_two_to_four_words_and_at_most_one_emoji(take, ok):
    assert repost_review.take_ok(take) is ok


def test_default_windows_are_the_coachs_four(sharing):
    assert store.windows() == [(480, 540, 5), (720, 780, 3), (1020, 1080, 6), (1305, 1350, 2)]


def test_nothing_is_shared_outside_a_window_and_review_may_start_half_an_hour_before(sharing):
    assert not store.refusal()
    sharing["now"] = datetime.fromisoformat("2026-11-25T10:00:00-05:00")
    assert "outside" in store.refusal() and "outside" in store.refusal(preparing=True)
    sharing["now"] = datetime.fromisoformat("2026-11-25T11:40:00-05:00")
    assert "outside" in store.refusal() and not store.refusal(preparing=True)


def test_window_count_spacing_and_one_claim_per_status_and_per_media(sharing):
    assert store.claim(URL, "Jensen cooked 🔥", "111")
    assert not store.claim(URL, "again", "222")                               # the same post
    assert not store.claim(URL.replace("creator", "copycat")[:-1] + "3", "again", "111")   # the same video elsewhere
    store.settle(URL, shipped=True)
    assert "spacing" in store.refusal()
    sharing["now"] += timedelta(minutes=11)
    assert not store.refusal()
    for index in range(4):
        other = f"https://x.com/creator/status/212559058890092{index}000"
        assert store.claim(other, "Too good 😂", str(900 + index))
        store.settle(other, shipped=True)
    sharing["now"] += timedelta(minutes=11)
    assert "window" in store.refusal()                                        # five in the 08:00 window


def test_an_uncertain_share_holds_the_next_one_and_a_proven_failure_releases_the_claim(sharing):
    assert store.claim(URL, "Jensen cooked 🔥", "111")
    assert "uncertain" in store.refusal()
    store.settle(URL, shipped=False)
    assert not store.contains(URL) and not store.refusal()


def test_our_own_video_post_counts_for_the_spacing(sharing, monkeypatch):
    from src.video import config as video_config
    monkeypatch.setattr(video_config, "legacy_usage", lambda now: (1, now - 120))
    assert "spacing" in store.refusal()


def test_cycle_reviews_one_lead_and_posts_only_an_approved_take(sharing, monkeypatch):
    posted = []
    video_share_bot._candidates.clear(); video_share_bot._declined.clear(); video_share_bot._approved.clear()
    monkeypatch.setattr(video_share_bot.active_hours, "require_active", lambda: None)
    monkeypatch.setattr(video_share_bot, "_discover", lambda: video_share_bot._candidates.update(
        {URL: {"url": URL, "likes": 9000, "has_video": True}}))
    page = {"url": URL, "text": "AI Jensen at the office", "has_video": True, "media_id": "111", "likes": 9000}
    monkeypatch.setattr(video_share_bot.twitter_client, "read_share_post", lambda url: page)
    verdict = {"take": "Jensen cooked 🔥", "brand_fit": True, "reason": "fun"}
    monkeypatch.setattr(video_share_bot.repost_review, "inspect", lambda page, share=False: {"verdict": verdict})
    monkeypatch.setattr(video_share_bot.repost_review, "valid", lambda *a: True)
    monkeypatch.setattr(video_share_bot.twitter_client, "post_video_share",
                        lambda *a: posted.append(a) or WriteOutcome.SHIPPED)
    video_share_bot.run_video_share_cycle()       # reviews
    assert not posted and len(video_share_bot._approved) == 1
    video_share_bot.run_video_share_cycle()       # posts
    assert posted == [(URL, "Jensen cooked 🔥", "111", "AI Jensen at the office")]
    # a clip the taste rule refuses is never queued
    video_share_bot._declined.clear()
    verdict["brand_fit"] = False
    video_share_bot.run_video_share_cycle()
    assert not video_share_bot._approved and len(posted) == 1


def test_write_path_checks_the_exact_video_in_the_composer_before_and_after_the_paste():
    import inspect
    source = inspect.getsource(twitter_client.post_video_share)
    for rule in ("Post Video", "postVideoRemove", "composed(\"\")", "reply_metrics.capture", "video_share_store.claim"):
        assert rule in source


def test_live_account_has_searches_and_the_scheduler_runs_the_job_only_when_enabled(settings_override):
    import tomllib
    from pathlib import Path
    import main
    raw = tomllib.loads(Path("accounts/theaishrink/account.toml").read_text())
    assert len(raw["video_share_queries"]) >= 4 and all("native_video" in q for q in raw["video_share_queries"])
    settings_override(VIDEO_SHARE_ENABLED=True)
    assert "video_share_job" in {job.id for job in main.build_scheduler().get_jobs()}
    settings_override(VIDEO_SHARE_ENABLED=False)
    assert "video_share_job" not in {job.id for job in main.build_scheduler().get_jobs()}
