"""Status, preflight, cleanup and local daily reporting; no new messaging channel."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

from ..core import state_store
from . import config, inventory, schedule
from .connectors import ADAPTERS
from .store import ASSETS

REPORT = state_store.StateFile("video_daily_report.json", {}, state_store.DISPOSABLE)


def status(store, cfg, now=None):
    from .reconcile import history_ready
    from .startup import KEY, waiting_reason
    from .selection import KEY as SELECTION_KEY
    now = now or schedule.utc_now()
    key, at = schedule.next_slot(now, cfg)
    samples = store.rows("SELECT seconds,backlog FROM reply_samples WHERE phase='confirmed' AND at>? ORDER BY seconds",
                         (now.timestamp() - 900,))
    telemetry = {"samples": len(samples), "baseline_p95_seconds": store.meta("reply_baseline_p95"),
                 "p95_seconds": samples[min(len(samples) - 1, int(.95 * len(samples)))]["seconds"] if samples else None,
                 "maximum_observed_send_depth": max((r["backlog"] for r in samples), default=None)}
    return {"enabled": config.enabled(), "live_configured": config.live(), "transport": cfg.publishing_transport,
            "paused": store.meta("paused", True),
            "shutdown": store.meta("shutdown", False), "next_slot": {"id": key, "at": at.isoformat()},
            "slots": store.rows("SELECT * FROM slots ORDER BY due DESC LIMIT 16"),
            "startup": store.rows("SELECT * FROM startup ORDER BY requested DESC LIMIT 3"),
            "video_first": {"intent": store.meta(KEY), "waiting_reason": waiting_reason(store)},
            "operator_selection": store.meta(SELECTION_KEY),
            "buffer": store.rows("SELECT state,COUNT(*) AS count FROM candidates GROUP BY state"),
            "window_coverage": inventory.report(store, cfg, now),
            "workers": store.rows("SELECT * FROM workers"),
            "worker_resources": store.meta("resource_observation"), "reply_telemetry": telemetry,
            "throttle": {role: store.meta("throttle:" + role) for role in ("discovery", "media")},
            "source_health": {p: store.meta("source:" + p, cls(cfg).capability()) for p, cls in ADAPTERS.items()},
            "publish_unknown": store.rows("SELECT id,slot,candidate,reason FROM reservations WHERE state='publish_unknown'"),
            "history_coverage": store.meta("history_coverage"),
            "history_initial_ready": history_ready(store, cfg),
            "history_archive_complete": store.meta("history_import_complete", False),
            "costs": store.rows("SELECT * FROM costs ORDER BY day DESC LIMIT 20")}


def preflight(store, cfg, *, network=False):
    blockers = []
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            blockers.append(f"missing {binary}")
    for module in ("numpy", "psutil", "jsonschema"):
        if not importlib.util.find_spec(module):
            blockers.append(f"missing media dependency {module}")
    if cfg.inspection_provider == "codex":
        from .inspection import capability
        inspector = capability(cfg)
        blockers.extend(inspector["missing"])
        if network and not inspector["missing"]:
            from .media import bounded_command
            try:
                bounded_command(["codex", "login", "status"], timeout=10)
            except Exception:
                blockers.append("Codex CLI login is unavailable; use the existing ChatGPT login")
    elif not cfg.inspection_command:
        blockers.append("no actual temporal video/audio/OCR inspector configured")
    elif not Path(cfg.inspection_command[0]).is_file():
        blockers.append("inspection executable missing")
    if not Path(cfg.font_file).is_file():
        blockers.append("watermark font missing")
    if not cfg.watermark:
        blockers.append("operator watermark missing")
    if not cfg.permissions:
        blockers.append("no video/audio creator permissions registered")
    if not any(cls(cfg).capability()["status"] != "blocked" for cls in ADAPTERS.values()):
        blockers.append("all discovery adapters lack a permitted configured source")
    if cfg.publishing_transport == "safari":
        if sys.platform != "darwin":
            blockers.append("Safari publishing requires macOS AppleScript")
        if network:
            from ..x.safari_video import SafariVideoClient
            try:
                SafariVideoClient(store, cfg).preflight()
                store.set_meta("account_verified", True)
            except Exception as exc:
                store.set_meta("next_browser_read", 0)
                blockers.append("Safari session check pending/failed: " + type(exc).__name__)
        elif not store.meta("safari_account_proof"):
            blockers.append("Safari account session has not been checked")
    else:
        creds = config.credentials().get("x", {})
        if not creds.get("user_access_token") or not creds.get("user_id"):
            blockers.append("missing X OAuth user_access_token/user_id in private credentials file")
        if not cfg.x_reads_enabled:
            blockers.append("X API access/cost budget not enabled")
        if network and creds.get("user_access_token") and cfg.x_reads_enabled:
            from ..x.video_client import XClient
            try:
                XClient(store, cfg).preflight()
                store.set_meta("account_verified", True)
            except Exception as exc:
                blockers.append("X permission/account check failed: " + type(exc).__name__)
    from .reconcile import history_ready
    if not history_ready(store, cfg):
        blockers.append("required initial account history not imported/fingerprinted")
    now = time.time()
    from ..core import settings
    if state_store.bot_holds_lock(str(Path(settings.PROJECT_ROOT).resolve())):
        marker = store.meta("main_profile_owner", {})
        try:
            pid = int((Path(settings.PROJECT_ROOT) / "bot.lock").read_text().strip())
        except (OSError, ValueError):
            pid = None
        if (marker.get("pid") != pid or not marker.get("video_enabled") or now - marker.get("heartbeat", 0) > 60):
            blockers.append("running main process has not confirmed video schedule ownership; explicitly restart it with VIDEO_ENABLED=1")
    workers = {row["role"]: row for row in store.rows("SELECT * FROM workers")}
    for role in ("discovery", "media", "publisher"):
        if role not in workers or now - workers[role]["heartbeat"] > cfg.lease_seconds:
            blockers.append(f"{role} worker heartbeat missing/stale")
    if store.rows("SELECT 1 FROM reservations WHERE state IN ('publish_unknown','submitting')"):
        blockers.append("uncertain publication must be reconciled")
    # The legacy editorial journal is guarded and must not have an ambiguous
    # submission when responsibility is transferred to the video publisher.
    from ..editorial.slot_journal import FileJournal
    submissions = FileJournal().submissions(schedule.local(schedule.utc_now()).date())
    if submissions.pending:
        blockers.append("legacy editorial submission is pending; reconcile before takeover")
    return {"ready_for_live": not blockers, "blockers": blockers, "status": status(store, cfg)}


def daily_report(store, cfg, now=None):
    now = now or schedule.utc_now()
    day = schedule.local(now).date().isoformat()
    if store.meta("reported_day") == day:
        return
    payload = status(store, cfg, now)
    payload["report_day"] = day
    payload["learning"] = learning_report(store)
    REPORT.write(payload)
    store.set_meta("reported_day", day)
    from ..core.logger import log
    log.info("[VIDEO] Daily report saved: %s; buffer=%s; primary-window shortfall=%s; source health=%s", REPORT.name, payload["buffer"],
             payload["window_coverage"]["shortfall"],
             {p: h["status"] for p, h in payload["source_health"].items()})


def cleanup(store, cfg, now):
    from .selection import selected
    # An explicit edit request is operator-owned work, not disposable discovery.
    # Expiry still removes eligibility, but must not destroy that saved original
    # or a render which a worker is currently reading/writing.
    protected = {r["id"] for r in store.rows("SELECT id,document FROM candidates")
                 if any(json.loads(r["document"]).get(key) for key in ("operator_edit_request", "operator_selection"))}
    protected.update(r["item"] for r in store.rows(
        "SELECT item FROM jobs WHERE state='running' AND lease>=?", (now,)))
    protected.update(r["candidate"] for r in store.rows(
        "SELECT candidate FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')"))
    with store.transaction() as db:
        old = db.execute("SELECT id,document FROM candidates WHERE state IN ('discovered','held','ready') "
                         "AND published IS NOT NULL AND published<?", (now - cfg.max_age_hours * 3600,)).fetchall()
        for row in old:
            if not selected(json.loads(row["document"]), now):
                db.execute("UPDATE candidates SET state='expired',reason='freshness expired' WHERE id=?", (row["id"],))
        db.execute("UPDATE candidates SET state='expired',reason='unknown publication time aged out' "
                   "WHERE state IN ('discovered','held') AND published IS NULL AND discovered<?", (now - cfg.max_age_hours * 3600,))
        db.execute("DELETE FROM reply_samples WHERE at<?", (now - 3 * 86400,))
        db.execute("DELETE FROM model_calls WHERE lease<?", (now - 86400,))
    for row in store.rows("SELECT id,document FROM candidates WHERE state IN ('expired','rejected','duplicate')"):
        if row["id"] in protected:
            continue
        folder = Path(str(ASSETS)) / row["id"]
        if folder.is_dir():
            shutil.rmtree(folder)
    for row in store.rows("SELECT candidate FROM reservations WHERE state='confirmed' AND confirmed<?",
                          (now - cfg.asset_retention_days * 86400,)):
        if row["candidate"] in protected:
            continue
        folder = Path(str(ASSETS)) / row["candidate"]
        if folder.is_dir():
            shutil.rmtree(folder)
    # Remove abandoned attempt directories after their fencing lease. Do not
    # remove the attempt currently referenced by a candidate or running job.
    referenced = {Path(json.loads(r["document"])["original_path"]).parent for r in
                  store.rows("SELECT document FROM candidates") if json.loads(r["document"]).get("original_path")}
    running = {r["token"] for r in store.rows("SELECT token FROM jobs WHERE state='running' AND lease>=?", (now,))}
    for candidate in Path(str(ASSETS)).glob("*"):
        if not candidate.is_dir() or candidate.name in protected:
            continue
        for attempt in candidate.iterdir():
            if (attempt.is_dir() and attempt not in referenced and attempt.name not in running
                    and now - attempt.stat().st_mtime > cfg.lease_seconds):
                shutil.rmtree(attempt)
    # Permanent posting/source/evidence records and original/edited fingerprints remain.


def learning_report(store):
    """Conservative advisory comparisons; no self-modifying weights or schedules."""
    import math
    import statistics
    samples = []
    missing = 0
    for row in store.rows("SELECT o.payload,c.document FROM outcomes o JOIN reservations r ON r.post_id=o.post_id "
                          "JOIN candidates c ON c.id=r.candidate WHERE o.window=24"):
        outcome, doc = json.loads(row["payload"]), json.loads(row["document"])
        observed = outcome.get("observed", {})
        public = observed.get("data", {}).get("public_metrics", {})
        media = observed.get("includes", {}).get("media", [])
        counts = [m.get("public_metrics", {}).get("view_count") for m in media if m.get("type") == "video"]
        views = counts[0] if len(counts) == 1 else None
        shares = public.get("retweet_count")
        if type(views) is not int or views <= 0 or type(shares) is not int or shares < 0:
            missing += 1
            continue
        samples.append({"share_rate": 1000 * shares / views,
                        "entertainment": doc.get("inspection", {}).get("entertainment_score"),
                        "views": views, "shares": shares})
    result = {"automatic_changes": False, "valid_24h_posts": len(samples), "missing_metrics": missing,
              "minimum_posts_for_suggestions": 30, "suggestions": [], "causal_claim": False,
              "retention": "reported only when API supplies observed playback counters"}
    low = [s["share_rate"] for s in samples if s["entertainment"] is not None and s["entertainment"] < 17]
    high = [s["share_rate"] for s in samples if s["entertainment"] is not None and s["entertainment"] >= 17]
    if len(samples) >= 30 and min(len(low), len(high)) >= 10:
        gap = statistics.mean(high) - statistics.mean(low)
        error = math.sqrt(statistics.variance(high) / len(high) + statistics.variance(low) / len(low))
        result["comparison"] = {"low_n": len(low), "high_n": len(high), "share_rate_gap_per_1000_views": gap,
                                "approximate_standard_error": error, "limitations": "observational, selection-biased, unadjusted for cast/platform/time"}
        if gap > max(0, 2 * error):
            result["suggestions"].append({"proposal": "Evaluate a +2 entertainment / -2 momentum weighting on a held-out sample",
                                           "maximum_weight_change": 2, "requires_operator_evaluation": True,
                                           "changes_posting_times_or_reply_policy": False})
    return result
