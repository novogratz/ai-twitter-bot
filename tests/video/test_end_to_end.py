"""Real local media, mocked semantic/X observations; never a real celebrity proof."""
from pathlib import Path
import shutil
import time

import pytest

from src.video import connectors, media, ranking, reconcile


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="optional ffmpeg integration")
def test_discovery_to_ready_with_explicit_fixture_semantics(video_store, video_cfg, tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    if not Path(video_cfg.font_file).exists():
        pytest.skip("optional renderer font")
    original = tmp_path / "owned-test-fixture.mp4"
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=4", "-f", "lavfi", "-i",
                  "sine=frequency=440:duration=4", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-shortest", str(original)], video_cfg)
    now = time.time()
    for n in range(6):
        item = {"source_id": f"fixture{n}", "creator": "creator", "canonical_url": f"https://www.instagram.com/reel/fixture{n}",
                "published_at": now - 3600, "publication_evidence": "fixture timestamp", "permission_id": "grant",
                "local_file": str(original), "metrics": {"views": 100}, "metrics_observed_at": now - 600}
        connectors.ingest(video_store, "instagram", [item], now, video_cfg)
        item.update(metrics={"views": 10000 if n == 0 else 200}, metrics_observed_at=now)
        connectors.ingest(video_store, "instagram", [item], now, video_cfg)
    job = video_store.claim("media", "fixture-worker", now, video_cfg)
    # This fake inspector is confined to pytest. It proves orchestration only;
    # a color pattern is not evidence of a real target person's performance.
    def fixture_inspect(path, stage, cfg, store, now, **extra):
        from src.video.security import sha256
        if stage == "output":
            return {"version": 1, "sha256": sha256(path), "full_clip_inspected": True,
                    "overlays_clean": True, "watermark_present": True}
        return {"version": 1, "sha256": sha256(path), "confidence": .99, "cast": ["performer"], "performance": "dance",
                "audio_inspected": True, "full_clip_inspected": True, "synthetic_parody": True, "unsafe": False,
                "evidence": [{"at": x, "observation": "mocked semantic observation"} for x in (.1, 2, 3.9)],
                "fit_score": 20, "entertainment_score": 20, "quality_score": 15,
                "safe_crop": [0, 0, 320, 240], "crop_preserves_action": True, "overlays_removable_by_crop": True,
                "watermark_position": "bottom", "watermark_clear_of_action": True}
    monkeypatch.setattr(media, "inspect", fixture_inspect)
    media.process(video_store, job, now, video_cfg)
    row = video_store.candidate(job["item"])
    assert row["state"] == "held" and row["document"]["novelty"]["state"] == "unchecked"
    class FixtureSearch:
        def search(self, query, cursor): return {"data": [], "meta": {}}
    assert reconcile.novelty(video_store, row, FixtureSearch(), video_cfg, time.time()) == "checked_no_match"
    row = video_store.candidate(job["item"])
    assert row["state"] == "ready"
    assert not ranking.gate(row["document"], video_cfg, time.time(), final=True)
    assert Path(row["document"]["output_path"]).is_file()
    assert row["document"]["ranking"]["total"] >= 80
    assert "BANGER" in row["document"]["caption"]
    assert not video_store.rows("SELECT * FROM reservations")
