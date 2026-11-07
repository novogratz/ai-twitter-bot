"""Provisional coverage from existing eligible clips; never invent future supply."""
import json

from . import ranking, schedule
from .media import fingerprint_match, matches_history


def same_content(left, right):
    lrow, ldoc = left
    rrow, rdoc = right
    if ldoc.get("original_sha256") and ldoc["original_sha256"] == rdoc.get("original_sha256"):
        return True
    return bool(lrow["fingerprint"] and rrow["fingerprint"] and
                fingerprint_match(lrow["fingerprint"], rrow["fingerprint"]))


def distinct(candidates):
    result = []
    for candidate in candidates:
        if not any(same_content(candidate, prior) for prior in result):
            result.append(candidate)
    return result


def usable_until(doc, cfg):
    grant_expiry = ranking.permission_expiry(doc, cfg)
    expiry = min(doc["published_at"] + cfg.max_age_hours * 3600, grant_expiry)
    choice = doc.get("operator_selection", {})
    if ranking.selected(doc, choice.get("selected_at", 0)):
        return min(choice["expires_at"], grant_expiry)
    if cfg.bangers_only:
        from .bangers import score
        # Stepwise original-age points can change before a future window.
        for days in (2, 7, 30, 90, 365):
            boundary = doc["published_at"] + days * 86400 + .01
            if boundary > doc.get("ranking", {}).get("scored_at", 0):
                graded = score(doc, boundary)
                if graded["total"] is None or graded["total"] < cfg.banger_min_score:
                    expiry = min(expiry, boundary)
                    break
        return expiry
    # Other score components can change at refresh. Account for known freshness
    # decay now; do not assume new observations will improve a marginal score.
    score = doc.get("ranking", {})
    freshness = score.get("components", {}).get("freshness")
    if freshness is not None:
        threshold = cfg.score_threshold * .75 if ranking.unknown_momentum_eligible(doc, cfg) else cfg.score_threshold
        required = threshold - (score["total"] - freshness)
        if required > 0:
            expiry = min(expiry, doc["published_at"] + cfg.max_age_hours * 3600 * (1 - required / 10))
    return expiry


def coverage(candidates, now, cfg):
    """Earliest-expiry allocation, after current gates and content deduplication."""
    remaining = sorted(candidates, key=lambda pair: (usable_until(pair[1], cfg), pair[0]["id"]))
    windows = []
    for key, at in schedule.upcoming_primary(now, cfg):
        # Leave the whole upload grace available without losing source freshness
        # or permission. Final score, novelty and file checks still run when due.
        selected = next((pair for pair in remaining if usable_until(pair[1], cfg) > at.timestamp() + cfg.grace_seconds), None)
        windows.append({"id": key, "at": at.isoformat(), "candidate": selected[0]["id"] if selected else None})
        if selected:
            remaining.remove(selected)
    covered = sum(item["candidate"] is not None for item in windows)
    return {"checked_at": now.isoformat(), "protection_enabled": cfg.protect_primary_windows,
            "eligible_distinct": len(candidates), "covered": covered, "shortfall": len(windows) - covered,
            "windows": windows, "provisional": True}


def surplus(candidates, now, cfg):
    """Allow spending only a clip whose removal keeps all main windows supplied."""
    if len(candidates) <= len(cfg.windows):
        return []
    return [pair for pair in candidates
            if coverage([other for other in candidates if other[0]["id"] != pair[0]["id"]], now, cfg)["shortfall"] == 0]


def report(store, cfg, now):
    from . import memory
    candidates = []
    for row in store.rows("SELECT * FROM candidates WHERE state='ready' AND id NOT IN "
                          "(SELECT candidate FROM content_claims) ORDER BY score DESC,discovered LIMIT 80"):
        doc = json.loads(row["document"])
        if not ranking.gate(doc, cfg, now.timestamp(), final=True) and not memory.refusal(store, doc):
            candidates.append((row, doc))
    claimed = [(row, json.loads(row["document"])) for row in store.rows(
        "SELECT c.* FROM candidates c JOIN content_claims p ON c.id=p.candidate")]
    history = [json.loads(row["payload"]) for row in store.rows("SELECT payload FROM history")]
    candidates = [pair for pair in candidates if not any(same_content(pair, prior) for prior in claimed)
                  and not any(matches_history(pair[1], prior) for prior in history)]
    return coverage(distinct(candidates), now, cfg)
