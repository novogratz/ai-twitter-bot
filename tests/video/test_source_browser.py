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


def test_visible_related_links_are_bounded_unverified_leads_not_metadata_approval(video_cfg):
    link = {"url": "https://www.bilibili.com/en/video/BV1234567890/?track=123",
            "title": "Example Star dance music parody", "confidence": 1, "permission_id": "forged"}
    links = [link, link, {"url": "https://evil.test/video/BV1234567890", "title": link["title"]},
             {"url": "https://www.bilibili.com/video/BV1234567891", "title": "Example Star interview"}]
    result = source_browser.related_candidates(links, video_cfg, "source", 1000)
    assert len(result) == 1
    assert result[0]["canonical_url"] == "https://www.bilibili.com/video/BV1234567890"
    assert result[0]["published_at"] is None and result[0]["creator"] == ""
    assert "permission_id" not in result[0] and "confidence" not in result[0]
    assert source_browser.related_candidates(None, video_cfg, "source", 1000) == []


def test_generated_related_clip_after_ten_real_dances_gets_a_preparation_lead(video_cfg):
    links = [{"url": f"https://www.bilibili.com/video/BV{number:010d}",
              "title": "Example Star dance at a real event"} for number in range(11)]
    generated = {"url": "https://www.bilibili.com/video/BV1234567890",
                 "title": "Example Star AI dance parody"}
    result = source_browser.related_candidates(links + [generated], video_cfg, "fixture", 1000)
    assert len(result) == 10
    assert result[0]["canonical_url"] == generated["url"]
    assert [item["canonical_url"] for item in result[1:]] == [item["url"] for item in links[:9]]
    assert all(item["published_at"] is None and "inspection" not in item and "permission_id" not in item
               for item in result)
    # Rank within the bounded visible shelf; do not fetch or scan another page.
    assert generated["url"] not in {item["canonical_url"] for item in source_browser.related_candidates(
        links + [None] * 69 + [generated], video_cfg, "fixture", 1000)}


def test_small_source_can_use_remaining_bytes_and_refunds_partial_failures(video_store, video_cfg, tmp_path, monkeypatch):
    from src.video import media
    from pathlib import Path
    cfg = replace(video_cfg, max_download_bytes=150, download_budget_bytes=2000)
    now = 10000
    assert video_store.budget("prior", "download_bytes", 1900, 2000, now)
    p = player(now)
    doc = dict(platform="bilibili", source_id=p["id"], source_download=source_browser.plan(p, p["id"], now))
    calls = []
    def fetch(url, *, sink, max_bytes, **kw):
        calls.append(max_bytes)
        if len(calls) == 1:
            sink.write(b"x" * 10)
            raise AccessError("incomplete response body")
        sink.write(b"x" * (40 if url.endswith("/video.m4s") else 5))
    monkeypatch.setattr(source_browser, "request", fetch)
    monkeypatch.setattr(media, "ffmpeg", lambda args, cfg: Path(args[-1]).write_bytes(b"original"))
    source_browser.download_player(doc, tmp_path / "original.mp4", cfg, video_store, now)
    assert calls == [100, 90, 50]
    assert sum(r["amount"] for r in video_store.rows("SELECT amount FROM costs WHERE kind='download_bytes'")) == 1955


@pytest.mark.parametrize("unsupported_count", [1, 81])
def test_unsupported_leads_cannot_hide_valid_bilibili_sources_behind_scan_limit(
        video_store, video_cfg, at, monkeypatch, unsupported_count):
    from src.x import safari, safari_video
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"bilibili": {"safari_player": True}},
                  permissions={"grant": video_cfg.permissions["grant"] | {"platform": "bilibili"}})
    leads = [{"source_id": f"av{64049836 + i}",
              "canonical_url": f"https://www.bilibili.com/video/av{64049836 + i}",
              "creator": "creator", "permission_id": "grant", "published_at": now - i - 1,
              "publication_evidence": "fixture source date"} for i in range(unsupported_count)]
    leads.append({"source_id": "BV1234567890", "canonical_url": "https://www.bilibili.com/video/BV1234567890",
                  "creator": "creator", "permission_id": "grant", "published_at": now - 3600,
                  "publication_evidence": "fixture source date"})
    assert connectors.ingest(video_store, "bilibili", leads, now, cfg) == unsupported_count + 1
    calls = []
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda url: calls.append(url) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(player(now)))
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
    assert calls == ["https://www.bilibili.com/en/video/BV1234567890/"]
    assert video_store.rows("SELECT source_id FROM candidates WHERE json_extract(document,'$.source_capture_attempt') IS NOT NULL") == [{"source_id": "BV1234567890"}]
    assert not video_store.rows("SELECT * FROM reservations")
