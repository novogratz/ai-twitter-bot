from pathlib import Path
import shutil
import socket
import sys

import pytest

from src.video import media, ranking
from src.video.security import AccessError, imported_file, public_addresses, sha256, validate_url


@pytest.mark.parametrize("to_sink", [False, True])
@pytest.mark.parametrize("declared, body, method, incomplete", [
    (8, b"complete", "GET", False),
    (80, b"partial", "GET", True),
    (80, b"", "HEAD", False),
])
def test_download_rejects_premature_eof(monkeypatch, to_sink, declared, body, method, incomplete):
    """An HTTP 200 with a short body must never become a saved original."""
    import io
    from src.video import security

    class Response:
        status = 200
        headers = {"Content-Length": str(declared), "Content-Type": "video/mp4"}

        def __init__(self):
            self.body = io.BytesIO(body)

        def getheader(self, name, default=None):
            return self.headers.get(name, default)

        def read(self, size):
            return self.body.read(size)

    class Connection:
        sock = None
        closed = False

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(security, "_PinnedHTTPS", lambda *a, **k: connection)
    monkeypatch.setattr(security.time, "sleep", lambda *_: None)
    sink = io.BytesIO() if to_sink else None
    kwargs = dict(hosts={"cdn.test"}, method=method, sink=sink, max_bytes=100, mime={"video/mp4"})
    if incomplete:
        with pytest.raises(AccessError, match="incomplete response body"):
            security.request("https://cdn.test/original.mp4", **kwargs)
    else:
        data, _, count = security.request("https://cdn.test/original.mp4", **kwargs)
        assert count == len(body)
        assert (sink.getvalue() if to_sink else data) == body
    assert connection.closed


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://cdn.test/a.mp4", "https://user:pass@cdn.test/a.mp4",
                                "https://cdn.test:444/a.mp4", "https://evil.test/a.mp4", "https://cdn.test/a\n.mp4"])
def test_download_url_validation(url):
    with pytest.raises(AccessError):
        validate_url(url, {"cdn.test"})


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"])
def test_private_dns_refused_even_for_allowlisted_host(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (ip, 443))])
    with pytest.raises(AccessError):
        public_addresses("cdn.test")


def test_local_import_cannot_escape_via_symlink(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "outside"
    secret.write_bytes(b"private")
    (allowed / "link").symlink_to(secret)
    with pytest.raises(AccessError):
        imported_file(allowed / "link", [str(allowed)])


def test_saved_operator_originals_count_toward_storage_budget(video_store, video_cfg, ready, at, tmp_path, monkeypatch):
    from dataclasses import replace
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "original.mp4").write_bytes(b"x" * 20)
    monkeypatch.setattr(media, "ASSETS", tmp_path / "assets")
    monkeypatch.setattr(media, "SAVED_ASSETS", saved)
    cfg = replace(video_cfg, max_download_bytes=100, storage_budget_bytes=310)
    with pytest.raises(AccessError, match="storage budget exhausted"):
        media.download(ready(), tmp_path / "output.mp4", cfg, video_store, at().timestamp())


def test_provider_deadline_and_output_limits():
    with pytest.raises(TimeoutError):
        media.bounded_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=.1)
    with pytest.raises(ValueError, match="output limit"):
        media.bounded_command([sys.executable, "-c", "print('x'*10000)"], max_output=100)


def test_dedup_cross_platform_crop_overlay_variants_and_music_alone():
    visual = [[f"{i * 123456789:016x}", f"{i * 987654321:016x}"] for i in range(1, 10)]
    a = {"sha256": "a", "visual": visual, "audio": [1, 2, 3, 4]}
    b = {"sha256": "b", "visual": [[x[1]] for x in visual], "audio": [1, 2, 3, 4]}
    assert media.duplicate(a, b)
    c = {"sha256": "c", "visual": [["ffffffffffffffff"] for _ in visual], "audio": [1, 2, 3, 4]}
    assert not media.duplicate(a, c)


def test_cleanup_refuses_destructive_crops_and_unimplemented_inpainting(video_cfg, tmp_path):
    info = {"width": 1000, "height": 1000}
    evidence = {"safe_crop": [0, 0, 500, 500], "crop_preserves_action": True, "overlays_removable_by_crop": True}
    with pytest.raises(ValueError, match="destructive"):
        media.render(tmp_path / "a", tmp_path / "b", info, evidence, video_cfg)
    evidence.update(safe_crop=[0, 0, 1000, 1000], overlays_removable_by_crop=False)
    with pytest.raises(ValueError, match="unavailable cleanup"):
        media.render(tmp_path / "a", tmp_path / "b", info, evidence, video_cfg)


def test_failed_quality_and_unverified_audio_are_ineligible(ready, video_cfg, at):
    doc = ready()
    doc["inspection"]["audio_inspected"] = False
    assert "video/audio" in ranking.gate(doc, video_cfg, at().timestamp(), final=True)
    doc["inspection"]["audio_inspected"] = True
    doc["qc"]["watermark_present"] = False
    assert "quality" in ranking.gate(doc, video_cfg, at().timestamp(), final=True)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="optional ffmpeg media integration")
def test_real_ffmpeg_clean_brand_decode_sync_and_original_unchanged(video_cfg, tmp_path):
    pytest.importorskip("numpy")
    font = Path(video_cfg.font_file)
    if not font.exists():
        pytest.skip("set platform font for optional renderer integration")
    original, output = tmp_path / "fixture.mp4", tmp_path / "branded.mp4"
    # Owned engineering test pattern, not a claimed celebrity or licensed creator sample.
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=4",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-threads", "1",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(original)], video_cfg)
    before = sha256(original)
    info = media.probe(original, video_cfg)
    evidence = {"safe_crop": [0, 0, 320, 240], "crop_preserves_action": True, "overlays_removable_by_crop": True,
                "watermark_position": "bottom", "watermark_clear_of_action": True}
    media.render(original, output, info, evidence, video_cfg)
    result = media.technical_qc(original, output, info, video_cfg)
    assert sha256(original) == before
    assert result["decoded"] and result["audio_sync"]
    assert result["probe"]["fps"] == 24
    assert result["probe"]["width"] == 320 and result["probe"]["height"] == 240
    assert media.duplicate(media.fingerprint(original, info, video_cfg), media.fingerprint(output, result["probe"], video_cfg))
