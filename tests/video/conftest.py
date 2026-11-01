from datetime import datetime
import hashlib

import pytest

from src.video.config import VideoConfig
from src.video.schedule import ZONE
from src.video.store import Store, dumps


@pytest.fixture
def at():
    return lambda h=7, m=0, s=0, day=2: datetime(2026, 11, day, h, m, s, tzinfo=ZONE)


@pytest.fixture
def video_cfg(tmp_path):
    return VideoConfig(publishing_transport="api", paired_windows=("07:00", "09:00", "21:00"),
        watermark="@TestAccount", targets={"performer": ["Example Star", "示例"]},
        local_import_roots=(str(tmp_path),), permissions={"grant": {"platform": "instagram", "creator": "creator",
        "video": True, "audio": True, "editing": True, "x_publication": True, "overlay_removal": True,
        "evidence": "fixture permission; not a real creator license", "expires_at": 2_000_000_000}})


@pytest.fixture
def video_store(tmp_path, settings_override):
    settings_override(VIDEO_ENABLED=True, VIDEO_LIVE=True, DRY_RUN=False, HOURLY_BREAK_MINUTES=0)
    store = Store(tmp_path / "pipeline.db")
    for key, value in {"paused": False, "history_import_complete": True, "account_verified": True}.items():
        store.set_meta(key, value)
    return store


@pytest.fixture
def ready(video_store, video_cfg, at, tmp_path):
    def add(ident="clip1", when=None, score=95):
        now = (when or at()).timestamp()
        path = tmp_path / (ident + ".mp4")
        path.write_bytes(("fixture bytes " + ident).encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        doc = {"platform": "instagram", "source_id": ident, "creator": "creator", "permission_id": "grant",
               "canonical_url": "https://www.instagram.com/reel/" + ident, "published_at": now - 3600,
               "publication_evidence": "fixture", "probe": {"duration": 20}, "original_sha256": digest,
               "original_path": str(path), "output_path": str(path), "output_sha256": digest,
               "brand": video_cfg.watermark,
               "inspection": {"sha256": digest, "confidence": .99, "performance": "dance", "cast": ["performer"],
                              "audio_inspected": True, "full_clip_inspected": True, "synthetic_parody": True, "unsafe": False,
                              "evidence": [{"at": t, "observation": "fixture performance"} for t in (1, 10, 19)],
                              "fit_score": 20, "entertainment_score": 20, "quality_score": 15},
               "qc": {"sha256": digest, "decoded": True, "audio_sync": True, "no_new_black_freeze": True,
                      "overlays_clean": True, "watermark_present": True},
               "novelty": {"state": "checked_no_match", "checked_at": now},
               "ranking": {"total": score, "scored_at": now}}
        with video_store.transaction() as db:
            db.execute("INSERT INTO candidates(id,platform,source_id,canonical_url,creator,published,discovered,updated,state,document,score) "
                       "VALUES(?,?,?,?,?,?,?,?,'ready',?,?)", (ident, "instagram", ident, doc["canonical_url"], "creator",
                       doc["published_at"], now, now, dumps(doc), score))
        return doc
    return add
