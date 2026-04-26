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
import json
import os
import subprocess
import time
from datetime import datetime
from .config import _PROJECT_ROOT
from .logger import log

HEALTH_FILE = os.path.join(_PROJECT_ROOT, "safari_health.json")
AUTONOMOUS_LOG_FILE = os.path.join(_PROJECT_ROOT, "autonomous_log.md")

RECOVERY_THRESHOLD = 3      # consecutive cycle failures before we restart
COOLDOWN_SECONDS = 600      # don't restart Safari more than once per 10 min


def _load() -> dict:
    if not os.path.exists(HEALTH_FILE):
        return {"consecutive_failures": 0, "last_recovery_ts": 0, "total_recoveries": 0}
    try:
        with open(HEALTH_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"consecutive_failures": 0, "last_recovery_ts": 0, "total_recoveries": 0}


def _save(data: dict):
    try:
        with open(HEALTH_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError:
        pass


def record_success(label: str = ""):
    """Reset the failure counter. Call from any cycle that completed normally."""
    data = _load()
    if data.get("consecutive_failures", 0) > 0:
        log.info(f"[HEALTH] {label or 'cycle'} OK — resetting failure counter (was {data['consecutive_failures']}).")
    data["consecutive_failures"] = 0
    _save(data)


def record_failure(label: str = "") -> bool:
    """Increment the failure counter. Returns True if recovery was triggered.

    Recovery = quit + relaunch Safari. Idempotent and rate-limited via
    COOLDOWN_SECONDS so a flapping bot doesn't bounce Safari in a loop.
    """
    data = _load()
    data["consecutive_failures"] = data.get("consecutive_failures", 0) + 1
    log.info(f"[HEALTH] {label or 'cycle'} FAILED — consecutive = {data['consecutive_failures']}.")

    if data["consecutive_failures"] < RECOVERY_THRESHOLD:
        _save(data)
        return False

    now = time.time()
    if now - data.get("last_recovery_ts", 0) < COOLDOWN_SECONDS:
        log.info(f"[HEALTH] Recovery already fired in last {COOLDOWN_SECONDS}s — skipping.")
        _save(data)
        return False

    log.warning(f"[HEALTH] {RECOVERY_THRESHOLD}+ consecutive failures — restarting Safari.")
    ok = _restart_safari()
    data["last_recovery_ts"] = now
    data["total_recoveries"] = data.get("total_recoveries", 0) + 1
    if ok:
        # Reset on successful recovery so the next cycle starts clean.
        data["consecutive_failures"] = 0
    _save(data)
    _append_autonomous_flag(label, data["total_recoveries"], ok)
    return ok


def _restart_safari() -> bool:
    """Force-quit Safari and reopen a fresh window. Best-effort, never raises."""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to quit'],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(2)
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to activate'],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(2)
        log.info("[HEALTH] Safari restarted.")
        return True
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
