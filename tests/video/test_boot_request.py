"""Ordinary boot requests a video independently of Reply admission."""
from dataclasses import replace

import pytest

from src.video import config, publisher, schedule, startup, store


@pytest.fixture
def boot(video_store, video_cfg, at, monkeypatch):
    import main
    cfg = replace(video_cfg, startup_on_boot=True)
    monkeypatch.setattr(config, "load", lambda: cfg)
    monkeypatch.setattr(store, "Store", lambda: video_store)
    monkeypatch.setattr(schedule, "utc_now", lambda: at(10))
    monkeypatch.setattr(startup, "DATABASE", video_store.path)
    return main._request_startup_video


def test_boot_requests_once_per_day_without_holding_replies(boot, video_store):
    first = boot()
    assert first["state"] == "pending"
    assert boot()["id"] == first["id"]
    assert len(video_store.rows("SELECT * FROM startup")) == 1
    assert not video_store.meta(startup.KEY)
    assert not startup.waiting_reason()
    assert not video_store.rows("SELECT * FROM reservations")


@pytest.mark.parametrize("flag", ["paused", "shutdown"])
def test_boot_respects_operator_video_controls(boot, video_store, flag):
    video_store.set_meta(flag, True)
    assert boot() is None
    assert not video_store.rows("SELECT * FROM startup")


@pytest.mark.parametrize("setting", ["VIDEO_ENABLED", "VIDEO_LIVE", "DRY_RUN"])
def test_disabled_or_dry_boot_has_no_startup_request(boot, video_store, settings_override, setting):
    settings_override(**{setting: setting == "DRY_RUN"})
    assert boot() is None
    assert not video_store.rows("SELECT * FROM startup")


def test_account_without_boot_opt_in_has_no_startup_request(boot, video_store, video_cfg, monkeypatch):
    monkeypatch.setattr(config, "load", lambda: video_cfg)
    assert boot() is None
    assert not video_store.rows("SELECT * FROM startup")


def test_old_expired_pending_request_does_not_swallow_new_boot(boot, video_store, video_cfg, at):
    publisher.request_startup(video_store, "old", at(8, day=1), video_cfg, explicit_live=True)
    new = boot()
    assert new["id"] == "boot:2026-11-02"
    assert video_store.rows("SELECT state FROM startup WHERE id='old'")[0]["state"] == "skipped"


def test_overnight_boot_preserves_request_until_active_time(boot, video_store, at, monkeypatch):
    monkeypatch.setattr(schedule, "utc_now", lambda: at(2))
    request = boot()
    assert request["state"] == "pending"
    assert not startup.waiting_reason()
    assert not video_store.rows("SELECT * FROM reservations")


def test_video_request_failure_does_not_stop_startup(boot, monkeypatch, caplog):
    def unavailable():
        raise OSError("fixture database unavailable")
    monkeypatch.setattr(store, "Store", unavailable)
    assert boot() is None
    assert "Reply workers continue" in caplog.text
