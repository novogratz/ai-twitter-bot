import json
from pathlib import Path

import pytest

from src.video import inventory, media, operations, publisher, ranking
from src.video.store import Store, dumps


def test_confirmed_video_identity_survives_restart_and_file_cleanup(video_store, video_cfg, ready, at, tmp_path, monkeypatch):
    doc = ready("original")
    doc["original_fingerprint"] = {"sha256": doc["original_sha256"], "visual": [], "audio": [1, 2]}
    doc["output_fingerprint"] = {"sha256": doc["output_sha256"], "visual": [], "audio": [1, 2]}
    assets = tmp_path / "assets"
    folder = assets / "original"
    folder.mkdir(parents=True)
    original = folder / "original.mp4"
    original.write_bytes(Path(doc["original_path"]).read_bytes())
    doc.update(original_path=str(original), output_path=str(original))
    video_store.save_candidate("original", doc, at().timestamp(), state="ready", score=95)
    row = publisher.reserve(video_store, at(), video_cfg)
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (row["id"],))
    publisher.confirm(video_store, row["id"], row["token"], at().timestamp(), "123")
    restarted = Store(video_store.path)
    monkeypatch.setattr(operations, "ASSETS", assets)
    operations.cleanup(restarted, video_cfg, at(day=30).timestamp())
    assert not folder.exists()
    record = json.loads(restarted.rows("SELECT payload FROM history WHERE post_id='123'")[0]["payload"])
    for key in ("platform", "source_id", "creator", "original_sha256", "output_sha256", "original_fingerprint", "output_fingerprint"):
        assert record[key] == doc[key]
    assert record["source_url"] == doc["canonical_url"]
    assert record["url"] == "https://x.com/i/status/123" and "BANGER" in record["caption"]
    assert restarted.rows("SELECT * FROM content_claims")
    assert restarted.candidate("original")["state"] == "posted"
    # A differently named, cross-platform copy is still recognizable after all bytes are gone.
    copy = {**doc, "platform": "bilibili", "source_id": "another", "canonical_url": "https://www.bilibili.com/video/BVother"}
    assert media.matches_history(copy, record)


@pytest.mark.parametrize("identifier", ["source", "source_url", "original_sha256", "output_sha256", "original_fingerprint", "output_fingerprint", "fingerprint"])
def test_publisher_checks_permanent_history_independently_of_queue(video_store, video_cfg, ready, at, identifier):
    doc = ready()
    fp = {"sha256": doc["original_sha256"], "visual": [], "audio": []}
    doc["original_fingerprint"] = fp
    video_store.save_candidate("clip1", doc, at().timestamp(), state="ready", score=95)
    if identifier == "source":
        archived = {"platform": doc["platform"], "source_id": doc["source_id"]}
    elif identifier == "source_url":
        archived = {"source_url": doc["canonical_url"]}
    elif identifier.endswith("sha256"):
        archived = {identifier: doc["original_sha256"]}
    else:
        archived = {identifier: fp}
    with video_store.transaction() as db:
        db.execute("INSERT INTO history VALUES('old',?,?)", (at(day=1).timestamp(), dumps(archived)))
    assert not ranking.gate(doc, video_cfg, at().timestamp(), final=True)
    assert not video_store.rows("SELECT * FROM content_claims")
    assert inventory.report(video_store, video_cfg, at())["eligible_distinct"] == 0
    assert publisher.reserve(Store(video_store.path), at(), video_cfg) is None
    assert "permanent posting history" in video_store.candidate("clip1")["reason"]


def test_shared_music_alone_does_not_match_posting_history():
    first = {"sha256": "a", "visual": [["0000000000000000"]] * 8, "audio": [1, 2, 3]}
    second = {"sha256": "b", "visual": [["ffffffffffffffff"]] * 8, "audio": [1, 2, 3]}
    assert not media.matches_history({"original_fingerprint": first}, {"output_fingerprint": second})


def test_cleanup_keeps_operator_selected_files_without_waiving_freshness(video_store, video_cfg, ready, at, tmp_path, monkeypatch):
    doc = ready("selected")
    assets = tmp_path / "assets"
    folder = assets / "selected" / "operator-review"
    folder.mkdir(parents=True)
    original = folder / "original.mp4"
    original.write_bytes(b"saved operator original")
    preview = assets / "selected" / "preview"
    preview.mkdir()
    (preview / "draft.mp4").write_bytes(b"local draft")
    doc.update(original_path=str(original), operator_edit_request={"state": "pending"})
    video_store.save_candidate("selected", doc, at().timestamp(), state="held")
    monkeypatch.setattr(operations, "ASSETS", assets)
    operations.cleanup(video_store, video_cfg, at(day=30).timestamp())
    assert original.read_bytes() == b"saved operator original"
    assert (preview / "draft.mp4").read_bytes() == b"local draft"
    assert video_store.candidate("selected")["state"] == "expired"
    assert ranking.gate(doc, video_cfg, at(day=30).timestamp()) == "publication time unverified or clip stale"


def test_cleanup_keeps_an_expired_candidates_inflight_media_files(video_store, video_cfg, ready, at, tmp_path, monkeypatch):
    ready("inflight")
    now = at(day=30).timestamp()
    assets = tmp_path / "assets"
    folder = assets / "inflight" / "running-attempt"
    folder.mkdir(parents=True)
    original = folder / "original.mp4"
    original.write_bytes(b"in use")
    video_store.enqueue("media", "inflight", now)
    video_store.claim("media", "worker", now, video_cfg)
    monkeypatch.setattr(operations, "ASSETS", assets)
    operations.cleanup(video_store, video_cfg, now)
    assert original.read_bytes() == b"in use"
    operations.cleanup(video_store, video_cfg, now + video_cfg.lease_seconds + 1)
    assert not folder.exists()
