"""Health watchdog: detect stuck Safari and recover.

The whole stack runs through Safari + AppleScript. If Safari hangs (memory
pressure, redirect loop, OS update, captive portal), every cycle silently
errors and the bot looks alive but accomplishes nothing. This module:

  1. Counts consecutive browser failures across the whole bot (process-wide,
     persisted so a restart doesn't lose context): a cycle counts only when
     its error is a `BrowserFailure`, raised by the browser layer (`src/x`).
     A bug or a model timeout is logged, never counted (issue #298).
  2. After RECOVERY_THRESHOLD failures in a row, asks
     safari_hygiene.restart_safari to force-quit Safari and reopen a fresh
     window — usually clears whatever wedged it. The restart's cooldown is
     the only delay: a refused restart is counted nowhere (issue #302).
  3. Writes a single-line flag into autonomous_log.md when a restart was
     tried, so the user sees it on return.

The counter resets on any successful cycle and after any restart that
succeeded, whichever path asked for it; another failure leaves it as it
was. By design this is per-bot (across reply / engage / post / etc.) —
three browser failures in a row from ANY mix of bots is the trigger, since
they all share Safari.
"""
import math
import os
import time
from datetime import datetime
from functools import wraps
from .config import _PROJECT_ROOT
from .logger import log
from .state_errors import StateUnreadable
from .state_store import DISPOSABLE, StateFile
from ..guards.active_hours import OutsideActiveHours
from ..x import safari_hygiene
from ..x.page_session import BrowserFailure
from ..x.safari_hygiene import RestartOutcome

HEALTH = StateFile("safari_health.json",
                   {"consecutive_failures": 0, "last_recovery_ts": 0, "total_recoveries": 0},
                   DISPOSABLE)
AUTONOMOUS_LOG_FILE = os.path.join(_PROJECT_ROOT, "autonomous_log.md")

RECOVERY_THRESHOLD = 3      # consecutive cycle failures before we restart

# The types each HEALTH field accepts: the two counters are whole numbers,
# the recovery time a timestamp.
FIELD_KINDS = {"consecutive_failures": int, "total_recoveries": int,
               "last_recovery_ts": (int, float)}


def _update(fn):
    """HEALTH.update, with each field checked before `fn` sees it (#303).

    The file is disposable, and valid JSON edited by hand may still hold a
    field that is not a count: a string, null, a list, a boolean, a
    negative number, a fraction for a counter. That field alone goes back
    to its default with a warning naming it; the valid ones are kept."""
    return HEALTH.update(lambda data: fn(_checked(data)))


def _checked(data: dict) -> dict:
    for field, default in HEALTH.default().items():
        value = data.get(field, default)
        # bool is an int to Python; the comparison also refuses NaN and infinity.
        if (isinstance(value, bool) or not isinstance(value, FIELD_KINDS[field])
                or not 0 <= value < math.inf):
            log.warning(f"[HEALTH] {HEALTH.name}: {field} is {value!r}, not a valid "
                        f"value: reset to {default}.")
            value = default
        data[field] = value
    return data


def record_success(label: str = ""):
    """Reset the failure counter. Call from any cycle that completed normally."""
    _reset(f"{label or 'cycle'} OK")


def reset_after_restart(reason: str):
    """Reset the failure counter after a Safari restart that succeeded.
    safari_hygiene.restart_safari calls it, whichever path asked."""
    _reset(f"Safari restarted ({reason})")


def _reset(event: str):
    def reset(data):
        if data["consecutive_failures"] > 0:
            log.info(f"[HEALTH] {event} — resetting failure counter (was {data['consecutive_failures']}).")
        data["consecutive_failures"] = 0
        return data
    _update(reset)


def wrap_job(run, label: str, *, safari_health: bool = True):
    """The scheduler's wrapper around a job's `run_*`: it never raises.

    An error is logged at ERROR with its traceback in bot.log. A job with
    `safari_health` resets the failure counter on success and hands its
    error to `record_failure`, which counts a BrowserFailure only; without
    it, the wrapper never touches the health file. StateUnreadable and
    OutsideActiveHours are never failures.
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


def _not_a_failure(label: str, exc: BaseException, safari_health: bool) -> bool:
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


def record_failure(label: str, exc: BaseException) -> bool:
    """Increment the failure counter. Returns True if Safari was restarted.

    From RECOVERY_THRESHOLD failures in a row, each failure asks
    safari_hygiene.restart_safari for a restart: its cooldown, its lock and
    its waking-hours check decide, so two threads crossing the threshold
    together restart Safari once. A refused restart is counted nowhere; a
    tried one counts in `total_recoveries` and autonomous_log.md, and one
    that succeeded has reset the counter.

    `exc` is the cycle's error, handed by `wrap_job`: only a BrowserFailure
    is counted. A StateUnreadable, an OutsideActiveHours or any other error
    is logged and not counted, and leaves the counter as it was.
    """
    if _not_a_failure(label or "cycle", exc, safari_health=True):
        return False
    if not isinstance(exc, BrowserFailure):
        log.info(f"[HEALTH] {label or 'cycle'} failed outside the browser "
                 f"({type(exc).__name__}). Not a Safari failure, no restart.")
        return False

    def count(data):
        data["consecutive_failures"] += 1
        log.info(f"[HEALTH] {label or 'cycle'} FAILED — consecutive = {data['consecutive_failures']}.")
        return data
    failures = _update(count)["consecutive_failures"]
    if failures < RECOVERY_THRESHOLD:
        return False

    log.info(f"[HEALTH] {failures} consecutive failures — asking for a Safari restart.")
    outcome = _restart_safari()
    if outcome is RestartOutcome.REFUSED:
        log.info("[HEALTH] Safari restart refused — no recovery counted.")
        return False

    def tried(data):
        data["last_recovery_ts"] = time.time()
        data["total_recoveries"] += 1
        return data
    total = _update(tried)["total_recoveries"]
    _append_autonomous_flag(label, total, bool(outcome))
    return bool(outcome)


def _restart_safari() -> RestartOutcome:
    """Force-quit Safari and reopen a fresh window. Best-effort, never raises.

    Delegates to safari_hygiene.restart_safari which also force-kills
    lingering WebKit helper processes (graceful quit sometimes leaves them
    holding network state). Cookies / localStorage survive — login persists.
    """
    try:
        return safari_hygiene.restart_safari(reason="health_recovery")
    except Exception as e:
        log.warning(f"[HEALTH] Safari restart failed: {e}")
        return RestartOutcome.FAILED


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
