from contextlib import nullcontext
import json
import shutil
import subprocess

import pytest

from src.video import native_source
from src.video.security import AccessError
from src.x import safari, safari_video


@pytest.mark.parametrize("route", ["p", "reel", "reels"])
def test_instagram_redirect_preserves_exact_shortcode(video_cfg, at, monkeypatch, route):
    url = "https://www.instagram.com/" + route + "/ClipAbC"
    row = {"document": {"platform": "instagram", "source_id": "ClipAbC", "canonical_url": url, "creator": ""}}
    payload = {"canonical_url": "https://www.instagram.com/reel/ClipAbC/", "published": at().timestamp() - 60,
               "creator": "creator", "title": "Example Star dancing", "media": ["https://cdn.cdninstagram.com/source.mp4"],
               "user_agent": "fixture browser"}
    monkeypatch.setattr(safari_video, "browser_session", nullcontext)
    monkeypatch.setattr(safari, "open_url", lambda url: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(payload))
    doc = native_source.capture(row, video_cfg, at().timestamp())
    assert doc["canonical_url"] == url and doc["source_download"]["source_id"] == "ClipAbC"
    payload["canonical_url"] = "https://www.instagram.com/reel/clipabc/"
    with pytest.raises(AccessError, match="identity differs"):
        native_source.capture(row, video_cfg, at().timestamp())


@pytest.mark.parametrize("code", ["ClipAbC", "wrong"])
def test_instagram_reads_only_exact_video_from_embedded_page_data(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the source-page fixture")
    media = {"code": code, "media_type": 2, "taken_at": 1790072845,
             "user": {"username": "creator"}, "caption": {"text": "Attributed Example Star music parody"},
             "video_versions": [{"width": 720, "height": 1280, "url": "https://cdn.cdninstagram.com/exact.mp4"}]}
    setup = """
const location={href:'https://www.instagram.com/reel/ClipAbC/'};
const navigator={userAgent:'fixture browser'};
const embedded=EMBEDDED;
const unrelated={currentSrc:'https://cdn.cdninstagram.com/recommended.mp4',
  getClientRects:()=>[{}],querySelectorAll:()=>[]};
const document={
  querySelector:s=>s==='link[rel="canonical"]'?{href:location.href}:null,
  querySelectorAll:s=>s==='script[type="application/json"]'?[{textContent:JSON.stringify({data:{items:[embedded]}})}]:s==='video'?[unrelated]:[],
  getElementById:()=>null
};
""".replace("EMBEDDED", json.dumps(media))
    result = subprocess.run([node, "-e", setup + "console.log(" + native_source.script("instagram", "ClipAbC") + ");"],
                            check=True, capture_output=True, text=True, timeout=10)
    observed = json.loads(result.stdout)
    if code == "ClipAbC":
        assert observed["published"] == media["taken_at"]
        assert observed["creator"] == "creator"
        assert observed["media"] == [media["video_versions"][0]["url"]]
    else:
        assert not observed["media"] and not observed["published"]


def test_redirected_instagram_tab_remains_scoped_to_exact_source(video_cfg, at, monkeypatch):
    url = "https://www.instagram.com/reel/ClipAbC"
    row = {"document": {"platform": "instagram", "source_id": "ClipAbC",
                         "canonical_url": url, "creator": "creator"}}
    payload = {"canonical_url": url, "published": at().timestamp()-60, "creator": "creator",
               "title": "Example Star dance", "media": ["https://cdn.cdninstagram.com/exact.mp4"],
               "user_agent": "fixture browser"}
    targets = []
    def read(js, *, target_url, **kwargs):
        targets.append(target_url)
        return json.dumps(payload) if target_url == url.replace("/reel/", "/reels/") else ""
    monkeypatch.setattr(safari_video, "browser_session", nullcontext)
    monkeypatch.setattr(safari, "open_url", lambda url: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", read)
    monkeypatch.setattr(native_source.time, "sleep", lambda _: None)
    assert native_source.capture(row, video_cfg, at().timestamp())["source_download"]["source_id"] == "ClipAbC"
    assert targets == [url, url.replace("/reel/", "/reels/")]
