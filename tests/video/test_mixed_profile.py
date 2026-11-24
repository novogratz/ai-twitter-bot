from dataclasses import replace

from src.video import config, publisher, schedule
from tests.helpers import clock


def test_live_account_has_twenty_daily_windows_with_six_qualifiers():
    cfg = config.load()
    # Operator, 2026-11-24 morning: "lets do 20 posts a day" (five the night before); short captions.
    clocks = list(schedule.clocks(cfg))
    assert len(clocks) == 20 and clocks[0] == "07:00" and clocks[-1] == "22:50" and cfg.short_caption
    assert cfg.upscale and cfg.remove_source_logos
    # Operator, 2026-11-23: Zuckerberg qualifies too; Trump and Elon must look good.
    assert set(cfg.targets) == {"elon", "trump", "jensen", "sam", "dario", "zuck"}
    assert "Trump or Elon appear they must look good" in cfg.editorial_taste
    assert cfg.watermark == "@thesimaximalist" and cfg.auto_edit and cfg.bangers_only
    assert cfg.edit_max_seconds == 120 and cfg.discovery_prompt_file
    # The ultra floors never passed one clip in three weeks; an audience floor replaces them.
    assert not cfg.ultra_bangers_only and cfg.audience_min_views >= 50000 and cfg.audience_min_likes >= 2000
    assert not cfg.startup_on_boot and cfg.buffer_target == 3 and cfg.ready_reserve_min == 1


def test_no_news_or_legacy_original_jobs_in_exceptional_video_mode(settings_override):
    import main
    settings_override(VIDEO_ENABLED=True, NEWS_ENABLED=False, NEWS_AUTO_PUBLISH=False)
    scheduler = main.build_scheduler()
    assert not scheduler.get_job("news_job")
    assert not scheduler.get_job("editorial_job")
    assert scheduler.get_job("direct_reply_job") and scheduler.get_job("video_health_job")


def test_news_video_and_replies_keep_independent_executors(settings_override):
    import main
    settings_override(VIDEO_ENABLED=True, NEWS_ENABLED=True)
    scheduler = main.build_scheduler()
    assert scheduler.get_job("news_job") and scheduler.get_job("video_health_job")
    assert scheduler.get_job("news_job").executor != scheduler.get_job("video_health_job").executor
    assert not scheduler.get_job("editorial_job")
    assert scheduler.get_job("direct_reply_job")
    assert not main.build_scheduler(reply_only=True).get_job("news_job")


def test_existing_news_publication_hold_still_blocks_video(video_store, video_cfg, ready, at, monkeypatch):
    from src.news import publisher as news_publisher
    clock(monkeypatch, at())
    ready()
    monkeypatch.setattr(news_publisher, "video_hold", lambda *a, **k: "news send unresolved")
    assert publisher.reserve(video_store, at(), video_cfg) is None
    assert not video_store.rows("SELECT * FROM reservations")


def test_stronger_reviewed_archive_banger_beats_a_weaker_recent_clip(video_store, video_cfg, ready, at):
    cfg = replace(video_cfg, bangers_only=True, max_age_hours=730 * 24)
    for ident, age, grade in (("recent", 1, 9.2), ("archive", 400, 10)):
        doc = ready(ident)
        doc["published_at"] = at().timestamp() - age * 86400
        doc["qc"].update(doc["inspection"], banger_scores={key: grade for key in doc["inspection"]["banger_scores"]})
        doc["qc"].update(opening={"hook_score": 10, "cast_visible_first_second": True,
                                  "action_first_second": True, "no_dead_intro": True},
                         opening_samples_reviewed=True, opening_sample_times=[0, .2, .4, .6, .8])
        from src.video import ranking
        doc = ranking.refresh(video_store, video_store.candidate(ident) | {"document": doc}, at().timestamp(), cfg)
        video_store.save_candidate(ident, doc, at().timestamp(), state="ready", score=doc["ranking"]["total"])
    assert publisher.reserve(video_store, at(), cfg)["candidate"] == "archive"
