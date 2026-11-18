"""Hash-bound contiguous excerpts selected from actual Codex source inspection."""
import math
import hashlib
import json


def policy_revision(cfg):
    from .captions import POLICY
    return hashlib.sha256(json.dumps({"version": 2, "targets": cfg.targets, "watermark": cfg.watermark,
        "duration": cfg.source_max_duration_seconds, "cut": [cfg.edit_min_seconds, cfg.edit_max_seconds],
        "hook": cfg.min_hook_score, "bangers": cfg.bangers_only, "rubric_min": cfg.banger_min_score,
        "caption": cfg.one_line_caption, "playful_caption": cfg.playful_caption,
        "meme_caption_policy": POLICY if cfg.meme_caption else None,
        "ultra_bangers": cfg.ultra_bangers_only,
        "best_available_fallback": cfg.best_available_fallback}, sort_keys=True).encode()).hexdigest()


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
    minimum = 0 if cfg.best_available_fallback else cfg.min_hook_score
    opening = (value.get("cast_visible_first_second"), value.get("action_first_second"))
    if (type(hook) not in (int, float) or not math.isfinite(hook) or not minimum <= hook <= 10
            or any(type(flag) is not bool for flag in opening)
            or (not cfg.best_available_fallback and not all(opening)) or not value.get("reason")):
        raise ValueError("editorial cut lacks a strong immediate opening")
    return {**value, "source_sha256": digest, "duration": round(end - start, 6), "revision": 1}


def banger_refusal(review, cfg, *, output=False):
    if not cfg.bangers_only:
        return ""
    from .bangers import review_refusal
    if reason := review_refusal(review, best_available=cfg.best_available_fallback):
        return reason
    if cfg.ultra_bangers_only and not cfg.best_available_fallback:
        from .bangers import ultra_refusal
        if reason := ultra_refusal(review):
            return reason
    floors = (19, 19, 14) if cfg.ultra_bangers_only else (18, 17, 12)
    if cfg.best_available_fallback:
        floors = (0, 0, 0)
    for field, minimum, maximum in zip(("fit_score", "entertainment_score", "quality_score"), floors, (20, 20, 15)):
        value = review.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            return "performance does not meet banger quality floors"
    if output:
        confidence = review.get("confidence")
        if (type(confidence) not in (int, float) or not math.isfinite(confidence) or confidence < cfg.confidence_min
                or review.get("unsafe") is not False or review.get("synthetic_parody") is not True
                or review.get("full_clip_inspected") is not True or review.get("audio_inspected") is not True
                or review.get("performance") not in ("dance", "singing", "music_parody", "comedy_parody", "cinematic_parody")):
            return "rendered performance verification incomplete"
        opening = review.get("opening", {})
        score = opening.get("hook_score")
        minimum = 0 if cfg.best_available_fallback else cfg.min_hook_score
        observed = tuple(opening.get(key) for key in ("cast_visible_first_second", "action_first_second", "no_dead_intro"))
        if (type(score) not in (int, float) or not math.isfinite(score) or not minimum <= score <= 10
                or any(type(flag) is not bool for flag in observed)
                or (not cfg.best_available_fallback and not all(observed))
                or review.get("opening_samples_reviewed") is not True
                or review.get("opening_sample_times") != [0, .2, .4, .6, .8]):
            return "rendered first second is not a verified banger opening"
        if not set(review.get("cast", [])) & set(cfg.targets):
            return "rendered excerpt has no attributed target performer"
    return ""
