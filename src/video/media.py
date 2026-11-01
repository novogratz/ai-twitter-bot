"""Preserve originals, inspect actual AV, crop conservatively, brand and verify."""
from fractions import Fraction
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

from . import ranking
from .security import AccessError, Deferred, imported_file, request, sha256
from .store import ASSETS, SAVED_ASSETS

_active_process = None
_job_deadline = None


class CommandFailure(ValueError):
    def __init__(self, returncode, stdout, stderr):
        super().__init__(f"media/provider process failed ({returncode}); source text withheld")
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def cancel_active():
    """Worker shutdown also stops its render/inspection subprocess group."""
    if _active_process is not None and _active_process.poll() is None:
        import signal
        try:
            os.killpg(_active_process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def bounded_command(argv, payload=None, timeout=120, *, max_output=2_000_000, memory_mb=2048, cwd=None):
    """No shell. Bound runtime and captured output, and kill the whole process group."""
    global _active_process
    if _job_deadline is not None:
        timeout = min(timeout, _job_deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError("complete media job deadline")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr, tempfile.TemporaryFile() as stdin:
        if payload is not None:
            stdin.write((payload if isinstance(payload, str) else json.dumps(payload, allow_nan=False)).encode())
        stdin.seek(0)
        process = subprocess.Popen([str(x) for x in argv], stdin=stdin, stdout=stdout, stderr=stderr,
                                   start_new_session=True, cwd=cwd)
        _active_process = process
        deadline = time.monotonic() + timeout
        try:
            import psutil
            monitor = psutil.Process(process.pid)
        except ImportError:
            monitor = None  # optional dependency absent in lightweight tests; live preflight refuses it
        next_memory_check = 0
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("media/provider process deadline")
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > max_output:
                    raise ValueError("media/provider output limit")
                if monitor is not None and time.monotonic() >= next_memory_check:
                    try:
                        used = monitor.memory_info().rss + sum(c.memory_info().rss for c in monitor.children(recursive=True))
                        if used > memory_mb * 1024 ** 2:
                            raise ValueError("media/provider memory budget")
                    except psutil.NoSuchProcess:
                        pass
                    next_memory_check = time.monotonic() + .5
                time.sleep(.05)
            if process.returncode:
                stdout.seek(0)
                stderr.seek(0)
                raise CommandFailure(process.returncode, stdout.read(max_output), stderr.read(max_output))
            if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > max_output:
                raise ValueError("media/provider output limit")
            stdout.seek(0)
            result = stdout.read(max_output + 1)
            if len(result) > max_output:
                raise ValueError("media/provider output limit")
            return result
        finally:
            if process.poll() is None:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            _active_process = None


def ffmpeg(args, cfg, *, output_limit=2_000_000):
    return bounded_command(["nice", "-n", "10", "ffmpeg", "-nostdin", "-v", "error", "-y",
                            "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
                            "-max_alloc", "134217728", *args], timeout=cfg.render_timeout_seconds,
                           max_output=output_limit, memory_mb=cfg.max_media_memory_mb)


def probe(path, cfg):
    data = json.loads(bounded_command(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                                     "-show_format", "-show_streams", "-of", "json", str(path)], timeout=30))
    streams = data["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    duration = float(data["format"]["duration"])
    fps = float(Fraction(video["avg_frame_rate"]))
    width, height = int(video["width"]), int(video["height"])
    if (not audio or not .5 <= duration <= cfg.max_duration_seconds or not 1 <= fps <= 60
            or not 32 <= width <= 4096 or not 32 <= height <= 4096 or not 1 / 3 <= width / height <= 3
            or video.get("sample_aspect_ratio", "1:1") not in ("1:1", "N/A")
            or any(s.get("side_data_type") == "Display Matrix" and s.get("rotation", 0) != 0 for s in video.get("side_data_list", []))):
        raise ValueError("unsupported duration, audio, rotation, aspect, dimensions or genuine frame rate")
    return {"duration": duration, "width": width, "height": height, "fps": fps,
            "audio_start": float(audio.get("start_time", 0)), "video_start": float(video.get("start_time", 0)),
            "video_codec": video["codec_name"], "audio_codec": audio["codec_name"]}


def audio_samples(path, cfg):
    import numpy as np
    raw = ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
                  "-f", "s16le", "pipe:1"], cfg, output_limit=3_000_000)
    return np.frombuffer(raw, dtype="<i2").astype(float)


def fingerprint(path, info, cfg):
    """Ordered full/central image hashes plus spectral audio; music alone never dedups."""
    import numpy as np
    count = min(30, max(4, math.ceil(info["duration"])))
    samples = []
    for index in range(count):
        at = min(info["duration"] - .05, (index + .5) * info["duration"] / count)
        raw = ffmpeg(["-ss", str(at), "-protocol_whitelist", "file,pipe", "-i", str(path),
                      "-frames:v", "1", "-vf", "scale=64:64", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], cfg)
        if len(raw) != 4096:
            raise ValueError("missing temporal frame")
        frame = Image.frombytes("L", (64, 64), raw)
        samples.append(visual_hash(frame))
    pcm = audio_samples(path, cfg)
    spectral = []
    for start in range(0, len(pcm) - 4000, 4000):
        spectrum = abs(np.fft.rfft(pcm[start:start + 4000] * np.hanning(4000)))
        bands = np.array([np.mean(spectrum[lo:hi]) for lo, hi in zip(np.geomspace(10, 2000, 17).astype(int)[:-1],
                                                                   np.geomspace(10, 2000, 17).astype(int)[1:])])
        bits = bands[1:] > bands[:-1]
        spectral.append(sum(int(bit) << i for i, bit in enumerate(bits)))
    return {"sha256": sha256(path), "visual": samples, "audio": spectral, "duration": info["duration"]}


def visual_hash(frame):
    """Same ordered crop-tolerant hash for file decoding and browser canvas reads."""
    frame = frame.convert("L").resize((64, 64))
    variants = []
    for margin in (0, 6, 12):
        pixels = list(frame.crop((margin, margin, 64 - margin, 64 - margin)).resize((9, 8)).tobytes())
        bits = [pixels[y * 9 + x + 1] > pixels[y * 9 + x] for y in range(8) for x in range(8)]
        variants.append(f"{sum(int(bit) << i for i, bit in enumerate(bits)):016x}")
    return variants


def duplicate(left, right):
    if left["sha256"] == right["sha256"]:
        return True
    a, b = left.get("visual", []), right.get("visual", [])
    if min(len(a), len(b)) < 4:
        return False
    # Align temporally over relative sample positions and small trim offsets.
    ratios = []
    for offset in range(-3, 4):
        matches, compared = 0, 0
        for i, frame in enumerate(a):
            j = round(i * (len(b) - 1) / (len(a) - 1)) + offset
            if 0 <= j < len(b):
                distance = min((int(x, 16) ^ int(y, 16)).bit_count() for x in frame for y in b[j])
                matches += distance <= 7
                compared += 1
        if compared >= 4:
            ratios.append(matches / compared)
    # Ordered subsequence matching also catches trimmed copies. Music alone
    # cannot contribute a visual match, and reordered unrelated shots do not fit.
    previous = [0] * (len(b) + 1)
    for frame in a:
        current = [0]
        for j, other in enumerate(b):
            match = min((int(x, 16) ^ int(y, 16)).bit_count() for x in frame for y in other) <= 7
            current.append(previous[j] + 1 if match else max(previous[j + 1], current[-1]))
        previous = current
    similarity = max(max(ratios, default=0), previous[-1] / min(len(a), len(b)))
    aa, bb = left.get("audio", []), right.get("audio", [])
    sound = sum((x ^ y).bit_count() <= 2 for x, y in zip(aa, bb)) / max(1, min(len(aa), len(bb)))
    return similarity >= .92 or (similarity >= .75 and sound >= .8)


@lru_cache(maxsize=2048)
def fingerprint_match(left, right):
    """Cache immutable sequence comparisons across publisher ticks."""
    return duplicate(json.loads(left), json.loads(right))


def matches_history(doc, posted):
    """Permanent identifiers and both media versions survive asset cleanup."""
    if doc.get("canonical_url") and doc["canonical_url"] == posted.get("source_url"):
        return True
    if (doc.get("source_id") and doc.get("platform") == posted.get("platform")
            and doc["source_id"] == posted.get("source_id")):
        return True
    keys = ("original_sha256", "output_sha256")
    if {doc[k] for k in keys if doc.get(k)} & {posted[k] for k in keys if posted.get(k)}:
        return True
    current = [doc[k] for k in ("original_fingerprint", "output_fingerprint") if doc.get(k)]
    prior = [posted[k] for k in ("fingerprint", "original_fingerprint", "output_fingerprint") if posted.get(k)]
    return any(fingerprint_match(json.dumps(left, sort_keys=True), json.dumps(right, sort_keys=True))
               for left in current for right in prior)


def download(doc, destination, cfg, store, now):
    if not ranking.permission(doc, cfg, now):
        raise AccessError("licensed video and audio permission required before downloading")
    used = sum(p.stat().st_size for root in (ASSETS, SAVED_ASSETS)
               for p in Path(str(root)).rglob("*") if p.is_file())
    if used + 3 * cfg.max_download_bytes > cfg.storage_budget_bytes:
        raise AccessError("storage budget exhausted")
    if doc.get("source_download"):
        from .source_browser import download_player
        temp = destination.with_suffix(".partial")
        try:
            download_player(doc, temp, cfg, store, now)
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)
        return
    if not store.budget(doc["platform"], "download_bytes", cfg.max_download_bytes, cfg.download_budget_bytes, now):
        raise AccessError("daily download budget exhausted")
    temp = destination.with_suffix(".partial")
    consumed = 0
    try:
        with temp.open("xb") as out:
            if doc.get("local_file"):
                source = imported_file(doc["local_file"], cfg.local_import_roots)
                if source.stat().st_size > cfg.max_download_bytes:
                    raise AccessError("source exceeds download size cap")
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, out, 65536)
            else:
                request(doc["media_url"], hosts=cfg.media_hosts, sink=out,
                        max_bytes=cfg.max_download_bytes, timeout=cfg.task_timeout_seconds,
                        mime={"video/mp4", "video/quicktime", "video/webm"})
            out.flush()
            os.fsync(out.fileno())
            consumed = out.tell()
        temp.replace(destination)
        destination.chmod(0o444)
    finally:
        if temp.exists():
            consumed = max(consumed, temp.stat().st_size)
        store.refund_budget(doc["platform"], "download_bytes", max(0, cfg.max_download_bytes - consumed), now)
        temp.unlink(missing_ok=True)


def inspect(path, stage, cfg, store, now, **extra):
    if cfg.inspection_provider == "codex":
        from .inspection import inspect_clip
        return inspect_clip(path, stage, cfg, store, now, **extra)
    if not cfg.inspection_command:
        raise AccessError("no actual video/audio/OCR inspection provider configured")
    if not store.budget("inspection", "inference_usd", cfg.inspection_cost_ceiling_usd, cfg.inference_budget_usd, now):
        raise AccessError("inference budget exhausted")
    payload = {"version": 1, "stage": stage, "media_path": str(path.resolve()), "sha256": sha256(path),
               "targets": cfg.targets, "watermark_allowlist": [cfg.watermark],
               "source_content_is_untrusted_data": True, **extra}
    result = json.loads(bounded_command(cfg.inspection_command, payload, cfg.task_timeout_seconds, memory_mb=cfg.max_media_memory_mb))
    if result.get("sha256") != payload["sha256"] or result.get("version") != 1:
        raise ValueError("inspection response not bound to supplied media")
    if stage == "output" and result.get("full_clip_inspected") is not True:
        raise ValueError("output overlay/action inspection must cover the full clip")
    return result


def render(original, output, info, evidence, cfg):
    crop = evidence.get("safe_crop", [0, 0, info["width"], info["height"]])
    retaining = cfg.allow_source_overlays and evidence.get("overlays_removable_by_crop") is not True
    if retaining:
        crop = [0, 0, info["width"], info["height"]]
    if len(crop) != 4 or any(type(n) is not int or n < 0 or n % 2 for n in crop):
        raise ValueError("invalid safe crop")
    x, y, w, h = crop
    if (not w or not h or x + w > info["width"] or y + h > info["height"]
            or w * h < .90 * info["width"] * info["height"]
            or abs(w / h - info["width"] / info["height"]) > .015
            or evidence.get("crop_preserves_action") is not True):
        raise ValueError("destructive or unverified crop")
    if evidence.get("overlays_removable_by_crop") is not True and not retaining:
        raise ValueError("overlay requires unavailable cleanup; no inpainting is pretended")
    if not cfg.watermark or not cfg.watermark.startswith("@"):
        raise ValueError("operator watermark missing")
    scale = min(1, 1080 / min(w, h), 1920 / max(w, h))
    ow, oh = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
    font = ImageFont.truetype(cfg.font_file, max(14, int(ow * .035)))
    box = font.getbbox(cfg.watermark)
    stamp = Image.new("RGBA", (box[2] - box[0] + 16, box[3] - box[1] + 12))
    ImageDraw.Draw(stamp).text((8 - box[0], 6 - box[1]), cfg.watermark, font=font,
                               fill=(255, 255, 255, 225), stroke_width=1, stroke_fill=(0, 0, 0, 190))
    watermark_path = output.with_suffix(".watermark.png")
    stamp.save(watermark_path)
    position = evidence.get("watermark_position", "bottom")
    if position not in ("top", "bottom") or evidence.get("watermark_clear_of_action") is not True:
        raise ValueError("watermark safe placement unverified")
    ypos = "H-h-0.06*H" if position == "bottom" else "0.06*H"
    filters = f"[0:v]crop={w}:{h}:{x}:{y},scale={ow}:{oh},setsar=1[v];[v][1:v]overlay=(W-w)/2:{ypos}:format=auto[out]"
    try:
        ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(original), "-i", str(watermark_path),
                "-filter_complex", filters, "-map", "[out]", "-map", "0:a:0", "-sn", "-dn", "-map_metadata", "-1",
                "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", "16", "-profile:v", "high",
                "-pix_fmt", "yuv420p", "-x264-params", "open-gop=0", "-fps_mode", "passthrough",
                "-c:a", "aac", "-profile:a", "aac_low", "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", str(output)], cfg)
    finally:
        watermark_path.unlink(missing_ok=True)


def technical_qc(original, output, original_info, cfg):
    import numpy as np
    result = probe(output, cfg)
    ffmpeg(["-xerror", "-protocol_whitelist", "file,pipe", "-i", str(output), "-f", "null", "-"], cfg)
    if abs(result["duration"] - original_info["duration"]) > .15 or abs(result["fps"] - original_info["fps"]) > .1:
        raise ValueError("duration or genuine frame rate changed")
    if result["video_codec"] != "h264" or result["audio_codec"] != "aac":
        raise ValueError("output codec mismatch")
    a, b = audio_samples(original, cfg), audio_samples(output, cfg)
    n = min(len(a), len(b))
    correlation = float(np.corrcoef(a[:n], b[:n])[0, 1])
    if not math.isfinite(correlation) or correlation < .95 or abs(result["audio_start"] - result["video_start"]) > .08:
        raise ValueError("audio timing/signal changed or silent")
    defects = []
    for path, duration in ((original, original_info["duration"]), (output, result["duration"])):
        tags = ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-an", "-vf",
                       "blackdetect=d=0.15:pix_th=0.05,freezedetect=n=-50dB:d=1,metadata=print:file=-",
                       "-f", "null", "-"], cfg).decode("utf-8", "replace")
        totals = {}
        for kind, prefix in (("black", "lavfi.black_"), ("freeze", "lavfi.freezedetect.freeze_")):
            active, total = None, 0.0
            for line in tags.splitlines():
                if line.startswith(prefix + "start="):
                    active = float(line.split("=", 1)[1])
                elif line.startswith(prefix + "end=") and active is not None:
                    total += max(0, float(line.split("=", 1)[1]) - active)
                    active = None
            if active is not None:
                total += max(0, duration - active)
            totals[kind] = total
        defects.append(totals)
    if any(defects[1][kind] > defects[0][kind] + .15 for kind in ("black", "freeze")):
        raise ValueError("introduced black/frozen frames")
    return {"decoded": True, "audio_sync": True, "audio_correlation": correlation,
            "no_new_black_freeze": True, "defect_seconds": defects, "probe": result}


def process(store, job, now, cfg):
    global _job_deadline
    _job_deadline = time.monotonic() + cfg.media_job_seconds
    try:
        return _process(store, job, now, cfg)
    finally:
        _job_deadline = None


def _process(store, job, now, cfg):
    row = store.candidate(job["item"])
    if row["state"] in ("rejected", "posted", "reserved", "duplicate", "expired"):
        return
    doc = row["document"]
    # Separate work directories prevent a stale worker overwriting its successor.
    folder = Path(str(ASSETS)) / row["id"] / job["token"]
    folder.mkdir(parents=True, exist_ok=True)
    original, output = folder / "original.mp4", folder / "branded.mp4"
    try:
        grant = ranking.permission(doc, cfg, now)
        if grant:
            doc["permission_record"] = {**grant, "checked_at": now}
        doc["inspection_provider"] = {"provider": cfg.inspection_provider,
                                      "executable": cfg.inspection_command[0] if cfg.inspection_command else None,
                                      "protocol": 1, "requested_at": now}
        previous = Path(doc["original_path"]) if doc.get("original_path") else None
        candidate_root = (Path(str(ASSETS)) / row["id"]).resolve()
        saved_root = (Path(str(SAVED_ASSETS)) / row["id"]).resolve()
        if (grant and previous is not None and previous.is_file()
                and (previous.resolve().is_relative_to(candidate_root)
                     or previous.resolve().is_relative_to(saved_root))
                and sha256(previous) == doc.get("original_sha256")):
            # A quota wait must not repeatedly download the same licensed bytes.
            # Old immutable files can be hard-linked into this fenced attempt.
            os.link(previous, original)
        else:
            download(doc, original, cfg, store, now)
        info = probe(original, cfg)
        doc.update(original_path=str(original), original_sha256=sha256(original), probe=info)
        original_fp = fingerprint(original, info, cfg)
        doc["original_fingerprint"] = original_fp
        for old in store.rows("SELECT id,fingerprint FROM candidates WHERE fingerprint IS NOT NULL AND id<>?", (row["id"],)):
            if duplicate(original_fp, json.loads(old["fingerprint"])):
                store.save_candidate(row["id"], doc, time.time(), state="duplicate", reason=f"same sequence as {old['id']}", fingerprint=original_fp, job=job)
                return
        for old in store.rows("SELECT payload FROM history"):
            if matches_history(doc, json.loads(old["payload"])):
                store.save_candidate(row["id"], doc, time.time(), state="duplicate", reason="already in own history", fingerprint=original_fp, job=job)
                return
        doc["inspection"] = inspect(original, "source", cfg, store, now, duration=info["duration"])
        reason = ranking.gate(doc, cfg, now)
        if reason:
            raise ValueError(reason)
        render(original, output, info, doc["inspection"], cfg)
        doc.update(output_path=str(output), output_sha256=sha256(output), brand=cfg.watermark)
        technical = technical_qc(original, output, info, cfg)
        final = inspect(output, "output", cfg, store, now, original_path=str(original),
                        source_inspection=doc["inspection"], duration=info["duration"])
        doc["qc"] = {**final, **technical}
        doc["output_fingerprint"] = fingerprint(output, technical["probe"], cfg)
        doc["caption"] = ranking.caption(doc, cfg, now)
        doc = ranking.refresh(store, row | {"document": doc}, now, cfg)
        reason = ranking.gate(doc, cfg, now, final=True)
        store.save_candidate(row["id"], doc, time.time(), state="held" if reason else "ready", reason=reason,
                             score=doc["ranking"]["total"], fingerprint=original_fp, job=job)
        store.enqueue("novelty", row["id"], now)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Deferred) else f"{type(exc).__name__}: media verification incomplete"
        store.save_candidate(row["id"], doc, time.time(), state="held", reason=reason,
                             fingerprint=doc.get("original_fingerprint"), job=job)
        raise
