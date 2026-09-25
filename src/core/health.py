"""Health watchdog: detect stuck Safari and recover.

The whole stack runs through Safari + AppleScript. If Safari hangs (memory
pressure, redirect loop, OS update, captive portal), every cycle silently
errors and the bot looks alive but accomplishes nothing. This module:

  1. Counts consecutive cycle failures across the whole bot (process-wide,
     persisted so a restart doesn't lose context).
  2. After RECOVERY_THRESHOLD failures in a row, force-quits Safari and
     reopens a fresh window — usually clears whatever wedged it.
  3. Writes a single-line flag into autonomous_log.md when recovery fires
     so the user sees it on return.

The counter resets on any successful cycle. By design this is per-bot
(across reply / engage / post / etc.) — three failed cycles in a row from
ANY mix of bots is the trigger, since they all share Safari.
"""
import os
import sys
import time
from datetime import datetime
from functools import wraps
from .config import _PROJECT_ROOT
from .logger import log
from .state_errors import StateUnreadable
from .state_store import DISPOSABLE, StateFile
from ..guards.active_hours import OutsideActiveHours

HEALTH = StateFile("safari_health.json",
                   {"consecutive_failures": 0, "last_recovery_ts": 0, "total_recoveries": 0},
                   DISPOSABLE)
AUTONOMOUS_LOG_FILE = os.path.join(_PROJECT_ROOT, "autonomous_log.md")

RECOVERY_THRESHOLD = 3      # consecutive cycle failures before we restart
COOLDOWN_SECONDS = 600      # don't restart Safari more than once per 10 min


def record_success(label: str = ""):
    """Reset the failure counter. Call from any cycle that completed normally."""
    def reset(data):
        if data.get("consecutive_failures", 0) > 0:
            log.info(f"[HEALTH] {label or 'cycle'} OK — resetting failure counter (was {data['consecutive_failures']}).")
        data["consecutive_failures"] = 0
        return data
    HEALTH.update(reset)


def wrap_job(run, label: str, *, safari_health: bool = True):
    """The scheduler's wrapper around a job's `run_*`: it never raises.

    An error is logged at ERROR with its traceback in bot.log. A job with
    `safari_health` resets the failure counter on success and hands its
    error to `record_failure`; without it, the job never touches the
    health file. StateUnreadable and OutsideActiveHours are never failures.
    """
    @wraps(run)
    def job():
        try:
            run()
        except Exception as exc:
            if _not_a_failure(label, exc, safari_health):
                return
            log.exception(f"[{label}] Cycle failed.")
            if safari_health:
                record_failure(label, exc)
            return
        if safari_health:
            record_success(label)
    return job


def _not_a_failure(label: str, exc: BaseException | None, safari_health: bool) -> bool:
    """Log a StateUnreadable or an OutsideActiveHours, never a cycle failure,
    and say whether `exc` was one. Only a job with `safari_health` is told
    that Safari is not restarted."""
    if isinstance(exc, OutsideActiveHours):
        say, event, advice = log.info, "stopped for the Overnight", ""
    elif isinstance(exc, StateUnreadable):
        say, event = log.error, f"halted: {exc}"
        advice = " Repair the file (docs/OPERATIONS.md#recovery)."
    else:
        return False
    if safari_health:
        say(f"[HEALTH] {label} {event}. Not a Safari failure, no restart.{advice}")
    else:
        say(f"[{label}] {event}.{advice}")
    return True


def record_failure(label: str = "", exc: BaseException | None = None) -> bool:
    """Increment the failure counter. Returns True if recovery was triggered.

    Recovery = quit + relaunch Safari. Idempotent and rate-limited via
    COOLDOWN_SECONDS so a flapping bot doesn't bounce Safari in a loop.

    `exc` is the cycle's error: a StateUnreadable or an OutsideActiveHours is
    logged and not counted. Without it, the error in flight is read, for the
    `safe_run_*` still calling it from their `except` block (#234).
    """
    if exc is None:
        exc = sys.exc_info()[1]
    if _not_a_failure(label or "cycle", exc, safari_health=True):
        return False
    claimed = []

    def count(data):
        data["consecutive_failures"] = data.get("consecutive_failures", 0) + 1
        log.info(f"[HEALTH] {label or 'cycle'} FAILED — consecutive = {data['consecutive_failures']}.")
        if data["consecutive_failures"] < RECOVERY_THRESHOLD:
            return data
        now = time.time()
        if now - data.get("last_recovery_ts", 0) < COOLDOWN_SECONDS:
            log.info(f"[HEALTH] Recovery already fired in last {COOLDOWN_SECONDS}s — skipping.")
            return data
        # Claimed before the restart, which runs outside the lock: a second
        # failing thread meanwhile finds the cooldown and skips.
        data["last_recovery_ts"] = now
        data["total_recoveries"] = data.get("total_recoveries", 0) + 1
        claimed.append(data["total_recoveries"])
        return data
    HEALTH.update(count)
    if not claimed:
        return False

    log.warning(f"[HEALTH] {RECOVERY_THRESHOLD}+ consecutive failures — restarting Safari.")
    ok = _restart_safari()
    if ok:
        # Reset on successful recovery so the next cycle starts clean.
        HEALTH.update(lambda data: {**data, "consecutive_failures": 0})
    _append_autonomous_flag(label, claimed[0], ok)
    return ok


def _restart_safari() -> bool:
    """Force-quit Safari and reopen a fresh window. Best-effort, never raises.

    Delegates to safari_hygiene.restart_safari which also force-kills
    lingering WebKit helper processes (graceful quit sometimes leaves them
    holding network state). Cookies / localStorage survive — login persists.
    """
    try:
        from ..x import safari_hygiene
        return safari_hygiene.restart_safari(reason="health_recovery")
    except Exception as e:
        log.warning(f"[HEALTH] Safari restart failed: {e}")
        return False


def _append_autonomous_flag(label: str, total_recoveries: int, ok: bool):
    """Write a one-line marker into autonomous_log.md so the user sees it
    in the daily review without trawling bot.log."""
    try:
        line = (
            f"\n- {datetime.now().isoformat(timespec='minutes')} "
            f"⚠️ HEALTH: Safari recovery #{total_recoveries} "
            f"after consecutive failures (trigger={label}, success={ok}).\n"
        )
        with open(AUTONOMOUS_LOG_FILE, "a") as f:
            f.write(line)
    except IOError:
        pass
