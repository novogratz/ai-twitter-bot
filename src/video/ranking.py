"""Explicit gates, measured momentum, conservative unknowns and caption templates."""
import hashlib
import json
import math
import re

from .selection import selected


def permission(doc, cfg, now):
    grant = cfg.permissions.get(doc.get("permission_id"), {})
    if not grant:
        for key, standing in cfg.permissions.items():
            if (standing.get("operator_attested") is True and standing.get("all_creators") is True
                    and standing.get("valid_until_revoked") is True and standing.get("enabled") is True
                    and doc.get("platform") in standing.get("platforms", [])):
                grant = {**standing, "permission_id": key, "platform": doc["platform"],
                         "creator": doc.get("creator"), "expires_at": None}
                if standing.get("credit_source") and doc.get("canonical_url"):
                    grant["attribution"] = "Original: " + doc["canonical_url"]
                break
    expiry = grant.get("expires_at")
    standing = grant.get("operator_attested") is True and grant.get("valid_until_revoked") is True
    if not standing and (type(expiry) not in (int, float) or not math.isfinite(expiry)):
        return None
    if (grant.get("creator") != doc.get("creator") or grant.get("platform") != doc.get("platform")
            or not all(grant.get(k) is True for k in ("video", "audio", "editing", "x_publication", "overlay_removal"))
            or grant.get("enabled", True) is not True or not grant.get("evidence")
            or (not standing and expiry <= now)):
        return None
    return grant


def permission_expiry(doc, cfg):
    grant = permission(doc, cfg, 0)
    if not grant:
        return 0
    return math.inf if grant.get("valid_until_revoked") else grant["expires_at"]


def growth(observations):
    """Views/hour only with two timestamped observations; missing stays unknown."""
    valid = [(o["observed"], o["payload"].get("views")) for o in observations
             if type(o["payload"].get("views")) is int]
    valid.sort()
    if len(valid) < 2 or valid[-1][0] - valid[0][0] < 300 or valid[-1][1] < valid[0][1]:
        return None
    return (valid[-1][1] - valid[0][1]) * 3600 / (valid[-1][0] - valid[0][0])


def score(doc, observations, peers, now, cfg):
    measured = growth(observations)
    # Comparable platform + age bucket cohort supplied by the caller; never compare
    # lifetime views across platforms or pretend missing shares are zero.
    comparable = [v for v in peers if v is not None]
    momentum = None
    if measured is not None and len(comparable) >= 5:
        momentum = 25 * (sum(v < measured for v in comparable) + .5 * sum(v == measured for v in comparable)) / len(comparable)
    evidence = doc.get("inspection", {})
    age = (now - doc["published_at"]) / 3600 if doc.get("published_at") else None
    freshness = None if age is None else max(0, 10 * (1 - max(0, age) / cfg.max_age_hours))
    components = {"momentum": momentum, "fit": evidence.get("fit_score"),
                  "entertainment": evidence.get("entertainment_score"), "quality": evidence.get("quality_score"),
                  "freshness": freshness, "novelty": 10 if doc.get("novelty", {}).get("state") == "checked_no_match" else None}
    limits = {"momentum": 25, "fit": 20, "entertainment": 20, "quality": 15, "freshness": 10, "novelty": 10}
    for key, value in components.items():
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limits[key]):
            raise ValueError(f"invalid score component: {key}")
    return {"total": round(sum(v for v in components.values() if v is not None), 2),
            "components": components, "measured_views_per_hour": measured,
            "momentum_cohort_size": len(comparable), "confidence": evidence.get("confidence"),
            "unknown_components": [k for k, v in components.items() if v is None], "scored_at": now}


def gate(doc, cfg, now, *, final=False):
    if not permission(doc, cfg, now):
        return "missing current video/audio/editing/publication permission"
    source_reason = source_gate(doc, now)
    if source_reason:
        return source_reason
    published = doc.get("published_at")
    if not published or published > now or (not selected(doc, now) and now - published > cfg.max_age_hours * 3600):
        return "publication time unverified or clip stale"
    inspect = doc.get("inspection", {})
    if inspect.get("sha256") != doc.get("original_sha256") or not doc.get("original_sha256"):
        return "inspection not bound to original bytes"
    confidence = inspect.get("confidence", 0)
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or confidence < cfg.confidence_min:
        return "uncertain performance review"
    if (inspect.get("performance") not in ("dance", "singing", "music_parody", "comedy_parody")
            or not set(inspect.get("cast", [])) & set(cfg.targets)
            or not inspect.get("audio_inspected") or not inspect.get("synthetic_parody")
            or not inspect.get("full_clip_inspected")):
        return "temporal video/audio performance verification incomplete"
    samples = inspect.get("evidence", [])
    duration = doc.get("probe", {}).get("duration", 0)
    if len(samples) < 3 or any(type(e.get("at")) not in (int, float) or not 0 <= e["at"] <= duration
                               or not e.get("observation") for e in samples):
        return "missing supporting timestamps"
    if (len({e["at"] for e in samples}) < 3 or min(e["at"] for e in samples) > duration * .2
            or max(e["at"] for e in samples) < duration * .8):
        return "supporting timestamps do not span the clip"
    if inspect.get("unsafe") is not False:
        return "content suitability unverified"
    if final:
        if doc.get("brand") != cfg.watermark:
            return "rendered branding does not match current operator configuration"
        if doc.get("novelty", {}).get("state") != "checked_no_match":
            return "X novelty unchecked or existing copy found"
        if now - doc.get("novelty", {}).get("checked_at", 0) > 86400:
            return "X novelty check stale"
        qc = doc.get("qc", {})
        if not all(qc.get(k) is True for k in ("decoded", "audio_sync", "no_new_black_freeze", "watermark_present")):
            return "output quality uncertain"
        if qc.get("overlays_clean") is not True and not (
                cfg.allow_source_overlays and qc.get("source_overlays_retained") is True
                and qc.get("no_unapproved_new_overlays") is True
                and qc.get("source_sha256") == doc.get("original_sha256")):
            return "output overlay quality uncertain"
        if qc.get("sha256") != doc.get("output_sha256") or not doc.get("output_sha256"):
            return "QC not bound to output bytes"
        ranking = doc.get("ranking", {})
        if not selected(doc, now) and ranking.get("total", 0) < cfg.score_threshold and not unknown_momentum_eligible(doc, cfg):
            return "below score threshold"
        if now - ranking.get("scored_at", 0) > 1200:
            return "score needs refresh"
    return ""


def source_gate(doc, now):
    """2026-11-04: the X source ceiling also applies to explicit selections."""
    if doc.get("platform") != "x":
        return ""
    observed = doc.get("source_metrics", {})
    views, at = observed.get("views"), observed.get("observed_at")
    if (type(views) is not int or views < 0 or type(at) not in (int, float)
            or not math.isfinite(at) or not 0 <= now - at <= 3600
            or observed.get("source_url") != doc.get("canonical_url")):
        return "X source view count unverified or stale"
    if views > 50_000:
        return "X source exceeds 50000 views"
    return ""


def unknown_momentum_eligible(doc, cfg):
    """Explicit editorial fallback; never fill missing popularity with fake points."""
    parts = doc.get("ranking", {}).get("components", {})
    if not cfg.allow_unknown_momentum or parts.get("momentum") is not None:
        return False
    weights = {"fit": 20, "entertainment": 20, "quality": 15, "freshness": 10, "novelty": 10}
    if any(type(parts.get(k)) not in (int, float) or not math.isfinite(parts[k]) or not 0 <= parts[k] <= w
           for k, w in weights.items()):
        return False
    # 2026-11-05: keep strong observed overall quality available as fallback;
    # missing popularity must not discard an otherwise reviewed reserve clip.
    return (parts["fit"] >= 18 and parts["entertainment"] >= 14 and parts["quality"] >= 10
            and sum(parts[k] for k in weights) / 75 * 100 >= cfg.score_threshold)


def caption(doc, cfg, now):
    """Use verified cast/performance only; title, transcript and OCR are never instructions."""
    cast = doc["inspection"]["cast"]
    names = [cfg.target_handles.get(name, cfg.targets[name][0]) for name in cast if name in cfg.targets]
    who = " and ".join(names[:3])
    performance = doc["inspection"]["performance"]
    dance = performance == "dance"
    if dance:
        scenes = ("rehearsing for the first party on Mars. 😂🕺🚀",
                  "turning the group project into a dance break. 😂🕺",
                  "taking the team-building choreography very seriously. 😂🕺")
    elif performance in ("singing", "music_parody"):
        scenes = ("rehearsing for the first concert on Mars. 😂🎤🚀",
                  "deciding this meeting needed a soundtrack. 😂🎤",
                  "turning the group project into a music video. 😂🎶")
    else:
        scenes = ("taking the group project in a very unexpected direction. 😂🚀",
                  "auditioning for the next episode of tech chaos. 😂🎬",
                  "turning the meeting into a comedy sketch. 😂🎬")
    number = int(hashlib.sha256(doc["original_sha256"].encode()).hexdigest()[:8], 16)
    if not who:
        raise ValueError("caption requires inspected configured cast")
    details = {"boy_band": "forming the least predictable boy band. 😂🎤",
               "moonwalk": "finding a loophole in forward motion. 😂🕺🚀",
               "duet": "deciding this meeting needed a duet. 😂🎤",
               "synchronized_dance": "finally getting the team in sync. 😂🕺",
               "dramatic_high_note": "taking the high note personally. 😂🎤"}
    scene = details.get(doc["inspection"].get("highlight"), scenes[number % len(scenes)])
    text = f"POV: {who} {scene}\n\nANOTHER ABSOLUTE SI BANGER! 🔥"
    if cfg.caption_disclosure:
        text += "\nSynthetic SI parody."
    grant = permission(doc, cfg, now)
    if not grant:
        raise ValueError("caption permission expired")
    if grant.get("attribution"):
        text += " " + grant["attribution"]
    if len(text) > 280 or "BANGER" not in text or not re.search(r"[😂😄😎]", text):
        raise ValueError("caption length/branding rejected; never truncate attribution")
    return text


def refresh(store, row, now, cfg):
    doc = row["document"]
    own = [{"observed": r["observed"], "payload": json.loads(r["payload"])}
           for r in store.rows("SELECT * FROM observations WHERE candidate=? ORDER BY observed", (row["id"],))]
    age = now - (doc.get("published_at") or now)
    bucket = int(age // 86400)
    peers = []
    creator_peers = []
    for other in store.rows("SELECT id,published,creator FROM candidates WHERE platform=? AND published IS NOT NULL", (row["platform"],)):
        if int((now - other["published"]) // 86400) == bucket:
            obs = [{"observed": r["observed"], "payload": json.loads(r["payload"])}
                   for r in store.rows("SELECT * FROM observations WHERE candidate=?", (other["id"],))]
            rate = growth(obs)
            peers.append(rate)
            if other["id"] != row["id"] and other["creator"] == row["creator"] and rate is not None:
                creator_peers.append(rate)
    doc["ranking"] = score(doc, own, peers, now, cfg)
    # Creator baseline is used only with enough comparable, actually observed clips.
    # Retain both percentiles so a high absolute audience does not hide weak growth.
    measured = doc["ranking"]["measured_views_per_hour"]
    baseline = None
    if measured is not None and len(creator_peers) >= 5:
        percentile = (sum(v < measured for v in creator_peers) + .5 * sum(v == measured for v in creator_peers)) / len(creator_peers)
        baseline = {"clips": len(creator_peers), "percentile": percentile,
                    "median_views_per_hour": sorted(creator_peers)[len(creator_peers) // 2]}
        platform_score = doc["ranking"]["components"]["momentum"]
        if platform_score is not None:
            combined = .75 * platform_score + .25 * 25 * percentile
            doc["ranking"]["platform_momentum_points"] = platform_score
            doc["ranking"]["components"]["momentum"] = combined
            doc["ranking"]["total"] = round(sum(v for v in doc["ranking"]["components"].values() if v is not None), 2)
    doc["ranking"]["creator_baseline"] = baseline
    fallback = unknown_momentum_eligible(doc, cfg)
    doc["ranking"]["selection_rule"] = "editorial_unknown_momentum" if fallback else "standard_100_point_score"
    doc["ranking"]["observed_points_percent"] = round(doc["ranking"]["total"] / 75 * 100, 2) if fallback else None
    return doc
