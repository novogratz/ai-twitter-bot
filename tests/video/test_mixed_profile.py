from dataclasses import replace

from src.video import config, publisher, schedule
from tests.helpers import clock


def test_live_account_targets_five_instagram_videos_with_supported_tech_cast():
    cfg = config.load()
    assert schedule.clocks(cfg) == ("06:00", "09:00", "12:00", "17:00", "21:00")
    assert cfg.daily_target_min == cfg.scheduled_daily_cap == 5
    assert cfg.early_video_window and cfg.meme_caption
    assert cfg.publish_platforms == ["instagram"]
    assert [p for p, options in cfg.platforms.items() if options.get("enabled")] == ["instagram"]
    assert set(cfg.targets) == {"elon", "trump", "jensen", "sam", "dario"}
    assert cfg.watermark == "@thesimaximalist" and cfg.auto_edit and cfg.bangers_only
    assert cfg.edit_max_seconds == 120 and cfg.discovery_prompt_file
    assert cfg.ultra_bangers_only and cfg.min_hook_score == 9 and cfg.best_available_fallback
    assert not cfg.startup_on_boot and cfg.buffer_target == 10 and cfg.ready_reserve_min == 5
    assert cfg.playful_caption and not cfg.one_line_caption


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


def test_guests_alone_cannot_qualify_a_clip(video_cfg, ready, at):
    from src.video import ranking
    live = config.load()
    cfg = replace(video_cfg, targets=live.targets)
    doc = ready()
    doc["inspection"]["cast"] = ["bill", "mark"]
    assert "performance verification" in ranking.gate(doc, cfg, at().timestamp(), final=True)
    for required in ("elon", "jensen", "dario", "sam", "trump"):
        doc["inspection"]["cast"] = ["bill", required]
        assert ranking.gate(doc, cfg, at().timestamp(), final=True) == ""


def test_video_preparation_sleeps_without_claiming_jobs(video_store, video_cfg, at, monkeypatch):
    from src.video import workers
    clock(monkeypatch, at(23))
    monkeypatch.setattr(workers, "seed_jobs", lambda *a: (_ for _ in ()).throw(AssertionError("seeded overnight")))
    for role in ("discovery", "media"):
        assert workers.run_once(role, video_store, video_cfg, "test", now=at(23).timestamp()) == "sleeping"
    assert not video_store.rows("SELECT id FROM jobs")
