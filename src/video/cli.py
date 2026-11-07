"""Explicit activation is distinct from worker starts, resumes and process recovery."""
import argparse
import json
import time

from ..core import settings, state_store
from . import config, operations, publisher, schedule, workers
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Licensed video pipeline; defaults to no public writes")
    parser.add_argument("--dry-run", action="store_true", help="Force all video API writes off for this command/worker")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "queue", "posted", "pause", "resume", "shutdown", "resume-workers", "resume-replies", "report", "baseline", "discover"):
        sub.add_parser(name)
    pre = sub.add_parser("preflight")
    pre.add_argument("--check-api", "--check-session", dest="check_api", action="store_true",
                     help="Check the selected transport: Safari session or optional API account")
    sub.add_parser("prepare-inspector", help="Build/check the local audio/OCR helper; never starts the bot")
    inspection = sub.add_parser("inspect", help="Inspect a local clip in a fresh Codex session; never queues or publishes it")
    inspection.add_argument("path")
    inspection.add_argument("--stage", choices=("source", "output"), default="source")
    discovery = sub.add_parser("check-discovery", help="One public/feed discovery check; never starts workers or publishes")
    discovery.add_argument("platform", choices=config.PLATFORMS)
    discovery.add_argument("--fresh", action="store_true",
                           help="Run fresh Codex research instead of cached results; shared budgets still apply")
    history = sub.add_parser("check-history", help="Resume accessible account-history import; no public writes")
    history.add_argument("--max-seconds", type=int, default=0,
                         help="Continue resumable passes for up to 1..3600 seconds; default is one pass")
    probe = sub.add_parser("probe-upload", help="Upload a local MP4 to Safari and discard it; NEVER submits a post")
    probe.add_argument("path")
    start = sub.add_parser("activate")
    start.add_argument("--live", action="store_true", required=True)
    start.add_argument("--request-id", required=True, help="stable explicit activation identifier, not a boot UUID")
    start.add_argument("--before-replies", action="store_true", help="Keep interactions paused until this startup video is confirmed")
    select = sub.add_parser("select", help="Choose one saved clip; age/score preference only, never permission or quality approval")
    select.add_argument("candidate")
    select.add_argument("--request-id", required=True)
    replacement = sub.add_parser("replace-deleted", help="Explicitly replace one operator-deleted video with the current caption policy")
    replacement.add_argument("post_id")
    replacement.add_argument("--request-id", required=True)
    replacement.add_argument("--operator-deleted", action="store_true", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("role", choices=workers.ROLES)
    worker.add_argument("--once", action="store_true")
    for name in ("preview", "reject", "retry", "review-output"):
        command = sub.add_parser(name)
        command.add_argument("candidate")
    feedback = sub.add_parser("remember", help="Record an actual owner delivery/show/rejection; never publishes")
    feedback.add_argument("candidate")
    feedback.add_argument("decision", choices=("shown", "delivered", "rejected"))
    skip = sub.add_parser("skip")
    skip.add_argument("slot")
    source = sub.add_parser("platform")
    source.add_argument("platform", choices=config.PLATFORMS)
    source.add_argument("mode", choices=("enable", "disable"))
    args = parser.parse_args(argv)
    if args.command == "check-history" and not 0 <= args.max_seconds <= 3600:
        parser.error("check-history --max-seconds must be 0..3600")
    settings.load()
    if args.dry_run:
        with settings.overriding() as override:
            override(VIDEO_LIVE=False, DRY_RUN=True)
            return _execute(args)
    return _execute(args)


def _execute(args):
    state_store.require_migrated()
    cfg, store = config.load(), Store()
    result = None
    if args.command == "remember":
        from .memory import remember
        if settings.get("DRY_RUN"):
            result = {"dry_run": True, "candidate": args.candidate, "decision": args.decision}
        else:
            remember(store, store.candidate(args.candidate), args.decision, time.time())
            result = {"candidate": args.candidate, "decision": args.decision, "published": False}
        print(json.dumps(result))
        return
    if args.command == "worker":
        return workers.run(args.role, once=args.once)
    if args.command == "select":
        from .selection import choose
        result = choose(store, args.candidate, args.request_id, time.time(), dry_run=settings.get("DRY_RUN"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "replace-deleted":
        if settings.get("DRY_RUN"):
            print(json.dumps({"dry_run": True, "replace_post_id": args.post_id, "public_writes": False}))
            return
        from . import ranking
        from ..x.safari_video import SafariVideoClient, publisher_session
        rows = store.rows("SELECT candidate FROM reservations WHERE post_id=? AND state='confirmed'", (args.post_id,))
        if not rows:
            raise SystemExit("Confirmed original receipt is required")
        candidate = store.candidate(rows[0]["candidate"])
        doc = ranking.refresh(store, candidate, time.time(), cfg)
        store.save_candidate(candidate["id"], doc, time.time(), state=candidate["state"],
                             score=doc["ranking"]["total"], fingerprint=json.loads(candidate["fingerprint"]))
        with publisher_session():
            client = SafariVideoClient(store, cfg)
            client.preflight(force=True)
            row = publisher.replace_deleted(store, args.post_id, args.request_id, schedule.utc_now(), cfg,
                                             operator_reports_deleted=args.operator_deleted)
            if row["state"] in ("reserved", "uploading"):
                client.publish_reserved(row["id"], row["token"])
            result = store.rows("SELECT state,post_id,post_url,reason FROM reservations WHERE id=?", (row["id"],))[0]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "prepare-inspector":
        from .inspection import prepare
        with workers.role_lock("media"):
            result = prepare(cfg)
    elif args.command == "inspect":
        from pathlib import Path
        from .inspection import inspect_clip
        with workers.role_lock("media"):
            result = inspect_clip(Path(args.path), args.stage, cfg, store, time.time())
    elif args.command == "check-discovery":
        from .connectors import discover
        result = {"result": discover(store, args.platform, time.time(), cfg, fresh=args.fresh),
                  "health": store.meta("source:" + args.platform),
                  "search": store.meta("public_discovery:" + args.platform)}
    elif args.command == "check-history":
        from .reconcile import import_history
        if cfg.publishing_transport == "safari":
            from ..x.safari_video import SafariVideoClient
            client = SafariVideoClient(store, cfg)
        else:
            from ..x.video_client import XClient
            client = XClient(store, cfg)
        from .security import Deferred
        deadline = time.monotonic() + args.max_seconds
        while True:
            pending, delay = "", 0
            try:
                with workers.role_lock("publisher"):
                    import_history(store, client, cfg, time.time())
            except Deferred as exc:
                pending, delay = str(exc), min(30, exc.retry_after)
            result = {"complete": store.meta("history_import_complete", False),
                      "imported": store.rows("SELECT COUNT(*) AS n FROM history")[0]["n"],
                      "coverage": store.meta("history_coverage"), "cursor": store.meta("history_cursor"), "pending": pending}
            if result["complete"] or time.monotonic() >= deadline:
                break
            print(json.dumps({"history_progress": result}, ensure_ascii=False), flush=True)
            time.sleep(max(0, min(delay, deadline - time.monotonic())))
    elif args.command == "probe-upload":
        if cfg.publishing_transport != "safari" or not config.live():
            raise SystemExit("Upload probe requires live Safari configuration; dry-run never uploads")
        from ..x.safari_video import probe_upload
        result = probe_upload(store, cfg, args.path)
    elif args.command == "preflight":
        result = operations.preflight(store, cfg, network=args.check_api)
    elif args.command == "activate":
        if not config.live():
            raise SystemExit("Activation requires VIDEO_ENABLED=1, VIDEO_LIVE=1 and DRY_RUN=0; no state changed")
        from . import startup
        if args.before_replies or store.meta(startup.KEY):
            startup.arm(store, args.request_id, schedule.utc_now())
            result = startup.activate_when_ready(store, cfg)
            if result is None:
                result = {"activation": "waiting for startup checks; interactions held", "intent": store.meta(startup.KEY)}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        result = operations.preflight(store, cfg, network=True)
        if not result["ready_for_live"]:
            print(json.dumps(result, indent=2))
            raise SystemExit("Live activation blocked by prerequisites above; no startup request created")
        with store.transaction() as db:
            store.put_meta(db, "shutdown", False)
            store.put_meta(db, "paused", False)
            store.put_meta(db, "profile_owned", True)
        result = publisher.request_startup(store, args.request_id, schedule.utc_now(), cfg, explicit_live=True)
    elif args.command == "resume-replies":
        if settings.get("DRY_RUN"):
            raise SystemExit("Dry run cannot release the video-first interaction hold")
        from .startup import KEY
        store.set_meta(KEY, None)
        result = {"interactions": "video-first hold explicitly released; no startup request created"}
    elif args.command in ("pause", "resume", "shutdown", "resume-workers"):
        if args.command == "resume":
            result = operations.preflight(store, cfg, network=True)
            if not result["ready_for_live"] or not config.live():
                print(json.dumps(result, indent=2))
                raise SystemExit("Resume blocked; no startup request is created by resume")
            store.set_meta("paused", False)
            store.set_meta("profile_owned", True)
        elif args.command == "shutdown":
            store.set_meta("paused", True)
            store.set_meta("shutdown", True)
            workers.stop_feature_workers(store)
            if not store.rows("SELECT 1 FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')"):
                store.set_meta("profile_owned", False)
        elif args.command == "resume-workers":
            store.set_meta("shutdown", False)
        else:
            store.set_meta("paused", True)
        result = operations.status(store, cfg)
    elif args.command == "platform":
        store.set_meta("platform_disabled:" + args.platform, args.mode == "disable")
        result = {"platform": args.platform, "enabled": args.mode == "enable"}
    elif args.command == "discover":
        for platform in config.PLATFORMS:
            with store.transaction() as db:
                db.execute("INSERT INTO jobs(kind,item,due) VALUES('discovery',?,?) ON CONFLICT(kind,item) DO UPDATE SET "
                           "due=excluded.due,state=CASE WHEN jobs.state='running' THEN jobs.state ELSE 'pending' END,attempts=0", (platform, time.time()))
        result = {"discovery": "queued immediately; independent worker consumes it"}
    elif args.command == "review-output":
        row = store.candidate(args.candidate)
        if row["state"] in ("reserved", "posted", "duplicate", "rejected"):
            raise SystemExit("Cannot review output of a closed/reserved candidate")
        if not all(row["document"].get(k) for k in ("original_path", "original_sha256", "output_path", "output_sha256")):
            raise SystemExit("Saved original and output are required")
        if settings.get("DRY_RUN"):
            result = {"candidate": args.candidate, "dry_run": True, "public_writes": False}
        else:
            with store.transaction() as db:
                db.execute("INSERT INTO jobs(kind,item,due) VALUES('inspect_output',?,?) ON CONFLICT(kind,item) "
                           "DO UPDATE SET due=excluded.due,state=CASE WHEN jobs.state='running' THEN jobs.state ELSE 'pending' END,attempts=0",
                           (args.candidate, time.time()))
            result = {"candidate": args.candidate, "output_review": "queued; no approval or publication"}
    elif args.command in ("reject", "retry"):
        row = store.candidate(args.candidate)
        if row["state"] in ("reserved", "posted"):
            raise SystemExit("Cannot alter a reserved/posted clip; pause and reconcile its reservation")
        if args.command == "reject":
            from .memory import remember
            remember(store, row, "rejected", time.time())
        with store.transaction() as db:
            if args.command == "reject":
                from .selection import KEY
                choice = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
                if choice and json.loads(choice[0])["candidate"] == args.candidate:
                    db.execute("DELETE FROM meta WHERE key=?", (KEY,))
            db.execute("UPDATE candidates SET state=?,reason='operator action' WHERE id=?",
                       ("rejected" if args.command == "reject" else "discovered", args.candidate))
            if args.command == "retry":
                db.execute("UPDATE jobs SET state='pending',due=?,attempts=0 WHERE item=? AND state<>'running'", (time.time(), args.candidate))
        result = {"candidate": args.candidate, "action": args.command}
    elif args.command == "skip":
        with store.transaction() as db:
            changed = db.execute("UPDATE slots SET state='skipped',reason='operator skip' WHERE id=? AND state='pending'", (args.slot,)).rowcount
        result = {"slot": args.slot, "skipped": bool(changed)}
    elif args.command == "preview":
        result = store.candidate(args.candidate)
        # Prints local preview/evidence only; never opens Safari or publishes.
    elif args.command == "baseline":
        data = store.rows("SELECT seconds FROM reply_samples WHERE phase='confirmed' AND at>? ORDER BY seconds", (time.time() - 3600,))
        if len(data) < cfg.min_latency_samples:
            raise SystemExit("Not enough measured reply sends; collect baseline with video background workers stopped")
        p95 = data[min(len(data) - 1, int(len(data) * .95))]["seconds"]
        store.set_meta("reply_baseline_p95", p95)
        result = {"reply_baseline_p95": p95, "samples": len(data), "comparability": "operator must use comparable reply traffic/model load"}
    elif args.command == "report":
        operations.daily_report(store, cfg)
        result = operations.status(store, cfg)
    elif args.command == "queue":
        result = store.rows("SELECT id,platform,creator,state,reason,score FROM candidates ORDER BY discovered DESC LIMIT 100")
    elif args.command == "posted":
        result = []
        for row in store.rows("SELECT * FROM history ORDER BY published DESC"):
            doc = json.loads(row["payload"])
            if doc.get("candidate"):
                result.append({"post_id": row["post_id"], "published": row["published"], **{
                    key: doc.get(key) for key in ("url", "candidate", "source_url", "platform", "source_id",
                                                 "creator", "caption", "original_sha256", "output_sha256")}})
    else:
        result = operations.status(store, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
