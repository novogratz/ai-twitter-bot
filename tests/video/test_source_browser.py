from contextlib import nullcontext
from dataclasses import replace
import json

import pytest

from src.video import connectors, source_browser
from src.video.security import AccessError


def player(now):
    return {"id": "BV1234567890", "published": now - 3600, "creator": "creator",
            "user_agent": "fixture Safari", "encrypted": False,
            "metrics": {"views": 1000, "likes": 12},
            "video": [{"url": "https://upos-hz-mirrorakam.akamaized.net/video.m4s",
                       "backups": ["https://upos-sz-mirrorcosov.bilivideo.com/video.m4s"],
                       "codecs": "avc1.640028", "height": 1080, "bandwidth": 1000}],
            "audio": [{"url": "https://upos-sz-mirrorcosov.bilivideo.com/audio.m4s", "codecs": "mp4a.40.2"}]}


def test_player_plan_uses_actual_backup_and_never_invents_urls():
    p = player(10000)
    plan = source_browser.plan(p, p["id"], 10000)
    assert plan["video"][0] == p["video"][0]["backups"][0]
    assert set(plan["video"]) == {p["video"][0]["url"], *p["video"][0]["backups"]}


@pytest.mark.parametrize("change", ["identity", "encrypted", "drm", "private", "future", "header", "expired"])
def test_player_identity_encryption_urls_and_publication_date_fail_closed(change):
    p = player(10000)
    if change == "identity": p["id"] = "wrong"
    elif change == "encrypted": p["encrypted"] = True
    elif change == "drm": p["video"][0]["drm"] = True
    elif change == "private": p["video"][0]["url"] = "https://127.0.0.1/video.m4s"
    elif change == "future": p["published"] = 10001
    elif change == "header": p["user_agent"] = "Safari\r\nInjected: true"
    else: p["video"][0]["url"] += "?deadline=9999"
    with pytest.raises(AccessError):
        source_browser.plan(p, "BV1234567890", 10000)


def test_source_capture_only_queues_independent_media_and_records_observed_metrics(video_store, video_cfg, at, monkeypatch):
    from src.x import safari, safari_video
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"bilibili": {"safari_player": True}},
                  permissions={"grant": video_cfg.permissions["grant"] | {"platform": "bilibili"}})
    connectors.ingest(video_store, "bilibili", [{"canonical_url": "https://www.bilibili.com/video/BV1234567890",
        "source_id": "BV1234567890", "creator": "creator", "permission_id": "grant"}], now, cfg)
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(player(now)))
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
    assert not video_store.rows("SELECT * FROM reservations")
    assert video_store.rows("SELECT kind,state FROM jobs") == [{"kind": "media", "state": "pending"}]
    assert len(video_store.rows("SELECT * FROM observations")) == 1
    assert source_browser.capture_next(video_store, cfg, now + 30) is None
