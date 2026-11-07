from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from src.video import editing, inspection, media, preparation, ranking
from src.video.security import sha256


def cut_review(digest, start=6, end=18):
    return {"sha256": digest, "cast": ["performer"], "coverage": {"fps": 1},
            "safe_crop": [0, 0, 320, 180], "crop_preserves_action": True,
            "overlays_removable_by_crop": True, "watermark_position": "bottom", "watermark_clear_of_action": True,
            "edit": {"start_seconds": start, "end_seconds": end, "cast": ["performer"], "hook_score": 9,
                     "cast_visible_first_second": True, "action_first_second": True,
                     "reason": "The performance begins immediately and ends on a complete phrase."}}


@pytest.mark.parametrize("change", [
    {"start_seconds": -1}, {"end_seconds": 25}, {"start_seconds": float("nan")},
    {"start_seconds": True}, {"start_seconds": 6.3}, {"end_seconds": 7},
    {"cast": []}, {"cast": ["unapproved"]}, {"hook_score": 7},
    {"cast_visible_first_second": False}, {"action_first_second": False},
])
def test_cut_never_invents_timestamps_cast_or_hook(video_cfg, change):
    cfg = replace(video_cfg, auto_edit=True)
    review = cut_review("a" * 64)
    review["edit"].update(change)
    with pytest.raises(ValueError):
        editing.plan(review, {"duration": 24}, cfg, "a" * 64)


def test_cut_is_bound_to_source_hash_and_inspected_bounds(video_cfg):
    cfg = replace(video_cfg, auto_edit=True)
    review = cut_review("a" * 64)
    plan = editing.plan(review, {"duration": 24}, cfg, "a" * 64)
    assert plan["duration"] == 12 and plan["source_sha256"] == "a" * 64
    with pytest.raises(ValueError, match="hash-bound"):
        editing.plan(review, {"duration": 24}, cfg, "b" * 64)


@pytest.mark.parametrize("field,value", [("cast", []), ("audio_inspected", False),
    ("confidence", .2), ("unsafe", True), ("synthetic_parody", False), ("opening_samples_reviewed", False)])
def test_banger_output_needs_actual_performance_and_first_second(ready, video_cfg, field, value):
    cfg = replace(video_cfg, bangers_only=True)
    review = ready()["inspection"] | {"opening": {"hook_score": 9, "cast_visible_first_second": True,
        "action_first_second": True, "no_dead_intro": True}, "opening_samples_reviewed": True,
        "opening_sample_times": [0, .2, .4, .6, .8]}
    assert editing.banger_refusal(review, cfg, output=True) == ""
    review[field] = value
    assert editing.banger_refusal(review, cfg, output=True)


def test_caption_is_one_reviewed_line_and_requires_target(ready, video_cfg, at):
    cfg = replace(video_cfg, one_line_caption=True, caption_disclosure=False)
    doc = ready()
    doc["inspection"]["caption"] = "Example Star turned the meeting into a dance break. 😂"
    doc["qc"]["caption_accurate"] = True
    text = ranking.caption(doc, cfg, at().timestamp())
    assert "\n" not in text and len(text) <= 180
    for invalid in (text + "\nAgain", "The mystery guest turned the meeting into a dance break.", None):
        doc["inspection"]["caption"] = invalid
        with pytest.raises(ValueError):
            ranking.caption(doc, cfg, at().timestamp())
    doc["inspection"]["caption"] = text
    doc["qc"]["caption_accurate"] = False
    with pytest.raises(ValueError):
        ranking.caption(doc, cfg, at().timestamp())


def test_retained_overlay_ocr_uses_source_cut_offset(video_cfg):
    cfg = replace(video_cfg, allow_source_overlays=True)
    text = {"text": "Creator credit", "box": [.1, .1, .3, .04], "confidence": .99}
    mark = {"text": cfg.watermark, "confidence": .99}
    source = {"sha256": "original", "coverage": {"fps": 1}, "ocr_evidence": [{"at": 6, "texts": [text]}]}
    output = {"sha256": "output", "confidence": .99, "coverage": {"fps": 1},
              "ocr_evidence": [{"at": 0, "texts": [text, mark]}], "edit": {"start_seconds": 6},
              "watermark_present": True, "no_destructive_edit": True, "audio_inspected": True,
              "source_overlays_retained": True, "no_unapproved_new_overlays": True}
    result = inspection.output_ocr(deepcopy(output), source, cfg, True)
    assert result["no_unapproved_new_overlays"] and not result["unexpected_output_text"]
    output["edit"]["start_seconds"] = 3
    assert not inspection.output_ocr(output, source, cfg, True)["no_unapproved_new_overlays"]


@pytest.mark.parametrize("failure", ["opening", "caption"])
def test_completed_output_refusal_keeps_evidence_without_requeueing_novelty(
        video_store, video_cfg, ready, at, failure):
    cfg = replace(video_cfg, bangers_only=True, one_line_caption=True)
    now = at().timestamp()
    doc = ready()
    doc["inspection"]["caption"] = "Example Star turned the meeting into a dance break. 😂"
    doc["qc"].update(doc["inspection"], caption_accurate=True,
                     opening={"hook_score": 9, "cast_visible_first_second": True,
                              "action_first_second": True, "no_dead_intro": True},
                     opening_samples_reviewed=True, opening_sample_times=[0, .2, .4, .6, .8])
    if failure == "opening":
        doc["qc"]["opening"]["hook_score"] = 5
    else:
        doc["inspection"]["caption"] = "A nameless guest turned the meeting into a dance break."
    video_store.enqueue("media", "clip1", now)
    job = video_store.claim("media", "test", now, cfg)
    original_fp = {"sha256": doc["original_sha256"], "visual": []}
    media.finish_output_review(video_store, video_store.candidate("clip1"), doc, now, cfg, job, original_fp)
    assert video_store.finish(job, now)
    saved = video_store.candidate("clip1")
    assert saved["state"] == "held" and saved["document"]["qc"] == doc["qc"]
    assert saved["document"]["preparation_hold"]["stage"] == "output_review"
    assert saved["document"]["original_sha256"] == doc["original_sha256"]
    assert not video_store.rows("SELECT * FROM jobs WHERE kind='novelty'")
    assert video_store.rows("SELECT state,attempts FROM jobs") == [{"state": "done", "attempts": 0}]


def test_editing_policy_reopens_completed_held_source_once_preserving_original_and_review(
        video_store, video_cfg, ready, at):
    cfg = replace(video_cfg, auto_edit=True)
    now = at().timestamp()
    doc = ready()
    video_store.save_candidate("clip1", doc, now, state="held", reason="unsupported duration")
    video_store.enqueue("media", "clip1", now)
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET state='done' WHERE item='clip1'")
        preparation.recover_supply(db, cfg, now)
    saved = video_store.candidate("clip1")
    assert saved["document"]["original_sha256"] == doc["original_sha256"]
    assert saved["document"]["inspection"] == doc["inspection"]
    assert saved["document"]["editing_policy_revision"] == editing.policy_revision(cfg)
    assert video_store.rows("SELECT state FROM jobs") == [{"state": "pending"}]
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET state='done' WHERE item='clip1'")
        preparation.recover_supply(db, cfg, now + 7200)
    assert video_store.rows("SELECT state FROM jobs") == [{"state": "done"}]
    assert not video_store.rows("SELECT * FROM reservations")


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg")
def test_real_cut_preserves_original_and_aligned_audio(video_cfg, tmp_path):
    pytest.importorskip("numpy")
    fonts = ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = next((path for path in fonts if Path(path).exists()), None)
    if not font:
        pytest.skip("requires a TrueType font")
    cfg = replace(video_cfg, auto_edit=True, font_file=font)
    original, output = tmp_path / "original.mp4", tmp_path / "edited.mp4"
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24", "-f", "lavfi", "-i",
                  "aevalsrc=sin(2*PI*(220*t+15*t*t)):s=48000", "-t", "24", "-c:v", "libx264",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", str(original)], cfg)
    digest = sha256(original)
    info = media.probe(original, cfg, source=True)
    review = cut_review(digest)
    edit = media.render(original, output, info, review, cfg)
    result = media.technical_qc(original, output, info, cfg, edit=edit)
    assert sha256(original) == digest
    assert abs(result["probe"]["duration"] - 12) < .15
    assert result["audio_sync"] and result["audio_correlation"] >= .95
    with pytest.raises(ValueError):
        media.technical_qc(original, output, info, cfg, edit=edit | {"start_seconds": 3})
    sheet, times = inspection.opening_pack(output, tmp_path, cfg)
    assert sheet.is_file() and times == [0, .2, .4, .6, .8]
