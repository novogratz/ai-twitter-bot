"""Supply progress and completed holds; all media/browser evidence is isolated."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.video import connectors, media, native_source, preparation, ranking, source_browser, workers
from src.video.security import AccessError, Deferred, sha256
from src.x import safari, safari_video


@pytest.mark.parametrize("outcome", ["unsupported_duration", "missing_audio", "negative_source_review"])
def test_completed_media_hold_keeps_original_and_does_not_repeat_each_window(
        video_store, video_cfg, at, tmp_path, monkeypatch, outcome):
    cfg = replace(video_cfg, publishing_transport="safari")
    clock = [at().timestamp()]
    monkeypatch.setattr(media.time, "time", lambda: clock[0])
    monkeypatch.setattr(media, "ASSETS", tmp_path / "managed")
    monkeypatch.setattr(workers.video_pressure, "pressure", lambda *a: "")
    monkeypatch.setattr(workers, "_api_work", lambda *a: None)
    original = tmp_path / "owned-fixture.mp4"
    original.write_bytes(b"complete owned test bytes; semantic and ffprobe results are mocked")
    item = {"source_id": "supply", "canonical_url": "https://www.instagram.com/reel/supply",
            "creator": "creator", "permission_id": "grant", "published_at": clock[0] - 60,
            "publication_evidence": "fixture source timestamp", "local_file": str(original)}
    assert connectors.ingest(video_store, "instagram", [item], clock[0], cfg) == 1
    ident = video_store.rows("SELECT id FROM candidates")[0]["id"]
    downloads, reviews = [], []
    download = media.download
    def recording_download(*args):
        downloads.append(True)
        return download(*args)
    monkeypatch.setattr(media, "download", recording_download)
    probe = {"format": {"duration": "4"}, "streams": [
        {"codec_type": "video", "width": 320, "height": 240, "avg_frame_rate": "24/1", "codec_name": "h264"},
        {"codec_type": "audio", "codec_name": "aac"}]}
    if outcome == "unsupported_duration":
        probe["format"]["duration"] = str(cfg.max_duration_seconds + 1)
    elif outcome == "missing_audio":
        probe["streams"].pop()
    def command(args, **kwargs):
        assert args[0] == "ffprobe", "completed held source reached another media command"
        return json.dumps(probe)
    monkeypatch.setattr(media, "bounded_command", command)
    monkeypatch.setattr(media, "fingerprint", lambda path, *a: {"sha256": sha256(path), "visual": []})
    def review(path, stage, *args, **kwargs):
        assert outcome == "negative_source_review" and stage == "source"
        reviews.append(stage)
        return {"sha256": sha256(path), "confidence": .99, "performance": "dance", "cast": ["performer"],
                "audio_inspected": True, "full_clip_inspected": True, "synthetic_parody": True, "unsafe": True,
                "evidence": [{"at": t, "observation": "fixture review"} for t in (.1, 2, 3.9)]}
    monkeypatch.setattr(media, "inspect", review)
    monkeypatch.setattr(media, "render", lambda *a: pytest.fail("rejected source reached rendering"))
    assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "processed"
    row = video_store.candidate(ident)
    doc = row["document"]
    assert row["state"] == "held"
    assert Path(doc["original_path"]).read_bytes() == original.read_bytes()
    assert doc["original_sha256"] == sha256(original)
    assert doc["preparation_hold"]["sha256"] == doc["original_sha256"]
    assert doc["preparation_hold"]["stage"] == ("source_review" if reviews else "probe")
    assert "output_path" not in doc and "qc" not in doc
    for _ in range(cfg.max_attempts + 1):
        clock[0] += 7200
        with video_store.transaction() as db:
            preparation.recover_supply(db, cfg, clock[0])
        assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "idle"
    assert downloads == [True]
    assert reviews == (["source"] if outcome == "negative_source_review" else [])
    assert video_store.rows("SELECT state,error FROM jobs WHERE kind='media'") == [{"state": "done", "error": ""}]
    assert not video_store.rows("SELECT * FROM reservations")


def _player(source_id, now, duration=30):
    return {"id": source_id, "published": now - 3600, "creator": "creator", "duration": duration,
            "user_agent": "fixture Safari", "encrypted": False,
            "video": [{"url": "https://cdn.bilivideo.com/video.m4s", "codecs": "avc1.640028", "height": 720}],
            "audio": [{"url": "https://cdn.bilivideo.com/audio.m4s", "codecs": "mp4a.40.2"}]}


def _source_cfg(video_cfg, platform):
    return replace(video_cfg, platforms={platform: {"safari_player": True}},
                   permissions={"grant": video_cfg.permissions["grant"] | {"platform": platform}})


def _source(video_store, cfg, platform, source_id, now, published, **extra):
    base = {"bilibili": "https://www.bilibili.com/video/", "instagram": "https://www.instagram.com/reel/",
            "x": "https://x.com/creator/status/"}[platform]
    assert connectors.ingest(video_store, platform, [{"source_id": source_id, "canonical_url": base + source_id,
        "creator": "creator", "permission_id": "grant", "published_at": published,
        "publication_evidence": "fixture source timestamp"}], now, cfg) == 1
    ident = video_store.rows("SELECT id FROM candidates WHERE source_id=?", (source_id,))[0]["id"]
    row = video_store.candidate(ident)
    video_store.save_candidate(ident, row["document"] | extra, now, state="held")
    return ident


@pytest.fixture
def saved_x_media(video_store, video_cfg, at, tmp_path, monkeypatch):
    cfg = replace(_source_cfg(video_cfg, "x"), publishing_transport="safari")
    clock = [at().timestamp()]
    monkeypatch.setattr(media.time, "time", lambda: clock[0])
    assets = tmp_path / "managed"
    monkeypatch.setattr(media, "ASSETS", assets)
    monkeypatch.setattr(workers.video_pressure, "pressure", lambda *a: "")
    monkeypatch.setattr(workers, "_api_work", lambda *a: None)
    ident = _source(video_store, cfg, "x", "123456", clock[0], clock[0] - 60)
    original = assets / ident / "saved" / "original.mp4"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"owned saved source; decoding and semantic review are mocked")
    doc = video_store.candidate(ident)["document"]
    doc.update(original_path=str(original), original_sha256=sha256(original),
        original_fingerprint={"sha256": sha256(original), "visual": []},
        source_metrics={"views": 100, "observed_at": clock[0], "source_url": doc["canonical_url"]})
    video_store.save_candidate(ident, doc, clock[0], state="held", fingerprint=doc["original_fingerprint"])
    video_store.enqueue("media", ident, clock[0])
    calls = []
    info = {"duration": 4, "width": 320, "height": 240, "fps": 24}
    def probe(*args):
        calls.append("probe")
        return info
    def inspect(path, stage, *args, **kwargs):
        calls.append(stage)
        if stage == "output":
            return {"sha256": sha256(path), "overlays_clean": True, "watermark_present": True}
        return {"sha256": sha256(path), "confidence": .99, "performance": "dance", "cast": ["performer"],
                "audio_inspected": True, "full_clip_inspected": True, "synthetic_parody": True, "unsafe": False,
                "fit_score": 20, "entertainment_score": 20, "quality_score": 15,
                "evidence": [{"at": t, "observation": "fixture review"} for t in (.1, 2, 3.9)]}
    def render(source, destination, *args):
        calls.append("render")
        destination.write_bytes(source.read_bytes() + b"fixture watermark")
    monkeypatch.setattr(media, "download", lambda *a: pytest.fail("saved complete original downloaded again"))
    monkeypatch.setattr(media, "probe", probe)
    monkeypatch.setattr(media, "fingerprint", lambda path, *a: {"sha256": sha256(path), "visual": []})
    monkeypatch.setattr(media, "inspect", inspect)
    monkeypatch.setattr(media, "render", render)
    monkeypatch.setattr(media, "technical_qc", lambda *a: {"probe": info, "decoded": True,
        "audio_sync": True, "no_new_black_freeze": True})
    return cfg, clock, ident, calls, original


@pytest.mark.parametrize("state", ["stale", "unverified", "expires_during_inspection"])
def test_x_view_admission_waits_resume_saved_media_after_refresh(video_store, saved_x_media, monkeypatch, state):
    cfg, clock, ident, calls, original = saved_x_media
    doc = video_store.candidate(ident)["document"]
    if state == "unverified":
        doc["source_metrics"] = {}
    else:
        doc["source_metrics"]["observed_at"] -= 3599 if state == "expires_during_inspection" else 3601
    video_store.save_candidate(ident, doc, clock[0], state="held", fingerprint=doc["original_fingerprint"])
    if state == "expires_during_inspection":
        inspect = media.inspect
        def elapsed_review(*args, **kwargs):
            evidence = inspect(*args, **kwargs)
            clock[0] += 2
            return evidence
        monkeypatch.setattr(media, "inspect", elapsed_review)
    assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "media deferred"
    assert calls == (["probe", "source"] if state == "expires_during_inspection" else [])
    held = video_store.candidate(ident)
    assert "preparation_hold" not in held["document"]
    assert held["document"]["original_sha256"] == sha256(original)
    assert video_store.rows("SELECT state,attempts,error FROM jobs WHERE kind='media'") == [
        {"state": "pending", "attempts": 0, "error": ""}]
    clock[0] += 60
    doc = held["document"]
    doc["source_metrics"] = {"views": 101, "observed_at": clock[0], "source_url": doc["canonical_url"]}
    video_store.save_candidate(ident, doc, clock[0], state="held", fingerprint=doc["original_fingerprint"])
    assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "processed"
    result = video_store.candidate(ident)["document"]
    assert calls[-4:] == ["probe", "source", "render", "output"]
    assert Path(result["original_path"]).read_bytes() == original.read_bytes()
    assert result["qc"]["sha256"] == result["output_sha256"]
    assert video_store.rows("SELECT state,error FROM jobs WHERE kind='media'") == [{"state": "done", "error": ""}]
    assert result["novelty"]["state"] == "unchecked"
    assert not video_store.rows("SELECT * FROM reservations")


def test_x_source_over_view_limit_is_terminal_before_costly_processing(video_store, saved_x_media):
    cfg, clock, ident, calls, _ = saved_x_media
    doc = video_store.candidate(ident)["document"]
    doc["source_metrics"]["views"] = 50_001
    video_store.save_candidate(ident, doc, clock[0], state="held", fingerprint=doc["original_fingerprint"])
    assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "processed"
    row = video_store.candidate(ident)
    assert calls == [] and row["state"] == "held" and "50000" in row["reason"]
    assert video_store.rows("SELECT state,error FROM jobs WHERE kind='media'") == [{"state": "done", "error": ""}]


@pytest.mark.parametrize("publication", ["stale", "missing", "future", "text", "boolean", "zero"])
def test_publication_policy_finishes_before_any_media_cost(
        video_store, video_cfg, ready, at, tmp_path, monkeypatch, publication):
    now = at().timestamp()
    cfg = replace(video_cfg, publishing_transport="safari")
    doc = ready()
    if publication == "missing":
        doc.pop("published_at")
    else:
        doc["published_at"] = {"future": now + 1, "stale": now - cfg.max_age_hours * 3600 - 1,
                               "text": "unverified", "boolean": True, "zero": 0}[publication]
    fingerprint = {"sha256": doc["original_sha256"], "visual": [["fixture"]]}
    video_store.save_candidate("clip1", doc, now, state="held", fingerprint=fingerprint)
    video_store.enqueue("media", "clip1", now)
    # A completed policy decision also closes a formerly retrying job.
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET attempts=2,error='prior transient failure' WHERE kind='media'")
    monkeypatch.setattr(media.time, "time", lambda: now)
    assets = tmp_path / "no-preparation-directory"
    monkeypatch.setattr(media, "ASSETS", assets)
    monkeypatch.setattr(workers.video_pressure, "pressure", lambda *a: "")
    monkeypatch.setattr(workers, "_api_work", lambda *a: None)
    for name in ("download", "probe", "fingerprint", "inspect", "render", "technical_qc"):
        monkeypatch.setattr(media, name, lambda *a, **k: pytest.fail("publication hold reached expensive media work"))
    assert workers.run_once("media", video_store, cfg, "fixture", now=now) == "processed"
    row = video_store.candidate("clip1")
    assert row["state"] == ("expired" if publication == "stale" else "held")
    assert row["reason"] == ("freshness expired" if publication == "stale" else "publication time unverified")
    assert row["document"] == doc
    assert json.loads(row["fingerprint"]) == fingerprint
    assert not assets.exists()
    assert video_store.rows("SELECT state,attempts,error FROM jobs WHERE kind='media'") == [
        {"state": "done", "attempts": 0, "error": ""}]
    assert not video_store.rows("SELECT * FROM costs")
    assert not video_store.rows("SELECT * FROM reservations")
    assert not video_store.rows("SELECT * FROM jobs WHERE kind='novelty'")


@pytest.mark.parametrize("publication", ["old", "unknown", "future"])
def test_explicit_selection_exempts_only_known_old_publication_time(
        video_store, saved_x_media, publication):
    cfg, clock, ident, calls, original = saved_x_media
    doc = video_store.candidate(ident)["document"]
    doc["published_at"] = {"old": clock[0] - cfg.max_age_hours * 3600 - 1,
                           "unknown": None, "future": clock[0] + 1}[publication]
    doc["operator_selection"] = {"scope": "one_video", "request_id": "explicit-saved-clip",
        "sha256": doc["original_sha256"], "source_id": doc["source_id"], "canonical_url": doc["canonical_url"],
        "selected_at": clock[0], "expires_at": clock[0] + 86400}
    video_store.save_candidate(ident, doc, clock[0], state="held", fingerprint=doc["original_fingerprint"])
    assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "processed"
    row = video_store.candidate(ident)
    if publication == "old":
        assert calls == ["probe", "source", "render", "output"]
        assert row["document"]["qc"]["sha256"] == row["document"]["output_sha256"]
        assert Path(row["document"]["original_path"]).read_bytes() == original.read_bytes()
        assert row["reason"] == "X novelty unchecked or existing copy found"
        assert video_store.rows("SELECT state FROM jobs WHERE kind='novelty'") == [{"state": "pending"}]
    else:
        assert calls == []
        assert row["state"] == "held" and row["reason"] == "publication time unverified"
        assert not video_store.rows("SELECT * FROM jobs WHERE kind='novelty'")
    assert video_store.rows("SELECT state,attempts,error FROM jobs WHERE kind='media'") == [
        {"state": "done", "attempts": 0, "error": ""}]
    assert not video_store.rows("SELECT * FROM reservations")


def test_publication_gate_shares_final_selection_boundary(video_cfg, ready, at):
    now = at().timestamp()
    doc = ready()
    doc["published_at"] = now - video_cfg.max_age_hours * 3600
    assert ranking.publication_gate(doc, video_cfg, now) == ""
    assert ranking.gate(doc, video_cfg, now, final=True) == ""
    assert ranking.publication_gate(doc, video_cfg, now + .01) == "freshness expired"
    assert ranking.gate(doc, video_cfg, now + .01, final=True) == "publication time unverified or clip stale"


@pytest.mark.parametrize("source", ["local", "remote"])
def test_small_remaining_daily_capacity_defers_and_keeps_partial_bytes_charged(
        video_store, video_cfg, ready, at, tmp_path, monkeypatch, source):
    cfg = replace(video_cfg, max_download_bytes=100, download_budget_bytes=200)
    now = at().timestamp()
    doc = ready()
    assert video_store.budget("prior", "download_bytes", 150, cfg.download_budget_bytes, now)
    if source == "local":
        original = tmp_path / "sized-source.mp4"
        original.write_bytes(b"x" * 75)
        doc["local_file"] = str(original)
    else:
        doc["media_url"] = "https://fixture.example/video.mp4"
        def incomplete(url, *, sink, max_bytes, **kwargs):
            assert max_bytes == 50
            sink.write(b"partial")
            raise AccessError("response exceeds byte budget")
        monkeypatch.setattr(media, "request", incomplete)
    destination = tmp_path / "download.mp4"
    with pytest.raises(Deferred, match="daily download allowance"):
        media.download(doc, destination, cfg, video_store, now)
    assert not destination.exists() and not destination.with_suffix(".partial").exists()
    assert sum(row["amount"] for row in video_store.rows("SELECT amount FROM costs WHERE kind='download_bytes'")) == (
        157 if source == "remote" else 150)


def test_full_per_file_byte_limit_remains_a_failure(video_store, video_cfg, ready, at, tmp_path, monkeypatch):
    cfg = replace(video_cfg, max_download_bytes=100, download_budget_bytes=200)
    doc = ready()
    doc["media_url"] = "https://fixture.example/video.mp4"
    def oversized(*args, **kwargs):
        assert kwargs["max_bytes"] == 100
        raise AccessError("response exceeds byte budget")
    monkeypatch.setattr(media, "request", oversized)
    with pytest.raises(AccessError) as error:
        media.download(doc, tmp_path / "too-large.mp4", cfg, video_store, at().timestamp())
    assert not isinstance(error.value, Deferred)


@pytest.mark.parametrize("platform", ["bilibili", "instagram"])
def test_capture_reaches_unseen_then_least_recent_sources_and_skips_saved_bytes(
        video_store, video_cfg, at, tmp_path, monkeypatch, platform):
    now = at().timestamp()
    cfg = _source_cfg(video_cfg, platform)
    saved = tmp_path / "already-saved.mp4"
    saved.write_bytes(b"already downloaded source")
    identifiers = [f"BV{number:010d}" for number in range(1, 5)] if platform == "bilibili" else [f"source{n}" for n in range(1, 5)]
    _source(video_store, cfg, platform, identifiers[0], now, now - 60,
            original_path=str(saved), original_sha256=sha256(saved))
    _source(video_store, cfg, platform, identifiers[1], now, now - 100)
    _source(video_store, cfg, platform, identifiers[2], now, now - 200, source_capture_attempt=now - 1800)
    _source(video_store, cfg, platform, identifiers[3], now, now - 300, source_capture_attempt=now - 7200)
    opened = []
    monkeypatch.setattr(source_browser.time, "time", lambda: now)
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    def open_url(url):
        opened.append(url.rstrip("/").rsplit("/", 1)[-1])
        return True
    monkeypatch.setattr(safari, "open_url", open_url)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(_player(opened[-1], now)))
    def capture(row, *args):
        opened.append(row["document"]["source_id"])
        row["document"]["source_download"] = {"fixture": "normal player plan"}
    monkeypatch.setattr(native_source, "capture", capture)
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
    assert source_browser.capture_next(video_store, cfg, now + 61) == "source media captured"
    assert opened == [identifiers[1], identifiers[3]]
    assert video_store.rows("SELECT COUNT(*) AS n FROM jobs WHERE kind='media'")[0]["n"] == 2
    assert not video_store.rows("SELECT * FROM reservations")


@pytest.mark.parametrize("matching_identity", [True, False])
def test_known_over_duration_requires_bound_source_and_never_queues_download(
        video_store, video_cfg, at, monkeypatch, matching_identity):
    now = at().timestamp()
    cfg = _source_cfg(video_cfg, "bilibili")
    ident = _source(video_store, cfg, "bilibili", "BV1234567890", now, now - 60)
    payload = _player("BV1234567890" if matching_identity else "BV9876543210", now, cfg.max_duration_seconds + 1)
    monkeypatch.setattr(source_browser.time, "time", lambda: now)
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(payload))
    result = source_browser.capture_next(video_store, cfg, now)
    doc = video_store.candidate(ident)["document"]
    if matching_identity:
        assert result == "source duration held"
        assert doc["source_duration"] == cfg.max_duration_seconds + 1
        assert doc["preparation_hold"]["stage"] == "source_duration"
        monkeypatch.setattr(safari, "open_url", lambda *a: pytest.fail("known over-duration source read again"))
        assert source_browser.capture_next(video_store, cfg, now + 1300) is None
    else:
        assert result == "source player unavailable"
        assert "source_duration" not in doc and "preparation_hold" not in doc
    assert "source_download" not in doc and "original_sha256" not in doc
    assert not video_store.rows("SELECT * FROM jobs WHERE kind='media'")
    assert not video_store.rows("SELECT * FROM costs WHERE kind='download_bytes'")


@pytest.mark.parametrize("matching_identity", [True, False])
def test_queued_media_uses_only_bound_source_duration_before_download(
        video_store, video_cfg, at, tmp_path, monkeypatch, matching_identity):
    now = at().timestamp()
    cfg = _source_cfg(video_cfg, "bilibili")
    source_id = "BV1234567890"
    ident = _source(video_store, cfg, "bilibili", source_id, now, now - 60,
        source_duration=cfg.max_duration_seconds + 1,
        source_duration_evidence={"source_id": source_id if matching_identity else "BV9876543210", "observed_at": now})
    monkeypatch.setattr(media.time, "time", lambda: now)
    monkeypatch.setattr(media, "ASSETS", tmp_path / "managed")
    downloads = []
    def download(*args):
        downloads.append(True)
        raise Deferred("fixture stopped at admitted download")
    monkeypatch.setattr(media, "download", download)
    video_store.enqueue("media", ident, now)
    job = video_store.claim("media", "fixture", now, cfg)
    if matching_identity:
        media.process(video_store, job, now, cfg)
        assert downloads == []
        assert "duration" in video_store.candidate(ident)["reason"]
    else:
        with pytest.raises(Deferred, match="admitted download"):
            media.process(video_store, job, now, cfg)
        assert downloads == [True]
        assert "preparation_hold" not in video_store.candidate(ident)["document"]
    assert not video_store.rows("SELECT * FROM reservations")


@pytest.mark.parametrize("changed,expected", [
    ({}, True),
    ({"fit": 17.99, "entertainment": 20, "quality": 15, "freshness": 10}, False),
    ({"fit": 20, "entertainment": 13.99, "quality": 15, "freshness": 10}, False),
    ({"fit": 20, "entertainment": 20, "quality": 9.99, "freshness": 10}, False),
    ({"freshness": 7.99}, False),
    ({"momentum": 0}, False),
    ({"quality": True}, False),
    ({"quality": float("nan")}, False),
])
def test_unknown_momentum_reserve_preserves_individual_and_overall_floors(video_cfg, changed, expected):
    cfg = replace(video_cfg, allow_unknown_momentum=True, score_threshold=80)
    parts = {"fit": 18, "entertainment": 14, "quality": 10, "freshness": 8, "novelty": 10,
             "momentum": None} | changed
    doc = {"ranking": {"components": parts, "total": 60, "unknown_components": ["momentum"]}}
    assert ranking.unknown_momentum_eligible(doc, cfg) is expected
    assert doc["ranking"]["total"] == 60 and doc["ranking"]["unknown_components"] == ["momentum"]
    assert parts["momentum"] == changed.get("momentum")
    assert not ranking.unknown_momentum_eligible(doc, replace(cfg, allow_unknown_momentum=False))


@pytest.mark.parametrize("gate", ["audio", "novelty", "qc", "permission", "hash"])
def test_entertainment_fourteen_reserve_never_overrides_publication_gates(ready, video_cfg, at, gate):
    cfg = replace(video_cfg, allow_unknown_momentum=True)
    now = at().timestamp()
    doc = deepcopy(ready())
    doc["inspection"].update(fit_score=18, entertainment_score=14, quality_score=10)
    doc["ranking"] = ranking.score(doc, [], [], now, cfg)
    assert doc["ranking"]["components"]["momentum"] is None
    assert doc["ranking"]["total"] < cfg.score_threshold
    assert ranking.gate(doc, cfg, now, final=True) == ""
    if gate == "audio":
        doc["inspection"]["audio_inspected"] = False
    elif gate == "novelty":
        doc["novelty"]["state"] = "unchecked"
    elif gate == "qc":
        doc["qc"]["audio_sync"] = False
    elif gate == "permission":
        cfg = replace(cfg, permissions={})
    else:
        doc["qc"]["sha256"] = "changed-output"
    assert ranking.gate(doc, cfg, now, final=True)

