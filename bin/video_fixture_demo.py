#!/usr/bin/env python3
"""Owned diagnostic media preview, explicitly ineligible as a celebrity candidate.

Exercises permitted feed ingestion, preservation, branding, full decoding and
audio checks without a network, model, bot process or public write.
"""
import argparse
import json
from pathlib import Path
import time

from video_load_check import isolated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    store = isolated(folder / "isolated-state")
    from src.video.config import VideoConfig
    from src.video import connectors, media, schedule
    from src.video.security import sha256
    cfg = VideoConfig(watermark="@Thesimaximalist", local_import_roots=(str(folder),))
    original, output = folder / "diagnostic-original.mp4", folder / "diagnostic-branded.mp4"
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=20", "-f", "lavfi", "-i",
                  "sine=frequency=440:duration=20", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-shortest", str(original)], cfg)
    now, original_hash = time.time(), sha256(original)
    manifest = {"version": 1, "items": [{"source_id": "diagnostic", "creator": "engineering_fixture",
        "canonical_url": "https://www.instagram.com/reel/diagnostic", "local_file": str(original),
        "published_at": now, "publication_evidence": "Generated locally by this diagnostic, NOT an Instagram upload.",
        "title": "Owned test pattern; fixture platform URL is not a real discovery."}]}
    (folder / "fixture-feed.json").write_text(json.dumps(manifest, indent=2))
    connectors.ingest(store, "instagram", manifest["items"], now, cfg)
    info = media.probe(original, cfg)
    media.render(original, output, info, {"safe_crop": [0, 0, 640, 360], "crop_preserves_action": True,
        "overlays_removable_by_crop": True, "watermark_clear_of_action": True, "watermark_position": "bottom"}, cfg)
    qc = media.technical_qc(original, output, info, cfg)
    assert sha256(original) == original_hash
    next_key, next_at = schedule.next_slot(schedule.utc_now(), cfg)
    result = {"fixture_only": True, "real_platform_discovery": False, "real_semantic_inspection": False,
              "state": "held", "eligible": False, "reason": "No target character/performance, creator grant, X novelty check or actual semantic inspector. Not a ready celebrity clip.",
              "original": str(original), "edited_preview": str(output), "original_sha256": original_hash,
              "output_sha256": sha256(output), "technical_qc": qc,
              "caption_preview_only": "BANGER diagnostic 😄\nSynthetic SI test pattern; not a celebrity performance.",
              "score": {"total": None, "reason": "eligibility failed; no fabricated entertainment/identity/momentum score"},
              "next_slot": {"id": next_key, "at": next_at.isoformat()}}
    (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
