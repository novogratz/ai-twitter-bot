
from src.guards import action_guard
from src.video import workers


def test_video_replaces_editorial_job_preserving_reply_jobs(video_cfg, monkeypatch, settings_override):
    import main
    from src.video import config
    monkeypatch.setattr(config, "load", lambda: video_cfg)
    settings_override(VIDEO_ENABLED=False)
    before = {j.id for j in main.build_scheduler().get_jobs()}
    settings_override(VIDEO_ENABLED=True)
    after = {j.id for j in main.build_scheduler().get_jobs()}
    assert before - after == {"editorial_job"}
    assert after - before == {"video_health_job"}
    assert "direct_reply_job" in after and "feed_sweep_job" in after


def test_legacy_profile_chokepoint_refuses_when_video_owns_schedule(settings_override, monkeypatch, video_cfg):
    from src.video import config
    monkeypatch.setattr(config, "load", lambda: video_cfg)
    settings_override(VIDEO_ENABLED=True)
    assert not action_guard.can_post(action_guard.POST)[0]
    assert not action_guard.can_post(action_guard.RETWEET)[0]


def test_worker_start_restart_redeploy_never_creates_startup(video_store, video_cfg, monkeypatch):
    from src.core import video_pressure
    monkeypatch.setattr(video_pressure, "pressure", lambda *a, **kw: "")
    for _ in range(3):
        workers.seed_jobs(video_store, video_cfg, 100)
        workers.run_once("discovery", video_store, video_cfg, "boot", now=100)
    assert not video_store.rows("SELECT * FROM startup")


def test_pause_stops_due_publication_but_discovery_remains_independent(video_store, video_cfg, ready, at, monkeypatch):
    from src.core import video_pressure
    from src.video import publisher
    ready()
    video_store.set_meta("paused", True)
    assert publisher.reserve(video_store, at(), video_cfg) is None
    monkeypatch.setattr(video_pressure, "pressure", lambda *a, **kw: "")
    workers.seed_jobs(video_store, video_cfg, at().timestamp())
    assert workers.run_once("discovery", video_store, video_cfg, "w", now=at().timestamp()) == "blocked"
    assert video_store.rows("SELECT * FROM jobs WHERE kind='discovery'")


def test_main_dry_run_propagates_to_video_commands(monkeypatch):
    import main
    from src.video import cli
    calls = []
    monkeypatch.setattr("sys.argv", ["main.py", "--dry-run", "--video", "activate", "--live", "--request-id", "test"])
    monkeypatch.setattr(cli, "main", lambda args: calls.append(args))
    main.main()
    assert calls == [["--dry-run", "activate", "--live", "--request-id", "test"]]
