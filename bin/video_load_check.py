#!/usr/bin/env python3
"""Isolated concurrent-load experiment: real Reply pipeline/FFmpeg, fixture I/O.

Never uses production state, model quotas, Safari or an external platform.
This measures contention under the stated workload, not live X/model latency.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import logging
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def isolated(root):
    # Install a logger before importing the engine so no test message opens bot.log.
    log = logging.getLogger("bot")
    log.handlers = [logging.NullHandler()]
    from src.core import settings, state_store
    settings._values = None
    settings.load(env_file=os.devnull, environ={})
    settings._overrides.update(VIDEO_ENABLED=True, VIDEO_LIVE=False, DRY_RUN=True, HOURLY_BREAK_MINUTES=0)
    state_store.root = lambda: str(root)
    from src.video.store import Store
    return Store()


def background(kind, root, stop, started, native_helper=None):
    store = isolated(root)
    from src.video.config import VideoConfig
    from src.video import connectors, media
    cfg = VideoConfig()
    started.set()
    count = 0
    while not stop.is_set():
        began = time.time()
        if kind == "discovery":
            connectors.ingest(store, "instagram", [{"source_id": f"load{count}", "creator": "fixture",
                "canonical_url": f"https://www.instagram.com/reel/load{count}", "published_at": began,
                "publication_evidence": "engineering fixture", "metrics": {"views": count}, "metrics_observed_at": began}], began, cfg)
            stop.wait(.03)
        else:
            media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=12", "-f", "lavfi", "-i",
                          "sine=frequency=440:duration=12", "-c:v", "libx264", "-threads", "1", "-preset", "fast",
                          "-c:a", "aac", "-shortest", str(Path(root) / "render-load.mp4")], cfg)
            if native_helper:
                from src.video import inspection
                path = Path(root) / "render-load.mp4"
                with tempfile.TemporaryDirectory(prefix="inspect-load-", dir=root) as directory:
                    folder = Path(directory)
                    info = media.probe(path, cfg)
                    frames, _, _ = inspection.frame_pack(path, folder, info, cfg)
                    audio = folder / "audio.wav"
                    media.ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", "48000", str(audio)], cfg)
                    manifest = folder / "manifest.json"
                    manifest.write_text(json.dumps({"audio_path": str(audio), "frames": frames}))
                    measured = json.loads(media.bounded_command(["nice", "-n", "10", native_helper, str(manifest)], timeout=120))
                    inspection.audio_summary(measured, info["duration"])
                    if len(measured["frames"]) != len(frames):
                        raise RuntimeError("load OCR coverage incomplete")
        store.event(time.time(), "load_" + kind, str(count), json.dumps({"start": began, "end": time.time()}))
        count += 1


def replies(root, count):
    isolated(root)
    from src.replies import reply_pipeline as pipeline
    from src.replies.reply_generator import Generation, Outcome
    from src.x.confirmed_write import WriteOutcome
    job = pipeline.Job("load", "LOAD", None)
    draft = Generation(Outcome.WRITTEN, "en", "That chorus has excellent comic timing.")
    def fake_send(*args, **kwargs):
        time.sleep(.015)
        return WriteOutcome.SHIPPED
    def one(i):
        candidate = pipeline.Candidate(f"https://x.com/fixture/status/{100000 + i}", "fixture parent", "LOAD", reply=draft.text)
        begin = time.perf_counter()
        # Fixed model latency is identical in both runs; real send queue/pipeline below.
        time.sleep(.015)
        result = pipeline._send(job, candidate, "fixture", draft)
        return time.perf_counter() - begin, result
    began = time.time()
    with ExitStack() as stack:
        for target, value in (("src.replies.reply_pipeline.require_active", lambda: None),
                              ("src.replies.reply_pipeline._parent_verdict", lambda *a: True),
                              ("src.replies.reply_pipeline._wait_out_reply_spacing", lambda *a: time.sleep(.002)),
                              ("src.x.twitter_client.reply_to_tweet", fake_send),
                              ("src.core.engagement_log.log_reply", lambda *a, **k: None)):
            stack.enter_context(patch(target, value))
        with ThreadPoolExecutor(3) as pool:
            results = list(pool.map(one, range(count)))
    ended = time.time()
    latencies = sorted(r[0] for r in results)
    return {"start": began, "end": ended, "replies": sum(r[1] for r in results), "seconds": ended - began,
            "p95_seconds": latencies[min(len(latencies) - 1, int(len(latencies) * .95))],
            "throughput_per_second": count / (ended - began), "samples": count}


def stalled_worker(root, ready):
    """Real media worker admission with a deliberately stalled fixture provider."""
    store = isolated(root)
    from src.video.config import VideoConfig
    from src.video import workers
    def stalled_media(store, job, now, cfg):
        ready.send(job["token"])
        ready.close()
        signal.pause()
    with patch("src.video.media.process", stalled_media), patch("src.core.video_pressure.pressure", lambda *a: ""):
        workers.run_once("media", store, VideoConfig(), "crash-check", now=100)


def crash_recovery(ctx, root, store, cfg):
    store.enqueue("media", "crashed-fixture", 100)
    receipt, sender = ctx.Pipe(duplex=False)
    child = ctx.Process(target=stalled_worker, args=(root, sender))
    child.start()
    sender.close()
    try:
        if not receipt.poll(10):
            raise RuntimeError("stalled worker failed to claim its fixture job")
        original_token = receipt.recv()
    finally:
        receipt.close()
        child.terminate()
        child.join(5)
        if child.is_alive():
            child.kill()
            child.join()
    # Advance only this isolated journal's clock; production leases are unchanged.
    recovered = store.claim("media", "replacement", 101 + cfg.lease_seconds, cfg)
    return bool(recovered and recovered["token"] != original_token), child.exitcode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=240)
    parser.add_argument("--with-inspection", action="store_true", help="Include real local Mac audio/OCR, still no Codex/network calls")
    args = parser.parse_args()
    if args.samples < 60:
        raise SystemExit("use at least 60 samples")
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="video-load-") as folder:
        native_helper = None
        if args.with_inspection:
            isolated(folder)
            from src.video.inspection import prepare
            from src.video.config import VideoConfig
            native_helper = prepare(VideoConfig())["helper"]
        baseline = replies(folder, args.samples)
        stop = ctx.Event()
        children = []
        for kind in ("discovery", "render"):
            started = ctx.Event()
            child = ctx.Process(target=background, args=(kind, folder, stop, started, native_helper))
            child.start()
            if not started.wait(10):
                raise RuntimeError("load child failed to start")
            children.append(child)
        try:
            loaded = replies(folder, args.samples)
        finally:
            stop.set()
            for child in children:
                child.join(30)
                if child.is_alive():
                    child.terminate()
                    child.join()
        store = isolated(folder)
        events = store.rows("SELECT * FROM events WHERE kind LIKE 'load_%'")
        overlapping = {}
        for kind in ("discovery", "render"):
            ranges = [json.loads(e["detail"]) for e in events if e["kind"] == "load_" + kind]
            overlapping[kind] = sum(r["start"] < loaded["end"] and r["end"] > loaded["start"] for r in ranges)
        from src.core.video_pressure import pressure
        from src.video.config import VideoConfig
        cfg = VideoConfig()
        throttled = pressure(store, cfg, time.time(), resources={"load": 2, "free_mb": 10000})
        resumed = pressure(store, cfg, time.time() + 1000, resources={"load": .1, "free_mb": 10000})
        recovered, crash_exitcode = crash_recovery(ctx, folder, store, cfg)
        ratio = loaded["p95_seconds"] / baseline["p95_seconds"]
        result = {"workload": "real Reply _send/send lock + simulated 15ms model/15ms X; real single-thread 640x360 FFmpeg; fixture-feed SQLite discovery",
                  "local_audio_ocr_included": bool(native_helper), "codex_sessions_in_load_check": False,
                  "live_platform_checks": False, "production_slo_verified": False,
                  "baseline": baseline, "concurrent": loaded, "p95_ratio": ratio, "within_initial_10_percent_target": ratio <= 1.10,
                  "overlapping_jobs": overlapping, "automatic_throttle_reason": throttled, "automatic_resume": resumed == "",
                  "crashed_job_reclaimed_with_new_fence": recovered,
                  "terminated_media_worker_exitcode": crash_exitcode,
                  "recovery_lease_clock_fast_forwarded": True,
                  "limitation": "Real X latency, model quotas, sustained memory/network pressure and real provider access require a deployment observation period."}
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
