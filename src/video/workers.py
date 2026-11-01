"""Independent processes; overnight discovery/media never enter Safari or Reply queues."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from ..core import settings, state_store, video_pressure
from ..core.logger import log
from . import config, connectors, media, operations, publisher, ranking, reconcile, schedule
from .store import Store
from .security import Deferred

ROLES = ("discovery", "media", "publisher")
_ROLE_HOLDERS = {}


def owns_role(role):
    return _ROLE_HOLDERS.get(role) == os.getpid()


@contextmanager
def role_lock(role):
    if role not in ROLES:
        raise ValueError("unknown video worker role")
    path = state_store.StatePath("video_" + role + ".lock")
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"video {role} worker already running") from None
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        _ROLE_HOLDERS[role] = os.getpid()
        try:
            yield
        finally:
            _ROLE_HOLDERS.pop(role, None)


def seed_jobs(store, cfg, now):
    for platform in config.PLATFORMS:
        store.enqueue("discovery", platform, now)


def run_once(role, store, cfg, owner, *, now=None):
    now = now if now is not None else time.time()
    if store.meta("shutdown", False):
        return "shutdown"
    store.heartbeat(role, owner, now)
    if role == "publisher":
        # Publishing keeps its reserved request budget under discovery/media load.
        from .startup import tick
        tick(store, cfg, now)
        result = publisher.publish_tick(store, cfg)
        if cfg.publishing_transport == "safari" and result != "attempted":
            from ..guards.active_hours import may_act
            if may_act() and store.meta("next_browser_read", 0) <= now:
                from .startup import waiting_reason
                # Explicit video-first startup already holds interactions. Finish
                # its bounded reads promptly; ordinary running keeps Reply gaps.
                delay = 2 if waiting_reason(store) else 30
                store.set_meta("next_browser_read", now + delay)
                return _x_work(store, cfg, owner, now) or result
        return result
    reason = video_pressure.pressure(store, cfg, now)
    store.set_meta("throttle:" + role, {"reason": reason, "checked_at": now})
    if reason:
        store.heartbeat(role, owner, now, "throttled: " + reason)
        return "throttled"
    if role == "discovery":
        # A failed batch is bounded. A circuit cooldown opens a fresh polling
        # batch later, so repaired providers recover without a bot restart.
        with store.transaction() as db:
            db.execute("UPDATE jobs SET state='pending',attempts=0,due=? WHERE kind='discovery' AND state='dead' AND due<?",
                       (now, now - 3600))
        job = store.claim("discovery", owner, now, cfg)
        if not job:
            return "idle"
        interval = cfg.day_poll_seconds if schedule.eligible(schedule.utc_now()) else cfg.night_poll_seconds
        try:
            result = connectors.discover(store, job["item"], now, cfg)
            store.finish(job, time.time(), repeat=interval)
            return result
        except Deferred as exc:
            store.finish(job, time.time(), repeat=exc.retry_after)
            return "source deferred"
        except Exception as exc:
            store.finish(job, time.time(), error=type(exc).__name__)
            return "source failed"
    # Alternate media preparation and API checks. A growing download queue must
    # not starve history import, positive reconciliation, novelty or due outcomes.
    inspection_job = store.claim("inspect_source", owner, now, cfg)
    if inspection_job:
        from dataclasses import replace
        from pathlib import Path
        from .security import sha256
        row = store.candidate(inspection_job["item"])
        if row["state"] in ("posted", "reserved", "rejected", "duplicate"):
            store.finish(inspection_job, now)
            return "closed source inspection"
        store.heartbeat(role, owner, now, "inspecting:" + inspection_job["item"])
        try:
            doc = row["document"]
            if not ranking.selected(doc, now):
                raise ValueError("explicit local inspection selection expired")
            original = Path(doc["original_path"])
            if sha256(original) != doc["original_sha256"]:
                raise ValueError("selected original changed")
            # One two-minute clip can need more than the automatic 180-second
            # default. Keep the existing maximum and shared quota/resource gates.
            inspect_cfg = replace(cfg, codex_timeout_seconds=max(cfg.codex_timeout_seconds, 300))
            media._job_deadline = time.monotonic() + cfg.media_job_seconds
            evidence = media.inspect(original, "source", inspect_cfg, store, now)
            if evidence.get("sha256") != doc["original_sha256"] or sha256(original) != doc["original_sha256"]:
                raise ValueError("inspection does not match selected original")
            latest = store.candidate(row["id"])
            if latest["state"] in ("posted", "reserved", "rejected", "duplicate"):
                store.finish(inspection_job, time.time())
                return "closed source inspection"
            doc = latest["document"] | {"inspection": evidence}
            reason = ranking.gate(doc, cfg, time.time())
            if not evidence.get("overlays_removable_by_crop"):
                reason = reason or "source overlays need an available clean original or cleanup method"
            store.save_candidate(row["id"], doc, time.time(), state="held",
                                 reason=reason or "source verified; output preparation pending", job=inspection_job)
            if evidence.get("confidence", 0) >= cfg.confidence_min and evidence.get("audio_inspected"):
                store.enqueue("novelty", row["id"], time.time())
            if not reason:
                store.enqueue("media", row["id"], time.time())
            store.finish(inspection_job, time.time())
            return "selected source inspected"
        except Deferred as exc:
            store.finish(inspection_job, time.time(), repeat=exc.retry_after)
            return "source inspection deferred"
        except Exception as exc:
            store.finish(inspection_job, time.time(), error=type(exc).__name__)
            return "source inspection failed"
        finally:
            media._job_deadline = None
    if cfg.publishing_transport == "safari" and store.meta("prefer_x_media", True):
        if _x_media_work(store, cfg, owner, now):
            store.set_meta("prefer_x_media", False)
            return "browser media fingerprinted"
    store.set_meta("prefer_x_media", True)
    api_due = (not store.meta("history_import_complete", False) or store.meta("prefer_api", True)
               or (store.meta("next_reconciliation", 0) <= now and
                   store.rows("SELECT 1 FROM reservations WHERE state='publish_unknown'")))
    if api_due:
        store.set_meta("prefer_api", False)
        outcome = _api_work(store, cfg, owner, now)
        if outcome:
            return outcome
    ready = store.rows("SELECT COUNT(*) AS n FROM candidates WHERE state='ready'")[0]["n"]
    job = store.claim("media", owner, now, cfg) if ready < cfg.buffer_target else None
    if job:
        store.set_meta("prefer_api", True)
        store.heartbeat(role, owner, now, "processing:" + job["item"])
        try:
            media.process(store, job, now, cfg)
            store.finish(job, time.time())
            return "processed"
        except Deferred as exc:
            store.finish(job, time.time(), repeat=exc.retry_after)
            return "media deferred"
        except Exception as exc:
            store.finish(job, time.time(), error=type(exc).__name__)
            return "media failed"
    outcome = _api_work(store, cfg, owner, now)
    if outcome:
        return outcome
    # Refresh ranking without inventing additional observations.
    for row in store.rows("SELECT id FROM candidates WHERE state IN ('ready','held') LIMIT 80"):
        row = store.candidate(row["id"])
        if row["document"].get("qc"):
            doc = ranking.refresh(store, row, now, cfg)
            why = ranking.gate(doc, cfg, now, final=True)
            import json
            store.save_candidate(row["id"], doc, now, state="held" if why else "ready", reason=why,
                                 score=doc["ranking"]["total"], fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
    return "idle"


def _x_media_work(store, cfg, owner, now):
    job = store.claim("x_media", owner, now, cfg)
    if not job:
        return False
    try:
        source = store.meta("x_media:" + job["item"])
        result = reconcile.media_fingerprint(source, store, cfg, now, offload=False)
        with store.transaction() as db:
            if not db.execute("SELECT 1 FROM jobs WHERE id=? AND token=? AND state='running' AND lease>=?",
                              (job["id"], job["token"], time.time())).fetchone():
                raise ValueError("history fingerprint job lost its lease")
            store.put_meta(db, "x_fingerprint:" + job["item"], result)
        store.finish(job, time.time())
    except Exception as exc:
        store.finish(job, time.time(), error=type(exc).__name__)
    return True


def _api_work(store, cfg, owner, now):
    # Safari work belongs to the publisher's existing scheduler executor, which
    # shares the Reply engine's in-process Safari lock. Media stays independent.
    if cfg.publishing_transport == "safari":
        return None
    return _x_work(store, cfg, owner, now)


def _x_work(store, cfg, owner, now):
    if cfg.publishing_transport == "safari":
        from ..x.safari_video import SafariVideoClient
        client = SafariVideoClient(store, cfg)
        circuit = "x_browser"
    else:
        if not cfg.x_reads_enabled:
            return None
        from ..x.video_client import XClient
        client = XClient(store, cfg)
        circuit = "x"
    if not store.circuit_ready(circuit, now):
        return None
    try:
        if cfg.publishing_transport == "safari":
            client.preflight(force=False)
            store.set_meta("account_verified", True)
            from .source_browser import capture_next
            if capture_next(store, cfg, now):
                return "source player checked"
        if not store.meta("history_import_complete", False):
            reconcile.import_history(store, client, cfg, now)
            return "history page imported"
        if store.meta("next_reconciliation", 0) <= now:
            reconcile.reconcile_unknown(store, client, now)
            store.set_meta("next_reconciliation", now + 300)
        if store.meta("next_outcomes", 0) <= now:
            reconcile.collect_outcomes(store, client, now)
            store.set_meta("next_outcomes", now + 1200)
        job = store.claim("novelty", owner, now, cfg)
        if job:
            try:
                candidate = store.candidate(job["item"])
                if candidate["state"] in ("posted", "reserved", "rejected", "expired", "duplicate"):
                    store.finish(job, now)
                    return "closed novelty job"
                reconcile.novelty(store, candidate, client, cfg, now)
                store.finish(job, time.time(), repeat=12 * 3600)
            except Deferred as exc:
                store.finish(job, time.time(), repeat=exc.retry_after)
            except Exception as exc:
                store.finish(job, time.time(), error=type(exc).__name__)
            return "novelty checked"
    except Deferred as exc:
        store.event(now, "x_read_pending", "publisher", str(exc))
        return "browser history/novelty pending"
    except Exception as exc:
        store.event(now, "x_read_failed", "media", type(exc).__name__)
        store.circuit(circuit, now, failed=True, retry_after=getattr(exc, "retry_after", 0))
    return None


def run(role, *, once=False):
    if not config.enabled():
        raise ValueError("VIDEO_ENABLED=1 is required to start video workers")
    state_store.require_migrated()
    cfg, store = config.load(), Store()
    if role == "publisher" and cfg.publishing_transport == "safari":
        raise ValueError("Safari publishing runs in main.py's dedicated scheduler worker, sharing the Reply browser lock")
    owner = f"{os.getpid()}:{uuid.uuid4().hex}"
    stop = threading.Event()
    def shutdown(*args):
        from ..guards.active_hours import request_stop
        request_stop()
        stop.set()
        media.cancel_active()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    with role_lock(role):
        seed_jobs(store, cfg, time.time())
        while not stop.is_set():
            try:
                outcome = run_once(role, store, cfg, owner)
                if role == "discovery":
                    if schedule.local(schedule.utc_now()).hour >= 23:
                        operations.daily_report(store, cfg)
                    operations.cleanup(store, cfg, time.time())
                if outcome == "shutdown":
                    return
                store.heartbeat(role, owner, time.time(), outcome)
            except Exception as exc:
                # Provider text is untrusted, sometimes credential-bearing; log class only.
                log.warning("[VIDEO] %s worker tick failed (%s)", role, type(exc).__name__)
            if once:
                return
            stop.wait(2 if role == "publisher" else 5)


class Supervisor:
    """Existing scheduler process supervises children; boots never create startup requests."""
    def __init__(self):
        self.children = {}
        self.next_start = {}
        self.browser_role = None
        self._claim_browser_role()

    def _claim_browser_role(self):
        if config.load().publishing_transport == "safari" and self.browser_role is None:
            self.browser_role = role_lock("publisher")
            self.browser_role.__enter__()

    def tick(self):
        if not config.enabled():
            return
        store = Store()
        if store.meta("shutdown", False):
            self.stop()
            return
        self._claim_browser_role()
        for role in ROLES:
            if role == "publisher" and config.load().publishing_transport == "safari":
                continue
            child = self.children.get(role)
            if child and child.poll() is None:
                continue
            if time.monotonic() < self.next_start.get(role, 0):
                continue
            lock_path = state_store.StatePath("video_" + role + ".lock")
            if Path(str(lock_path)).exists():
                with open(lock_path) as handle:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue  # independently supervised worker already owns this role
            script = Path(settings.PROJECT_ROOT).resolve() / "bin" / "video.py"
            self.children[role] = subprocess.Popen([sys.executable, str(script), "worker", role], start_new_session=True)
            self.next_start[role] = time.monotonic() + 30

    def stop(self):
        for child in self.children.values():
            if child.poll() is None:
                child.terminate()
        for child in self.children.values():
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Killing the process group also stops bounded renders/providers.
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        self.children.clear()
        if self.browser_role is not None:
            self.browser_role.__exit__(None, None, None)
            self.browser_role = None


def health_job():
    if config.enabled():
        store, cfg = Store(), config.load()
        if cfg.publishing_transport == "safari":
            return run_once("publisher", store, cfg, f"{os.getpid()}:scheduler")
        stale = [r["role"] for r in store.rows("SELECT * FROM workers") if time.time() - r["heartbeat"] > cfg.lease_seconds]
        if stale:
            log.warning("[VIDEO] Stale worker heartbeats: %s", ", ".join(stale))


def record_main_mode():
    if config.enabled():
        Store().set_meta("main_profile_owner", {"pid": os.getpid(), "video_enabled": True, "heartbeat": time.time()})


def stop_feature_workers(store):
    """Explicit CLI shutdown only: signal verified video processes, never the Reply bot."""
    import psutil
    script = (Path(settings.PROJECT_ROOT).resolve() / "bin" / "video.py").resolve()
    stopped = []
    for row in store.rows("SELECT role,owner FROM workers"):
        if row["role"] not in ROLES:
            continue
        try:
            pid = int(row["owner"].split(":", 1)[0])
            process = psutil.Process(pid)
            args = process.cmdline()
            has_script = any(arg.endswith("video.py") and Path(arg).resolve() == script for arg in args)
            if has_script and args[-2:] == ["worker", row["role"]]:
                process.terminate()
                stopped.append(pid)
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return stopped
