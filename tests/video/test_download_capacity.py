"""Daily capacity waits differ from genuine per-file limit failures."""
from dataclasses import replace

import pytest

from src.video import native_source, reconcile, source_browser
from src.video.security import AccessError, Deferred


@pytest.mark.parametrize("route", ["history", "native", "bilibili"])
@pytest.mark.parametrize("remaining", [10, 150])
def test_insufficient_daily_capacity_defers_without_losing_partial_costs(
        video_store, video_cfg, at, tmp_path, monkeypatch, route, remaining):
    cfg = replace(video_cfg, max_download_bytes=150, download_budget_bytes=2000)
    now = at().timestamp()
    spent = cfg.download_budget_bytes - remaining
    assert video_store.budget("prior", "download_bytes", spent, cfg.download_budget_bytes, now)
    calls = []
    def fetch(url, *, sink, max_bytes, **kwargs):
        calls.append(max_bytes)
        sink.write(b"12345")
        raise AccessError("response exceeds byte budget")
    module = {"history": reconcile, "native": native_source, "bilibili": source_browser}[route]
    monkeypatch.setattr(module, "request", fetch)
    url = "https://video.twimg.com/fixture.mp4"
    destination = tmp_path / "original.mp4"
    if route == "history":
        source = {"variants": [{"content_type": "video/mp4", "url": url}]}
        action = lambda: reconcile.media_fingerprint(source, video_store, cfg, now, offload=False)
    else:
        source = {"platform": "bilibili" if route == "bilibili" else "x", "source_id": "fixture",
                  "canonical_url": "https://x.com/creator/status/123"}
        plan = {"platform": source["platform"], "source_id": "fixture", "captured_at": now,
                "expires_at": now + 3600, "user_agent": "fixture Safari"}
        if route == "bilibili":
            plan.update(video=["https://cdn.bilivideo.com/video.m4s"], audio=["https://cdn.bilivideo.com/audio.m4s"])
            action = lambda: source_browser.download_player(source, destination, cfg, video_store, now)
        else:
            plan["media"] = [url]
            action = lambda: native_source.download(source, destination, cfg, video_store, now)
        source["source_download"] = plan
    with pytest.raises(AccessError) as error:
        action()
    assert isinstance(error.value, Deferred) is (remaining < cfg.max_download_bytes)
    assert calls == [remaining]
    used = sum(row["amount"] for row in video_store.rows("SELECT amount FROM costs WHERE kind='download_bytes'"))
    assert used == spent + 5
    assert not destination.exists()


@pytest.mark.parametrize("route", ["native", "bilibili"])
def test_aggregate_file_cap_is_not_a_daily_capacity_wait(
        video_store, video_cfg, at, tmp_path, monkeypatch, route):
    cfg = replace(video_cfg, max_download_bytes=150, download_budget_bytes=2000)
    now = at().timestamp()
    platform = "bilibili" if route == "bilibili" else "x"
    plan = {"platform": platform, "source_id": "fixture", "captured_at": now,
            "expires_at": now + 3600, "user_agent": "fixture Safari"}
    doc = {"platform": platform, "source_id": "fixture", "source_download": plan,
           "canonical_url": "https://x.com/creator/status/123"}
    calls = []
    def fetch(url, *, sink, **kwargs):
        calls.append(url)
        sink.write(b"x" * cfg.max_download_bytes)
        if route == "native":
            raise AccessError("incomplete response body")
    if route == "bilibili":
        plan.update(video=["https://cdn.bilivideo.com/video.m4s"], audio=["https://cdn.bilivideo.com/audio.m4s"])
        module, action = source_browser, source_browser.download_player
    else:
        plan["media"] = ["https://video.twimg.com/one.mp4", "https://video.twimg.com/two.mp4"]
        module, action = native_source, native_source.download
    monkeypatch.setattr(module, "request", fetch)
    with pytest.raises(AccessError) as error:
        action(doc, tmp_path / "original.mp4", cfg, video_store, now)
    assert not isinstance(error.value, Deferred)
    assert len(calls) == 1
    assert sum(row["amount"] for row in video_store.rows("SELECT amount FROM costs WHERE kind='download_bytes'")) == 150
