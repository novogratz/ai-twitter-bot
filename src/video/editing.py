"""Hash-bound contiguous excerpts selected from actual Codex source inspection."""
import math
import hashlib
import json


def policy_revision(cfg):
    return hashlib.sha256(json.dumps({"version": 1, "targets": cfg.targets, "watermark": cfg.watermark,
        "duration": cfg.source_max_duration_seconds, "cut": [cfg.edit_min_seconds, cfg.edit_max_seconds],
        "hook": cfg.min_hook_score, "bangers": cfg.bangers_only}, sort_keys=True).encode()).hexdigest()


def plan(evidence, info, cfg, digest):
    if not cfg.auto_edit:
        return None
    value = evidence.get("edit")
    if not isinstance(value, dict) or evidence.get("sha256") != digest:
        raise ValueError("missing hash-bound editorial cut")
    start, end = value.get("start_seconds"), value.get("end_seconds")
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in (start, end)):
        raise ValueError("invalid editorial cut timestamps")
    if not (0 <= start < end <= info["duration"] and cfg.edit_min_seconds <= end - start <= cfg.edit_max_seconds):
        raise ValueError("editorial cut outside inspected source or duration bounds")
    # Starts are actual full-sequence sample times. Output opening review still
    # examines subsecond samples of the rendered first second independently.
    fps = evidence.get("coverage", {}).get("fps", cfg.inspection_fps)
    if abs(start * fps - round(start * fps)) > .001:
        raise ValueError("cut start is not an inspected timestamp")
    cast = value.get("cast", [])
    if (not isinstance(cast, list) or not cast or not set(cast) <= set(evidence.get("cast", []))
            or not set(cast) <= set(cfg.targets)):
        raise ValueError("editorial cut lacks attributed visible target cast")
    hook = value.get("hook_score")
    if (type(hook) not in (int, float) or not math.isfinite(hook) or not cfg.min_hook_score <= hook <= 10
            or value.get("cast_visible_first_second") is not True
            or value.get("action_first_second") is not True or not value.get("reason")):
        raise ValueError("editorial cut lacks a strong immediate opening")
    return {**value, "source_sha256": digest, "duration": round(end - start, 6), "revision": 1}


def banger_refusal(review, cfg, *, output=False):
    if not cfg.bangers_only:
        return ""
    for field, minimum, maximum in (("fit_score", 18, 20), ("entertainment_score", 17, 20), ("quality_score", 12, 15)):
        value = review.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            return "performance does not meet banger quality floors"
    if output:
        confidence = review.get("confidence")
        if (type(confidence) not in (int, float) or not math.isfinite(confidence) or confidence < cfg.confidence_min
                or review.get("unsafe") is not False or review.get("synthetic_parody") is not True
                or review.get("full_clip_inspected") is not True or review.get("audio_inspected") is not True
                or review.get("performance") not in ("dance", "singing", "music_parody", "comedy_parody")):
            return "rendered performance verification incomplete"
        opening = review.get("opening", {})
        score = opening.get("hook_score")
        if (type(score) not in (int, float) or not math.isfinite(score) or not cfg.min_hook_score <= score <= 10
                or opening.get("cast_visible_first_second") is not True
                or opening.get("action_first_second") is not True
                or opening.get("no_dead_intro") is not True
                or review.get("opening_samples_reviewed") is not True
                or review.get("opening_sample_times") != [0, .2, .4, .6, .8]):
            return "rendered first second is not a verified banger opening"
        if not set(review.get("cast", [])) & set(cfg.targets):
            return "rendered excerpt has no attributed target performer"
    return ""
