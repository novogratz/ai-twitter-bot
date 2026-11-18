from dataclasses import replace
import json

import pytest

from src.video import preview
from src.video.security import AccessError, Deferred


def preview_config(video_cfg):
    return replace(video_cfg, permissions={"standing": {
        "enabled": True, "operator_attested": True, "all_creators": True,
        "platforms": ["instagram"], "valid_until_revoked": True, "video": True,
        "audio": True, "editing": True, "x_publication": True, "overlay_removal": True,
        "evidence": "fixture operator permission"}})


def test_preview_respects_download_hold_and_never_queues_or_claims(video_store, video_cfg, tmp_path, monkeypatch):
    def capture(row, cfg, now):
        row["document"].update(creator="creator", published_at=now-60,
            publication_evidence="exact source page date", title="Example Star synthetic dance")
    def download(*args):
        raise Deferred("daily download budget exhausted")
    monkeypatch.setattr(preview.native_source, "capture", capture)
    monkeypatch.setattr(preview.media, "download", download)
    result = preview.prepare("https://www.instagram.com/reel/preview_clip", video_store,
                             preview_config(video_cfg), output_root=tmp_path)
    assert result["status"] == "held" and "download budget" in result["hold_reason"]
    assert result["published"] is result["queued"] is result["publication_ready"] is False
    assert not video_store.rows("SELECT * FROM candidates")
    assert not video_store.rows("SELECT * FROM reservations")
    assert not video_store.rows("SELECT * FROM content_claims")
    assert not video_store.rows("SELECT * FROM jobs")
    from pathlib import Path
    assert json.loads((Path(result["folder"])/"report.json").read_text())["status"] == "held"


def test_preview_never_reopens_a_posted_source(video_store, video_cfg, ready, tmp_path, monkeypatch):
    ready()
    with video_store.transaction() as db:
        db.execute("UPDATE candidates SET state='posted' WHERE id='clip1'")
    monkeypatch.setattr(preview.native_source, "capture", lambda *a: pytest.fail("opened a posted source"))
    with pytest.raises(AccessError, match="already posted"):
        preview.prepare("https://www.instagram.com/reel/clip1", video_store,
                        preview_config(video_cfg), output_root=tmp_path)


def test_preview_requires_instagram_identity_and_usage_permission(video_store, video_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(preview.native_source, "capture", lambda *a: pytest.fail("opened unapproved source"))
    with pytest.raises(ValueError):
        preview.prepare("https://evil.example/reel/clip", video_store, video_cfg, output_root=tmp_path)
    with pytest.raises(AccessError, match="permission"):
        preview.prepare("https://www.instagram.com/reel/clip", video_store, video_cfg, output_root=tmp_path)
