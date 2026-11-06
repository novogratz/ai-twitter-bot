"""Actual source scores can rule out render cost without awarding future points."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.video import media, preparation, ranking, workers
from src.video.security import sha256


def _choice(doc, now):
    return {"scope": "one_video", "request_id": "fixture-operator-choice",
            "sha256": doc["original_sha256"], "source_id": doc["source_id"],
            "canonical_url": doc["canonical_url"], "selected_at": now, "expires_at": now + 86400}


@pytest.mark.parametrize("scores,allowed", [
    ((15, 10, 9), False),  # actual refusal: even 25 + 10 + 10 more points reaches only 79
    ((15, 10, 10), True),  # the standard score can reach exactly 80
    ((15, 10, 9.999), True),  # final standard totals round to two decimals
    ((18, 8, 10), True),  # fallback fails, but future observed momentum could qualify
    ((18, 14, 10), True),  # the existing editorial fallback remains possible
    ((None, None, None), True),  # missing source scores are not zero
    ((15, 10, None), True),
    ((0, 0, None), False),  # known scores alone prove the upper bound too low
])
def test_source_bound_is_generous_pure_and_uses_standard_rounding(video_cfg, at, scores, allowed):
    cfg = replace(video_cfg, allow_unknown_momentum=True)
    doc = {"inspection": dict(zip(("fit_score", "entertainment_score", "quality_score"), scores)),
           "ranking": {"components": {"momentum": None}, "total": 0}, "novelty": {"state": "unchecked"}}
    before = deepcopy(doc)
    assert (ranking.source_score_gate(doc, cfg, at().timestamp()) == "") is allowed
    assert doc == before


@pytest.mark.parametrize("field,invalid", [
    ("fit_score", True), ("fit_score", -1), ("fit_score", 20.001),
    ("entertainment_score", float("nan")), ("entertainment_score", float("inf")),
    ("entertainment_score", "10"), ("quality_score", 15.001), ("quality_score", []),
])
def test_source_bound_shares_finite_bounded_score_validation(video_cfg, at, field, invalid):
    doc = {"inspection": {"fit_score": 20, "entertainment_score": 20, "quality_score": 15},
           "published_at": at().timestamp()}
    doc["inspection"][field] = invalid
    with pytest.raises(ValueError, match="invalid score component"):
        ranking.source_score_gate(doc, video_cfg, at().timestamp())
    with pytest.raises(ValueError, match="invalid score component"):
        ranking.score(doc, [], [], at().timestamp(), video_cfg)


@pytest.mark.parametrize("selection,allowed", [("active", True), ("expired", False), ("wrong_hash", False)])
def test_source_score_refusal_preserves_only_current_hash_bound_selection(video_cfg, ready, at, selection, allowed):
    now = at().timestamp()
    doc = ready()
    doc["inspection"].update(fit_score=15, entertainment_score=10, quality_score=9)
    doc["operator_selection"] = _choice(doc, now)
    if selection == "expired":
        doc["operator_selection"].update(selected_at=now - 86400, expires_at=now)
    elif selection == "wrong_hash":
        doc["operator_selection"]["sha256"] = "different bytes"
    assert (ranking.source_score_gate(doc, video_cfg, now) == "") is allowed


@pytest.mark.parametrize("case", ["impossible", "boundary", "future_momentum", "fallback", "selected"])
def test_media_stops_impossible_source_before_render_qc_and_output_review(
        video_store, video_cfg, ready, at, tmp_path, monkeypatch, case):
    clock = [at().timestamp()]
    cfg = replace(video_cfg, publishing_transport="safari", allow_unknown_momentum=True)
    doc = ready()
    original = Path(doc["original_path"])
    source_bytes = original.read_bytes()
    scores = {"impossible": (15, 10, 9), "boundary": (15, 10, 10), "future_momentum": (18, 8, 10),
              "fallback": (18, 14, 10), "selected": (15, 10, 9)}[case]
    review = doc["inspection"] | dict(zip(("fit_score", "entertainment_score", "quality_score"), scores))
    info = doc["probe"]
    for key in ("inspection", "ranking", "output_path", "output_sha256", "brand", "qc"):
        doc.pop(key, None)
    doc.update(local_file=str(original), novelty={"state": "unchecked"})
    if case == "selected":
        doc["operator_selection"] = _choice(doc, clock[0])
    video_store.save_candidate("clip1", doc, clock[0], state="held")
    video_store.enqueue("media", "clip1", clock[0])
    monkeypatch.setattr(media.time, "time", lambda: clock[0])
    monkeypatch.setattr(media, "ASSETS", tmp_path / "managed")
    monkeypatch.setattr(workers.video_pressure, "pressure", lambda *a: "")
    monkeypatch.setattr(workers, "_api_work", lambda *a: None)
    monkeypatch.setattr(media, "probe", lambda *a: info)
    monkeypatch.setattr(media, "fingerprint", lambda path, *a: {"sha256": sha256(path), "visual": [["fixture"]]})
    calls = []
    def inspect(path, stage, *args, **kwargs):
        calls.append(stage)
        if stage == "source":
            assert sha256(path) == review["sha256"]
            return deepcopy(review)
        return {"sha256": sha256(path), "watermark_present": True, "overlays_clean": True}
    def render(source, output, *args):
        calls.append("render")
        output.write_bytes(b"separate rendered fixture")
    def qc(*args):
        calls.append("technical_qc")
        return {"probe": info, "decoded": True, "audio_sync": True, "no_new_black_freeze": True}
    monkeypatch.setattr(media, "inspect", inspect)
    monkeypatch.setattr(media, "render", render)
    monkeypatch.setattr(media, "technical_qc", qc)

    assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "processed"
    row = video_store.candidate("clip1")
    result = row["document"]
    assert result["inspection"] == review
    assert Path(result["original_path"]).read_bytes() == source_bytes
    assert result["original_sha256"] == sha256(original)
    assert json.loads(row["fingerprint"]) == result["original_fingerprint"]
    assert video_store.rows("SELECT state,attempts,error FROM jobs WHERE kind='media'") == [
        {"state": "done", "attempts": 0, "error": ""}]
    assert not video_store.rows("SELECT * FROM reservations")

    if case == "impossible":
        assert calls == ["source"]
        assert row["state"] == "held" and row["score"] is None
        assert row["reason"] == "source review scores cannot reach publication threshold"
        assert result["preparation_hold"] == {"stage": "source_score", "reason": row["reason"],
                                               "sha256": result["original_sha256"], "at": clock[0]}
        assert not {"output_path", "qc", "ranking"} & result.keys()
        assert not video_store.rows("SELECT * FROM jobs WHERE kind='novelty'")
        for _ in range(cfg.max_attempts + 1):
            clock[0] += 7200
            with video_store.transaction() as db:
                preparation.recover_supply(db, cfg, clock[0])
            assert workers.run_once("media", video_store, cfg, "fixture", now=clock[0]) == "idle"
        assert calls == ["source"]
    else:
        assert calls == ["source", "render", "technical_qc", "output"]
        assert "preparation_hold" not in result
        # Passing cost admission awards no momentum or novelty and grants no publication.
        assert result["ranking"]["components"]["momentum"] is None
        assert result["ranking"]["components"]["novelty"] is None
        assert result["novelty"]["state"] == "unchecked" and row["state"] == "held"
        assert video_store.rows("SELECT state FROM jobs WHERE kind='novelty'") == [{"state": "pending"}]
        if case == "fallback":
            projected = deepcopy(result)
            projected["ranking"]["components"]["novelty"] = 10
            assert ranking.unknown_momentum_eligible(projected, cfg)
