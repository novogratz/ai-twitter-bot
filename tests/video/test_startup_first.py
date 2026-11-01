from types import SimpleNamespace

import pytest

from src.video import cli, operations, publisher, startup
from src.video.store import Store
from tests.helpers import url


@pytest.fixture
def held(video_store, at, monkeypatch):
    monkeypatch.setattr(startup, "DATABASE", video_store.path)
    video_store.set_meta("paused", True)
    startup.arm(video_store, "explicit-video-first", at(6, 50))
    return video_store


def checks(monkeypatch, *, allowed):
    calls = []
    def preflight(*a, **kw):
        calls.append(kw.get("network"))
        return {"ready_for_live": allowed, "blockers": [] if allowed else ["missing source permission"]}
    monkeypatch.setattr(operations, "preflight", preflight)
    return calls


def confirm(store, reservation, now):
    with store.transaction() as db:
        db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (reservation["id"],))
    publisher.confirm(store, reservation["id"], reservation["token"], now.timestamp(), "123")


def test_failed_preflight_holds_replies_durably_without_consuming_startup(held, video_cfg, at, monkeypatch):
    calls = checks(monkeypatch, allowed=False)
    assert startup.activate_when_ready(held, video_cfg, now=at(6, 50)) is None
    assert calls == [False]  # no network checks when local prerequisites already fail
    assert not held.rows("SELECT * FROM startup")
    assert held.meta("paused")
    assert startup.waiting_reason(Store(held.path))
    from src.guards.reply_admission import Refusal, judge_parent
    verdict = judge_parent(url("someone"))
    assert verdict.refusal is Refusal.STARTUP_VIDEO and not verdict.refusal.definitive


def test_primary_collision_releases_jobs_only_after_confirmed_video(held, video_cfg, ready, at, monkeypatch):
    import main
    from src.replies import direct_reply
    from src.video import workers
    checks(monkeypatch, allowed=True)
    calls = []
    monkeypatch.setattr(direct_reply, "run_direct_reply_cycle", lambda: calls.append("reply"))
    monkeypatch.setattr(workers, "health_job", lambda: calls.append("video"))
    monkeypatch.setattr(main.health, "wrap_job", lambda fn, *a, **kw: fn)
    scheduler = main.build_scheduler()
    reply_job, video_job = scheduler.get_job("direct_reply_job"), scheduler.get_job("video_health_job")
    reply_job.func()
    video_job.func()
    assert calls == ["video"]
    request = startup.activate_when_ready(held, video_cfg, now=at(6, 50))
    assert request["state"] == "pending" and startup.waiting_reason()
    ready(when=at())
    reservation = publisher.reserve(held, at(), video_cfg)
    assert reservation["startup"] == request["id"] and reservation["slot"].endswith("07:00")
    reply_job.func()
    assert calls == ["video"]
    confirm(held, reservation, at())
    assert not startup.waiting_reason()
    reply_job.func()
    assert calls == ["video", "reply"]


@pytest.mark.parametrize("outcome", ["empty", "expired", "unknown"])
def test_empty_expired_or_ambiguous_startup_never_releases_replies(held, video_cfg, ready, at, monkeypatch, outcome):
    checks(monkeypatch, allowed=True)
    startup.activate_when_ready(held, video_cfg, now=at(6, 50))
    if outcome == "unknown":
        ready()
        row = publisher.reserve(held, at(), video_cfg)
        with held.transaction() as db:
            db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (row["id"],))
        publisher.unknown(held, row["id"], row["token"], at().timestamp(), "ambiguous fixture")
    elif outcome == "expired":
        publisher.tick_calendar(held, at(8), video_cfg)
        assert held.rows("SELECT state FROM startup")[0]["state"] == "skipped"
    assert startup.waiting_reason()
    startup.tick(Store(held.path), video_cfg, at(8).timestamp())
    assert len(held.rows("SELECT * FROM startup")) == 1
    assert startup.waiting_reason()


def test_repeated_launch_and_restart_preserve_one_request(held, video_cfg, at, monkeypatch):
    checks(monkeypatch, allowed=True)
    startup.activate_when_ready(held, video_cfg, now=at(6, 50))
    for index in range(3):
        restarted = Store(held.path)
        intent = startup.arm(restarted, f"repeat-{index}", at(6, 51))
        assert intent["request_id"] == "explicit-video-first"
        startup.tick(restarted, video_cfg, at(6, 51).timestamp())
    assert len(held.rows("SELECT * FROM startup")) == 1
    assert startup.waiting_reason()


def test_future_explicit_activation_can_hold_again_after_previous_success(held, video_cfg, ready, at, monkeypatch):
    checks(monkeypatch, allowed=True)
    startup.activate_when_ready(held, video_cfg, now=at(6, 50))
    ready()
    confirm(held, publisher.reserve(held, at(), video_cfg), at())
    assert not startup.waiting_reason()
    startup.arm(held, "tomorrow", at(5, day=3))
    assert startup.waiting_reason()
    startup.activate_when_ready(held, video_cfg, now=at(5, day=3))
    assert len(held.rows("SELECT * FROM startup")) == 2


def test_ordinary_boot_and_dry_run_do_not_arm_a_hold(video_store, video_cfg, at, settings_override, monkeypatch):
    monkeypatch.setattr(startup, "DATABASE", video_store.path)
    startup.tick(video_store, video_cfg, at().timestamp())
    assert not video_store.meta(startup.KEY) and not startup.waiting_reason()
    settings_override(DRY_RUN=True)
    with pytest.raises(ValueError, match="live video"):
        startup.arm(video_store, "dry", at())
    assert not video_store.meta(startup.KEY)


def test_disabled_video_flag_cannot_bypass_existing_hold(held, settings_override):
    settings_override(VIDEO_ENABLED=False)
    assert startup.waiting_reason()


def test_unreadable_gate_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "broken.db"
    path.write_bytes(b"not a sqlite database")
    monkeypatch.setattr(startup, "DATABASE", path)
    assert "unreadable" in startup.waiting_reason()
    assert path.read_bytes() == b"not a sqlite database"


def test_cli_failed_video_first_activation_stays_held(held, video_cfg, at, monkeypatch, capsys):
    checks(monkeypatch, allowed=False)
    monkeypatch.setattr(cli, "Store", lambda: held)
    monkeypatch.setattr(cli.config, "load", lambda: video_cfg)
    monkeypatch.setattr(cli.state_store, "require_migrated", lambda: None)
    cli._execute(SimpleNamespace(command="activate", before_replies=True, request_id="another-launch"))
    assert "interactions held" in capsys.readouterr().out
    assert startup.waiting_reason() and not held.rows("SELECT * FROM startup")


def test_only_explicit_resume_replies_releases_failed_hold(held, video_cfg, monkeypatch, settings_override):
    monkeypatch.setattr(cli, "Store", lambda: held)
    monkeypatch.setattr(cli.config, "load", lambda: video_cfg)
    monkeypatch.setattr(cli.state_store, "require_migrated", lambda: None)
    settings_override(DRY_RUN=True)
    with pytest.raises(SystemExit, match="Dry run"):
        cli._execute(SimpleNamespace(command="resume-replies"))
    assert startup.waiting_reason()
    settings_override(DRY_RUN=False)
    cli._execute(SimpleNamespace(command="resume-replies"))
    assert not startup.waiting_reason() and not held.rows("SELECT * FROM startup")
