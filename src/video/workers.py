"""Independent processes; overnight discovery/media never enter Safari or Reply queues."""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

from ..core import settings, state_store, video_pressure
from ..core.logger import log
from ..guards.active_hours import OutsideActiveHours
from . import config, connectors, media, operations, publisher, ranking, reconcile, schedule
from .store import Store
from .security import Deferred

ROLES = ("discovery", "media", "publisher")
_ROLE_HOLDERS = {}


def runtime_generation(cfg):
    """Fingerprint the loaded configuration and startup code, never record secrets."""
    root = Path(settings.PROJECT_ROOT).resolve()
    account = settings.get("BOT_ACCOUNT")
    config_path = Path(settings.get("VIDEO_CONFIG_FILE") or root / "accounts" / account / "video.toml").resolve()
    paths = sorted(set((root / "src").rglob("*.py")) | {
        root / "bin" / "video.py", root / "bin" / "video_av_probe.swift",
        root / "requirements.txt", root / "requirements-video.txt", root / "accounts" / account / "account.toml", config_path}
        | {Path(path) for path in (cfg.discovery_prompt_file, cfg.discovery_memory_file, cfg.query_bank_file) if path})
    effective = {key: settings.get(key) for key in settings.DECLARED}
    digest = hashlib.sha256(json.dumps({"config": asdict(cfg), "settings": effective,
        "python": sys.version, "executable": sys.executable}, sort_keys=True, ensure_ascii=False).encode())
    latest = settings.source_modified_at()
    for path in paths:
        if path.is_file():
            digest.update(str(path).encode())
            digest.update(path.read_bytes())
            latest = max(latest, path.stat().st_mtime)
    return {"fingerprint": digest.hexdigest(), "files_modified_at": latest,
            "project_root": str(root), "state_root": str(Path(state_store.root()).resolve())}


def record_worker_runtime(store, role, owner, cfg):
    import psutil
    runtime = runtime_generation(cfg) | {"owner": owner, "pid": os.getpid(),
        "process_started_at": psutil.Process(os.getpid()).create_time()}
    with store.transaction() as db:
        store.put_meta(db, "worker_runtime:" + role, runtime)
        db.execute("INSERT INTO workers VALUES(?,?,?,'starting') ON CONFLICT(role) DO UPDATE SET "
                   "owner=excluded.owner,heartbeat=excluded.heartbeat,detail=excluded.detail",
                   (role, owner, time.time()))


def verified_role_process(role, lock_path):
    """A PID in a file is insufficient: verify process identity and the open lock."""
    import psutil
    if role not in ("discovery", "media"):
        return None
    try:
        raw = lock_path.read_text().strip()
        if not raw.isdigit() or int(raw) == os.getpid():
            return None
        process = psutil.Process(int(raw))
        args = process.cmdline()
        script = (Path(settings.PROJECT_ROOT).resolve() / "bin" / "video.py").resolve()
        cwd = Path(process.cwd())
        scripts = [Path(arg) if Path(arg).is_absolute() else cwd / arg for arg in args if arg.endswith("video.py")]
        if args[-2:] != ["worker", role] or not any(path.resolve() == script for path in scripts):
            return None
        if not any(Path(item.path).resolve() == lock_path.resolve() for item in process.open_files()):
            return None
        # Recheck after process inspection in case ownership changed meanwhile.
        if lock_path.read_text().strip() != raw:
            return None
        return process
    except (OSError, ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
        return None


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


def _scheduler_owner_absent(owner):
    """Signal zero checks existence only; any extant/reused/unknown PID stays."""
    if not isinstance(owner, str):
        return False
    match = re.fullmatch(r"([1-9][0-9]{0,9}):scheduler", owner)
    if not match or int(match[1]) == os.getpid():
        return False
    try:
        os.kill(int(match[1]), 0)
    except ProcessLookupError:
        return True
    except (OSError, OverflowError):
        return False
    return False


def recover_orphaned_novelty_reads(store, now):
    """Recover only read jobs after the new sole Safari publisher owns its role."""
    if not owns_role("publisher"):
        return 0
    recovered = 0
    for job in store.rows("SELECT id,item,owner,token,attempts FROM jobs WHERE kind='novelty' AND state='running'"):
        if not job["token"] or not _scheduler_owner_absent(job["owner"]):
            continue
        with store.transaction() as db:
            # Recheck process existence under the DB write lock, then fence the
            # exact abandoned claim. A successor token or live PID is untouched.
            if not owns_role("publisher") or not _scheduler_owner_absent(job["owner"]):
                continue
            changed = db.execute("UPDATE jobs SET state='pending',due=?,owner=NULL,lease=NULL,token=NULL,"
                "attempts=MAX(0,attempts-1) WHERE id=? AND kind='novelty' AND state='running' "
                "AND owner=? AND token=? AND attempts=?",
                (now, job["id"], job["owner"], job["token"], job["attempts"])).rowcount
            if changed:
                detail = json.dumps({"previous_owner": job["owner"], "job_id": job["id"],
                                     "refunded_attempt": min(1, job["attempts"])})
                db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,?,?,?)",
                           (now, "novelty_read_recovered", job["item"], detail))
                recovered += 1
    return recovered


def seed_jobs(store, cfg, now):
    for platform in (cfg.platforms or dict.fromkeys(config.PLATFORMS)):
        if cfg.platforms.get(platform, {}).get("enabled", True):
            store.enqueue("discovery", platform, now)


def run_once(role, store, cfg, owner, *, now=None):
    now = now if now is not None else time.time()
    if store.meta("shutdown", False):
        return "shutdown"
    store.heartbeat(role, owner, now)
    if role in ("publisher", "discovery"):
        from .preparation import maintain_reserve
        maintain_reserve(store, cfg, now)
    if role == "publisher":
        # Publishing keeps its reserved request budget under discovery/media load.
        from .startup import tick
        from .preparation import prepare_upcoming
        prepare_upcoming(store, cfg, now)
        tick(store, cfg, now)
        result = publisher.publish_tick(store, cfg)
        if cfg.publishing_transport == "safari" and result != "attempted":
            upcoming = schedule.next_slot(schedule.utc_now(), cfg)
            if (upcoming and 0 <= upcoming[1].timestamp() - now <= 180
                    and store.rows("SELECT 1 FROM candidates WHERE state='ready' LIMIT 1")
                    and not store.rows("SELECT 1 FROM reservations WHERE state='publish_unknown'")):
                # Leave this scheduler free to reserve/upload when the clock
                # turns. A routine archive read must not straddle a ready slot.
                return result
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
    output_job = store.claim("inspect_output", owner, now, cfg)
    if output_job:
        store.heartbeat(role, owner, now, "reviewing_output:" + output_job["item"])
        try:
            media.review_output(store, output_job, now, cfg)
            store.finish(output_job, time.time())
            return "saved output reviewed"
        except Deferred as exc:
            store.finish(output_job, time.time(), repeat=exc.retry_after)
            return "saved output review deferred"
        except Exception as exc:
            store.finish(output_job, time.time(), error=type(exc).__name__)
            return "saved output review failed"
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
            evidence = media.inspect(original, "source", inspect_cfg, store, now, source_document=doc)
            if evidence.get("sha256") != doc["original_sha256"] or sha256(original) != doc["original_sha256"]:
                raise ValueError("inspection does not match selected original")
            latest = store.candidate(row["id"])
            if latest["state"] in ("posted", "reserved", "rejected", "duplicate"):
                store.finish(inspection_job, time.time())
                return "closed source inspection"
            doc = latest["document"] | {"inspection": evidence}
            reason = ranking.gate(doc, cfg, time.time())
            if not evidence.get("overlays_removable_by_crop") and not cfg.allow_source_overlays:
                reason = reason or "source overlays need an available clean original or cleanup method"
            store.save_candidate(row["id"], doc, time.time(), state="held",
                                 reason=reason or "source verified; output preparation pending",
                                 fingerprint=json.loads(latest["fingerprint"]) if latest["fingerprint"] else None,
                                 job=inspection_job)
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
            store.save_candidate(row["id"], doc, now, state="held" if why else "ready", reason=why,
                                 score=doc["ranking"]["total"], fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
    return "idle"


def _x_media_work(store, cfg, owner, now):
    job = store.claim("x_media", owner, now, cfg)
    if not job:
        return False
    try:
        media._job_deadline = time.monotonic() + cfg.media_job_seconds
        source = store.meta("x_media:" + job["item"])
        result = reconcile.media_fingerprint(source, store, cfg, now, offload=False)
        with store.transaction() as db:
            if not db.execute("SELECT 1 FROM jobs WHERE id=? AND token=? AND state='running' AND lease>=?",
                              (job["id"], job["token"], time.time())).fetchone():
                raise ValueError("history fingerprint job lost its lease")
            store.put_meta(db, "x_fingerprint:" + job["item"], result)
        store.finish(job, time.time())
    except Deferred as exc:
        store.finish(job, time.time(), repeat=exc.retry_after)
    except Exception as exc:
        store.finish(job, time.time(), error=type(exc).__name__)
    finally:
        media._job_deadline = None
    return True


def _api_work(store, cfg, owner, now):
    # Safari work belongs to the publisher's existing scheduler executor, which
    # shares the Reply engine's in-process Safari lock. Media stays independent.
    if cfg.publishing_transport == "safari":
        return None
    return _x_work(store, cfg, owner, now)


def _read_failure(store, stage, exc, now):
    """Local failure reasons only; never echo provider text, page data or URLs."""
    from .security import AccessError
    reasons = (
        "Safari could not open X", "Safari login/account could not be verified",
        "Safari did not return readable page evidence", "browser read budget exhausted",
        "browser fingerprint read budget exhausted", "Safari page failed to open",
        "X page unavailable or rate limited", "unreadable X page is not an empty search",
        "native video bytes are not accessible through the selected X transport",
        "history/novelty media download budget exhausted",
        "history contains inaccessible media; export or restore access before live selection",
        "native video duration unavailable", "X video frames are not readable under browser origin policy",
        "blank/static video frames cannot establish a sequence fingerprint", "exact status metrics unavailable",
    )
    reason = str(exc) if isinstance(exc, AccessError) and str(exc) in reasons else type(exc).__name__
    store.event(now, "x_read_failed", stage, reason)
    log.warning("[VIDEO] Browser %s failed: %s", stage, reason)
    return reason


def _shared_read_failure(exc):
    """Account-wide denial and provider retry instructions still stop every lane."""
    from .security import AccessError
    return isinstance(exc, AccessError) and (
        exc.status in (401, 403, 429) or exc.retry_after > 0
        or str(exc) in ("Safari login/account could not be verified", "X page unavailable or rate limited"))


def _x_work(store, cfg, owner, now):
    from ..core import work_priority
    upcoming = schedule.next_slot(schedule.utc_now(), cfg)
    imminent = bool(upcoming and 0 <= upcoming[1].timestamp() - now <= cfg.preparation_lead_seconds)
    startup_due = bool(store.rows("SELECT 1 FROM startup WHERE state='pending' LIMIT 1"))
    initial_history = not reconcile.history_ready(store, cfg)
    reserve_low = store.rows("SELECT COUNT(*) AS n FROM candidates WHERE state='ready'")[0]["n"] < cfg.buffer_target
    priority = work_priority.REPLY if imminent or startup_due or initial_history or reserve_low else work_priority.BACKGROUND
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
    stage = "preflight"
    try:
        if cfg.publishing_transport == "safari":
            with work_priority.scope(priority):
                client.preflight(force=False)
            store.set_meta("account_verified", True)
            store.circuit(circuit, now, failed=False)
        client.critical_reads = True
        stage = "reconciliation"
        if store.meta("next_reconciliation", 0) <= now and store.circuit_ready(circuit + ":" + stage, now):
            with work_priority.scope(work_priority.REPLY):
                reconcile.reconcile_unknown(store, client, now)
            store.circuit(circuit + ":" + stage, now, failed=False)
            store.set_meta("next_reconciliation", now + 300)
        # A stalled duplicate check must not consume every preparation turn.
        # Publishing/reconciliation have already had first access; after two
        # novelty batches give the independent source queue one bounded read.
        if (cfg.publishing_transport == "safari" and reserve_low
                and store.meta("novelty_reads_since_source", 0) >= 2
                and store.circuit_ready(circuit + ":source", now)):
            stage = "source"
            store.set_meta("novelty_reads_since_source", 0)
            from .source_browser import capture_next
            with work_priority.scope(priority):
                captured = capture_next(store, cfg, now)
            if captured:
                store.circuit(circuit + ":source", now, failed=False)
                return "source player checked"
        stage = "novelty"
        job = store.claim("novelty", owner, now, cfg)
        if job:
            try:
                candidate = store.candidate(job["item"])
                if store.rows("SELECT 1 FROM jobs WHERE item=? AND kind IN ('media','inspect_source','inspect_output') "
                              "AND state='running'", (job["item"],)):
                    store.finish(job, time.time(), repeat=15)
                    return "media preparation pending"
                if candidate["state"] in ("posted", "reserved", "rejected", "expired", "duplicate"):
                    store.finish(job, now)
                    return "closed novelty job"
                with work_priority.scope(priority):
                    reconcile.novelty(store, candidate, client, cfg, now)
                store.circuit(circuit + ":" + stage, now, failed=False)
                store.finish(job, time.time(), repeat=12 * 3600)
            except Deferred as exc:
                store.finish(job, time.time(), repeat=exc.retry_after)
            except OutsideActiveHours:
                store.finish(job, time.time(), repeat=30)
                return "interaction cooldown"
            except Exception as exc:
                detail = _read_failure(store, stage, exc, now)
                if _shared_read_failure(exc):
                    store.circuit(circuit, now, failed=True, retry_after=exc.retry_after)
                store.finish(job, time.time(), error=detail)
            finally:
                store.set_meta("novelty_reads_since_source", store.meta("novelty_reads_since_source", 0) + 1)
            return "novelty checked"
        client.critical_reads = False
        stage = "source"
        if cfg.publishing_transport == "safari" and store.circuit_ready(circuit + ":" + stage, now):
            store.set_meta("novelty_reads_since_source", 0)
            from .source_browser import capture_next
            with work_priority.scope(priority):
                captured = capture_next(store, cfg, now)
            if captured:
                store.circuit(circuit + ":" + stage, now, failed=False)
                return "source player checked"
        stage = "history"
        if not store.meta("history_import_complete", False) and store.circuit_ready(circuit + ":" + stage, now):
            if not reconcile.history_ready(store, cfg) or store.meta("next_history_backfill", 0) <= now:
                store.set_meta("next_history_backfill", now + 300)
                with work_priority.scope(priority if initial_history else work_priority.BACKGROUND):
                    reconcile.import_history(store, client, cfg, now)
                store.circuit(circuit + ":" + stage, now, failed=False)
                return "history page imported"
        stage = "outcomes"
        if store.meta("next_outcomes", 0) <= now and store.circuit_ready(circuit + ":" + stage, now):
            reconcile.collect_outcomes(store, client, now)
            store.circuit(circuit + ":" + stage, now, failed=False)
            store.set_meta("next_outcomes", now + 1200)
    except Deferred as exc:
        store.event(now, "x_read_pending", "publisher", str(exc))
        return "browser history/novelty pending"
    except OutsideActiveHours:
        return "interaction cooldown"
    except Exception as exc:
        _read_failure(store, stage, exc, now)
        # Login/read admission failures apply globally. An inaccessible archive
        # clip or optional metrics page must never disable novelty/reconciliation.
        failed_circuit = circuit if stage == "preflight" or _shared_read_failure(exc) else circuit + ":" + stage
        store.circuit(failed_circuit, now, failed=True, retry_after=getattr(exc, "retry_after", 0))
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
        record_worker_runtime(store, role, owner, cfg)
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
        self.retiring = {}
        self.runtime = runtime_generation(config.load())
        self.browser_role = None
        self._claim_browser_role()

    def _claim_browser_role(self):
        if config.load().publishing_transport == "safari" and self.browser_role is None:
            self.browser_role = role_lock("publisher")
            self.browser_role.__enter__()
            try:
                recover_orphaned_novelty_reads(Store(), time.time())
            except Exception as exc:
                # Read recovery cannot prevent Reply startup. Failed checks
                # leave the fenced lease to its ordinary expiration path.
                log.warning("[VIDEO] Orphaned novelty read recovery deferred (%s).", type(exc).__name__)

    def _handover_stale_worker(self, store, role, lock_path):
        """Retire only a verified old media/discovery process; leave its leases fenced."""
        import psutil
        process = verified_role_process(role, lock_path)
        if process is None:
            return
        try:
            started = process.create_time()
            previous = store.meta("worker_runtime:" + role, {})
            matching = (previous.get("pid") == process.pid
                        and previous.get("process_started_at") == started
                        and previous.get("project_root") == self.runtime["project_root"]
                        and previous.get("state_root") == self.runtime["state_root"])
            if matching:
                obsolete = previous.get("fingerprint") != self.runtime["fingerprint"]
            elif previous:
                return  # mismatched/reused PID metadata is not proven ownership
            else:
                # Upgrade legacy workers only on positive evidence of a code/
                # config update since their start. Unknown new processes stay.
                obsolete = started < self.runtime["files_modified_at"]
            if not obsolete:
                return
            identity = (process.pid, started)
            if self.retiring.get(role) == identity:
                return  # one graceful signal; wait for the actual role lock release
            checked = verified_role_process(role, lock_path)
            if checked is None or checked.pid != process.pid or checked.create_time() != started:
                return
            process.terminate()
            self.retiring[role] = identity
            log.info("[VIDEO] Retiring stale %s worker PID %s; replacement waits for its role lock.", role, process.pid)
            store.event(time.time(), "worker_handover", role, "Verified earlier code/config generation sent SIGTERM; leases and publication claims retained")
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return

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
                        self._handover_stale_worker(store, role, Path(str(lock_path)))
                        continue  # independently supervised worker already owns this role
            script = Path(settings.PROJECT_ROOT).resolve() / "bin" / "video.py"
            self.children[role] = subprocess.Popen([sys.executable, str(script), "worker", role], start_new_session=True)
            self.retiring.pop(role, None)
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
