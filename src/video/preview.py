"""Prepare one Instagram preview without queuing, claiming or publishing a post."""
from pathlib import Path
import json
import tempfile
import time

from . import editing, media, memory, native_source, ranking
from .connectors import canonical, video_id
from .security import AccessError, Deferred, sha256


def prepare(source_url, store, cfg, *, output_root=None):
    """Use normal source/usage/inspection budgets; final publication remains separate."""
    url = canonical("instagram", source_url)
    ident = video_id("instagram", url)
    doc = {"platform": "instagram", "source_id": ident, "canonical_url": url,
           "creator": "", "novelty": {"state": "unchecked"}}
    if reason := memory.refusal(store, doc):
        raise AccessError(reason)
    existing = store.rows("SELECT id,state FROM candidates WHERE platform='instagram' AND source_id=?", (ident,))
    if existing and (existing[0]["state"] in ("posted", "reserved", "duplicate", "rejected")
                     or store.rows("SELECT 1 FROM content_claims WHERE candidate=?", (existing[0]["id"],))):
        raise AccessError("source is already posted, claimed or rejected")
    if not ranking.permission(doc, cfg, time.time()):
        raise AccessError("source usage permission unavailable")
    if output_root is not None:
        output_root = Path(output_root).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="si-instagram-preview-", dir=output_root))
    report = {"source": url, "folder": str(folder), "published": False,
              "queued": False, "publication_ready": False, "status": "held"}
    original, output = folder / "original.mp4", folder / "branded.mp4"
    try:
        now = time.time()
        if not store.budget("instagram", "requests", 1, cfg.request_budget - cfg.publishing_request_reserve, now):
            raise Deferred("source request budget exhausted")
        native_source.capture({"document": doc}, cfg, now)
        if reason := ranking.source_gate(doc, time.time(), cfg):
            raise AccessError(reason)
        media.download(doc, original, cfg, store, time.time())
        original.chmod(0o444)
        doc.update(original_path=str(original), original_sha256=sha256(original))
        report.update(original_path=str(original), original_sha256=doc["original_sha256"],
                      creator=doc["creator"], source_published_at=doc["published_at"])
        info = media.probe(original, cfg, source=cfg.auto_edit)
        doc["probe"] = info
        doc["original_fingerprint"] = media.fingerprint(original, info, cfg)
        if reason := memory.refusal(store, doc):
            raise AccessError(reason)
        if any(media.matches_history(doc, json.loads(row["payload"]))
               for row in store.rows("SELECT payload FROM history")):
            raise AccessError("source matches existing account history")
        doc["inspection"] = media.inspect(original, "source", cfg, store, time.time(),
                                           duration=info["duration"], source_document=doc)
        report["source_review"] = doc["inspection"]
        if cfg.auto_edit:
            doc["edit"] = editing.plan(doc["inspection"], info, cfg, doc["original_sha256"])
        if reason := ranking.gate(doc, cfg, time.time()) or ranking.source_score_gate(doc, cfg, time.time()):
            raise AccessError(reason)
        media.render(original, output, info, doc["inspection"], cfg)
        doc.update(output_path=str(output), output_sha256=sha256(output), brand=cfg.watermark)
        technical = media.technical_qc(original, output, info, cfg, edit=doc.get("edit"))
        review = media.inspect(output, "output", cfg, store, time.time(), original_path=str(original),
                               source_inspection=doc["inspection"], edit=doc.get("edit"),
                               duration=technical["probe"]["duration"])
        doc["qc"] = {**review, **technical}
        if reason := ranking.output_gate(doc, cfg):
            raise AccessError(reason)
        caption = ranking.caption(doc, cfg, time.time())
        (folder / "caption.txt").write_text(caption + "\n")
        report.update(status="prepared", output_path=str(output), caption=caption,
                      output_sha256=doc["output_sha256"], output_review=doc["qc"],
                      remaining_checks=["fresh X exposure/history checks", "final publication admission"])
    except (AccessError, Deferred, ValueError, media.CommandFailure) as exc:
        report["hold_reason"] = str(exc)[:500]
        report["error_type"] = type(exc).__name__
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
