from contextlib import nullcontext
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.video import connectors, media, native_source, source_browser
from src.video.security import AccessError


@pytest.mark.parametrize("raw,upper", [("49.9K views", 49949), ("50K Views. View post analytics", 50499),
    ("50,000 views", 50000), ("50 001 views", 50001), ("100\u202f000 vues", 100000),
    ("50\u00a0001 views", 50001), ("12 likes 1 views", None), ("5 01 views", None),
    ("Views", None), ("1.2M views", 1249999), (True, None), (42, 42)])
def test_rounded_x_counter_never_falsely_proves_threshold(raw, upper):
    assert native_source.view_upper_bound(raw) == upper


@pytest.mark.parametrize("url", ["https://video.twimg.com.evil.test/a.mp4", "http://video.twimg.com/a.mp4",
    "https://video.twimg.com@127.0.0.1/a.mp4", "https://video.twimg.com:8080/a.mp4", "https://127.0.0.1/a.mp4"])
def test_native_source_cdn_is_strict(url):
    with pytest.raises(AccessError):
        native_source.media_host("x", url)


def test_normal_x_page_queues_media_without_publishing_or_model_call(video_store, video_cfg, at, monkeypatch):
    from src.x import safari, safari_video
    now = at().timestamp()
    url = "https://x.com/creator/status/123"
    cfg = replace(video_cfg, platforms={"x": {"safari_player": True}},
                  permissions={"grant": video_cfg.permissions["grant"] | {"platform": "x"}})
    connectors.ingest(video_store, "x", [{"canonical_url": url, "source_id": "123", "creator": "creator",
                                         "permission_id": "grant"}], now, cfg)
    payload = {"canonical_url": url, "published": now - 3600, "creator": "creator", "title": "Example Star dance parody",
               "views": "49.9K views", "media": ["https://video.twimg.com/ext_tw_video/321/pu/vid/a.mp4"],
               "user_agent": "Fixture Safari"}
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda url: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **kw: json.dumps(payload))
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
    row = video_store.rows("SELECT * FROM candidates")[0]
    doc = json.loads(row["document"])
    assert doc["source_metrics"]["views"] == 49949
    assert row["state"] == "discovered"
    assert video_store.rows("SELECT kind,state FROM jobs") == [{"kind": "media", "state": "pending"}]
    assert not video_store.rows("SELECT * FROM reservations")
    assert "inspection" not in doc


def test_x_above_ceiling_never_queues_download(video_store, video_cfg, at, monkeypatch):
    from src.x import safari, safari_video
    now = at().timestamp()
    url = "https://x.com/creator/status/123"
    cfg = replace(video_cfg, platforms={"x": {"safari_player": True}},
                  permissions={"grant": video_cfg.permissions["grant"] | {"platform": "x"}})
    connectors.ingest(video_store, "x", [{"canonical_url": url, "source_id": "123", "creator": "creator",
                                         "permission_id": "grant"}], now, cfg)
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda url: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **kw: json.dumps({"canonical_url": url,
        "published": now - 3600, "views": "50.1K views", "media": ["https://video.twimg.com/a.mp4"], "user_agent": "Safari"}))
    assert source_browser.capture_next(video_store, cfg, now) == "source player unavailable"
    assert not video_store.rows("SELECT * FROM jobs")
    assert "50000" in video_store.rows("SELECT reason FROM candidates")[0]["reason"]


def plan_doc(now, url):
    return {"platform": "x", "source_id": "123", "canonical_url": "https://x.com/creator/status/123",
        "source_download": {"platform": "x", "source_id": "123", "captured_at": now, "expires_at": now + 3600,
                            "user_agent": "Safari", "media": [url]}}


def test_source_hls_downloads_only_observed_segments_and_remuxes_offline(video_store, video_cfg, tmp_path, monkeypatch):
    now = 10000
    url = "https://video.twimg.com/source/master.m3u8"
    responses = {url: b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nmedia.m3u8\n",
        "https://video.twimg.com/source/media.m3u8": b"#EXTM3U\n#EXTINF:3,\none.ts\n#EXTINF:3,\ntwo.ts\n#EXT-X-ENDLIST\n",
        "https://video.twimg.com/source/one.ts": b"segmentone", "https://video.twimg.com/source/two.ts": b"segmenttwo"}
    calls = []
    def fetch(url, *, sink, **kw):
        calls.append(url)
        sink.write(responses[url])
    def ffmpeg(args, cfg):
        assert args[:2] == ["-protocol_whitelist", "file,pipe"]
        assert Path(args[3]).read_bytes() == b"segmentonesegmenttwo"
        Path(args[-1]).write_bytes(b"remuxed")
    monkeypatch.setattr(native_source, "request", fetch)
    monkeypatch.setattr(media, "ffmpeg", ffmpeg)
    destination = tmp_path / "original.mp4"
    native_source.download(plan_doc(now, url), destination, video_cfg, video_store, now)
    assert destination.read_bytes() == b"remuxed"
    assert calls == list(responses)
    used = sum(row["amount"] for row in video_store.rows("SELECT amount FROM costs WHERE kind='download_bytes'"))
    assert used == sum(len(data) for data in responses.values())


@pytest.mark.parametrize("manifest", [
    "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"secret\"\n#EXTINF:3,\none.ts\n#EXT-X-ENDLIST\n",
    "#EXTM3U\n#EXTINF:3,\none.ts\n",
    "#EXTM3U\n#EXTINF:3,\nhttps://evil.test/one.ts\n#EXT-X-ENDLIST\n",
])
def test_hls_rejects_encryption_live_or_unapproved_segment_host(video_store, video_cfg, tmp_path, monkeypatch, manifest):
    calls = []
    def fetch(url, *, sink, **kw):
        calls.append(url)
        sink.write(manifest.encode())
    monkeypatch.setattr(native_source, "request", fetch)
    url = "https://video.twimg.com/source.m3u8"
    with pytest.raises(AccessError):
        native_source.download(plan_doc(10000, url), tmp_path / "source.mp4", video_cfg, video_store, 10000)
    assert calls == [url]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="real FFmpeg fixture needs local binaries")
def test_split_hls_preserves_real_video_and_audio_and_skips_audio_only_variant(video_store, video_cfg, tmp_path, monkeypatch):
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=96x96:rate=10", "-t", "2", "-an", "-c:v", "libx264",
                  "-g", "10", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
                  "-hls_segment_filename", str(tmp_path / "video%d.ts"), str(tmp_path / "video.m3u8")], video_cfg)
    media.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "2", "-vn", "-c:a", "aac",
                  "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
                  "-hls_segment_filename", str(tmp_path / "audio%d.ts"), str(tmp_path / "audio.m3u8")], video_cfg)
    master = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="sound",NAME="original",DEFAULT=YES,AUTOSELECT=YES,URI="audio.m3u8"\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=50000,CODECS="mp4a.40.2"\nonly-audio.m3u8\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=300000,RESOLUTION=96x96,CODECS="avc1.64000a,mp4a.40.2",AUDIO="sound"\nvideo.m3u8\n')
    calls = []
    def fetch(url, *, sink, **kw):
        name = url.rsplit("/", 1)[-1]
        calls.append(name)
        sink.write(master.encode() if name == "master.m3u8" else (tmp_path / name).read_bytes())
    monkeypatch.setattr(native_source, "request", fetch)
    result = tmp_path / "result.mp4"
    native_source.download(plan_doc(10000, "https://video.twimg.com/master.m3u8"), result, video_cfg, video_store, 10000)
    probe = media.probe(result, video_cfg)
    assert probe["video_codec"] == "h264" and probe["audio_codec"] == "aac"
    assert 1.9 <= probe["duration"] <= 2.2
    assert "audio.m3u8" in calls and "only-audio.m3u8" not in calls
    from array import array
    pcm = array("h", media.ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(result), "-vn",
                                   "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"], video_cfg))
    assert max(map(abs, pcm)) > 100


@pytest.mark.skipif(not shutil.which("node"), reason="DOM script fixture needs Node")
@pytest.mark.parametrize("identity,expected_media", [("https://www.instagram.com/reel/wrong", []),
    ("https://www.instagram.com/reel/123", ["https://cdn.cdninstagram.com/source.mp4"])])
def test_normal_page_script_rejects_explicit_foreign_video_object_and_ambiguous_visible_players(identity, expected_media):
    data = {"@type": "VideoObject", "url": identity, "uploadDate": "2026-01-01T00:00:00Z",
            "contentUrl": "https://cdn.cdninstagram.com/source.mp4"}
    setup = """const location={href:'https://www.instagram.com/reel/123'};
      const navigator={userAgent:'Fixture'};
      const foreign={getClientRects:()=>[1],currentSrc:'https://cdn.cdninstagram.com/foreign.mp4'};
      const document={querySelector:s=>s==='link[rel="canonical"]'?{href:location.href}:null,
        querySelectorAll:s=>s==='video'?[foreign,foreign]:s==='script[type="application/ld+json"]'?[{textContent:DATA}]:[],
        getElementById:()=>null};
    """.replace("DATA", json.dumps(json.dumps(data)))
    result = subprocess.run(["node", "-e", setup + "console.log(" + native_source.script("instagram", "123") + ");"],
                            check=True, capture_output=True, text=True, timeout=10)
    payload = json.loads(result.stdout)
    assert payload.get("media", []) == expected_media
