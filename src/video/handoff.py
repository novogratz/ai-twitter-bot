"""Documented discovery adapter into the existing candidate/media queue."""
import json

from . import bangers, memory, ranking


def build(store, row, doc, cfg, now):
    from .media import matches_history
    from .reconcile import history_ready
    history = [json.loads(r["payload"]) for r in store.rows("SELECT payload FROM history")]
    personal = memory.refusal(store, doc)
    if any(matches_history(doc, old) for old in history):
        personal = "already in confirmed account history"
    refusal = personal or ranking.gate(doc, cfg, now, final=True)
    if cfg.one_line_caption and not refusal:
        try:
            ranking.caption(doc, cfg, now)
        except ValueError as exc:
            refusal = str(exc)
    if not history_ready(store, cfg):
        refusal = refusal or "initial account-history fingerprint coverage incomplete"
    review, qc = doc.get("inspection", {}), doc.get("qc", {})
    notes = qc.get("performance_notes", review.get("performance_notes", {}))
    grant = ranking.permission(doc, cfg, now)
    return {
        "version": 1, "candidate_id": row["id"], "content_cluster": doc.get("content_cluster", row["id"]),
        "status": "HOLD" if refusal else "QUALIFIED", "hold_reason": refusal, "checked_at": now,
        "consumer": "existing candidates/jobs tables; media prepares and publisher confirms separately",
        "source": {"canonical_url": doc["canonical_url"], "platform": doc["platform"],
                   "source_id": doc["source_id"], "creator": doc.get("creator"),
                   "original_published_at": doc.get("published_at"), "publication_evidence": doc.get("publication_evidence"),
                   "discovered_at": row.get("discovered"), "original_sha256": doc.get("original_sha256"),
                   "probe": doc.get("probe"), "matching_variants": doc.get("verified_source_variants", []),
                   "quality_note": "probe measures encoded format; native detail and true frame rate are not inferred"},
        "performance": {"cast": review.get("cast", []), "cast_basis": "creator/source attribution, not face identification",
                        "evidence": review.get("evidence", []), "category": review.get("performance"),
                        "song_attribution": notes.get("song_attribution"), "notes": notes,
                        "audio_evidence": review.get("audio_evidence"),
                        "language_dependent": review.get("language_dependent"),
                        "language_evidence_verified": review.get("language_evidence_verified", False)},
        "excerpt": doc.get("edit"), "output_sha256": doc.get("output_sha256"),
        "editorial_score": bangers.score(doc, now), "x_exposure": doc.get("novelty", {}),
        "personal_history": {"result": personal or "no match in inspected personal history",
                             "initial_coverage_ready": history_ready(store, cfg),
                             "archive_complete": store.meta("history_import_complete", False),
                             "seed_coverage": store.meta("personal_memory_coverage"),
                             "fingerprints_available": bool(doc.get("original_fingerprint") and doc.get("output_fingerprint"))},
        "cleanup_notes": notes.get("cleanup_risks"),
        "usage": {"eligible": bool(grant), "evidence": grant.get("evidence") if grant else None,
                  "required_attribution": grant.get("attribution") if grant else None},
        "caption": review.get("caption"), "published": False,
        "uncertainty": "bounded public search and imported history are not proof of worldwide novelty",
    }
