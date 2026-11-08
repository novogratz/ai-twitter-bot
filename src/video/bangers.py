"""Evidence-based editorial judgments, separate from measured popularity."""
import math

WEIGHTS = {"hook_payoff": 25, "performance": 20, "fit": 15, "quality": 15, "novelty": 10,
           "engagement": 10, "freshness": 5}
JUDGMENTS = tuple(key for key in WEIGHTS if key not in ("engagement", "freshness"))


def editorial_total(review):
    """Normalize actual editorial judgments alone; views and age cannot raise it."""
    return round(sum(review["banger_scores"][key] * WEIGHTS[key] for key in JUDGMENTS)
                 * 10 / sum(WEIGHTS[key] for key in JUDGMENTS), 4)


def ultra_refusal(review):
    if reason := review_refusal(review):
        return reason
    if any(review["banger_scores"][key] < 9 for key in JUDGMENTS):
        return "ultra bangers require every editorial component at least 9/10"
    if editorial_total(review) < 95:
        return "ultra bangers require 95/100 editorial quality; reach and freshness cannot compensate"
    return ""


def review_refusal(review):
    scores = review.get("banger_scores", {})
    for key in JUDGMENTS:
        value = scores.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10:
            return "banger rubric evidence incomplete"
        if key != "novelty" and value < 8:
            return "banger hook/performance/fit/quality must each reach 8/10"
    if review.get("brand_fit") is not True:
        return "brand fit or non-hostile parody unverified"
    if review.get("language_dependent") is not False and review.get("language_evidence_verified") is not True:
        return "language-dependent joke lacks verified transcript/translation"
    if not review.get("banger_reason"):
        return "banger rubric lacks an editorial reason"
    return ""


def freshness(published, now):
    if type(published) not in (int, float) or not math.isfinite(published) or not 0 < published <= now:
        return 0
    days = (now - published) / 86400
    return next((score for age, score in ((2, 10), (7, 8), (30, 6), (90, 4), (365, 2)) if days <= age), 1)


def score(doc, now, *, source=False):
    review = doc.get("inspection" if source else "qc", {})
    refusal = review_refusal(review)
    if refusal:
        return {"status": "hold", "total": None, "reason": refusal}
    values = dict(review["banger_scores"])
    momentum = doc.get("ranking", {}).get("components", {}).get("momentum")
    measured = type(momentum) in (int, float) and math.isfinite(momentum) and 0 <= momentum <= 25
    values["engagement"] = momentum * 10 / 25 if measured else 5
    values["freshness"] = freshness(doc.get("published_at"), now)
    points = {key: round(values[key] * weight / 10, 4) for key, weight in WEIGHTS.items()}
    total = round(sum(points.values()), 2)
    return {"status": "exceptional" if total >= 92 else "qualified" if total >= 88 else "reserve" if total >= 82 else "reject",
            "total": total, "editorial_total": editorial_total(review),
            "scores": values, "weighted_points": points, "reason": review["banger_reason"],
            "engagement_basis": "matched observed momentum percentile" if measured else "neutral editorial prior; no comparable observations",
            "engagement_confidence": "observed" if measured else "low",
            "measured_momentum": momentum if measured else None, "scored_at": now,
            "limitations": "editorial judgment, not measured retention or a probability of virality"}


def possible(doc, now, cfg):
    result = score(doc, now, source=True)
    if result["total"] is None:
        return False
    # Feasibility only: allow maximum unobserved engagement, never save it as a score.
    return result["total"] + 10 - result["weighted_points"]["engagement"] >= cfg.banger_min_score
