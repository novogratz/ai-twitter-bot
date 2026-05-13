"""Safari hygiene — proactive + reactive restart to keep x.com loading.

After a few hours of automation, Safari itself wedges: x.com pages stop
loading, and other tabs (Telegram Web, etc.) also freeze. So it's not an
x.com session-state issue — it's a Safari memory / process-state issue
that takes everything down with it.

Manual fix that works: "Clear History + relogin." The actual mechanism
that fixes it is the implicit Safari restart, not the cookie wipe.

So this module just quits + relaunches Safari, which:
  - Drops every wedged tab (Safari reopens to start page, not last tabs)
  - Releases accumulated memory / network / WebKit process state
  - PRESERVES cookies (file-based in ~/Library/Cookies) so login survives
  - PRESERVES localStorage / IndexedDB (file-based)

Two trigger paths:
  1. Preventive — main.py schedules safe_run_session_refresh() every ~2h
     so we restart BEFORE Safari wedges.
  2. Reactive — health.py calls into this when a cycle fails. Already
     wired through health.record_failure / _restart_safari.

This is intentionally a thin wrapper over the same restart logic that
health.py uses, so callers can request a fresh Safari without going
through the consecutive-failure counter.
"""
import json
import os
import subprocess
import time
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT
from .logger import log

HYGIENE_STATE_FILE = os.path.join(_PROJECT_ROOT, "safari_hygiene_state.json")

# Don't restart Safari more than once in this window. The preventive
# scheduler tick is every ~2h; reactive recovery has its own cooldown
# in health.py. This guards against a flapping bot causing rapid bounces.
MIN_GAP_SECONDS = 30 * 60  # 30 min


def _last_run_ts() -> float:
    if not os.path.exists(HYGIENE_STATE_FILE):
        return 0.0
    try:
        with open(HYGIENE_STATE_FILE, "r") as f:
            return float(json.load(f).get("last_run_ts", 0) or 0)
    except (json.JSONDecodeError, OSError, ValueError):
        return 0.0


def _mark_ran():
    try:
        with open(HYGIENE_STATE_FILE, "w") as f:
            json.dump({
                "last_run": datetime.now().isoformat(),
                "last_run_ts": time.time(),
            }, f)
    except OSError:
        pass


def _quit_safari() -> bool:
    """Quit Safari gracefully, then force-kill if it didn't go down.

    Cookies / localStorage / IndexedDB are file-based so login persists
    across the restart. Only volatile WebKit process state is lost — which
    is the whole point.
    """
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to quit'],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        log.warning(f"[HYGIENE] Graceful Safari quit failed: {e}")

    time.sleep(3)

    # Force-kill any lingering Safari processes (incl. WebKit helpers that
    # sometimes survive a graceful quit when a tab is mid-network).
    for proc in ("Safari", "com.apple.WebKit.Networking", "com.apple.WebKit.WebContent"):
        try:
            subprocess.run(["pkill", "-x", proc], capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    time.sleep(2)
    return True


def _launch_safari() -> bool:
    try:
        subprocess.run(
            ["open", "-a", "Safari"],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(3)
        # Bring it to the front so subsequent AppleScript `front window`
        # calls in twitter_client land on the right surface.
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to activate'],
            capture_output=True, text=True, timeout=10,
        )
        time.sleep(2)
        return True
    except Exception as e:
        log.warning(f"[HYGIENE] Safari launch failed: {e}")
        return False


def restart_safari(reason: str = "") -> bool:
    """Quit + relaunch Safari. Returns True on success.

    Cooldown-guarded — refuses to bounce more than once per MIN_GAP_SECONDS.
    Login session survives because cookies live on disk.
    """
    last = _last_run_ts()
    gap = time.time() - last
    if gap < MIN_GAP_SECONDS:
        log.info(f"[HYGIENE] Skipping restart (last was {int(gap)}s ago, < {MIN_GAP_SECONDS}s cooldown). reason={reason}")
        return False

    log.warning(f"[HYGIENE] Restarting Safari. reason={reason or 'preventive'}")
    _quit_safari()
    ok = _launch_safari()
    if ok:
        _mark_ran()
        log.info("[HYGIENE] Safari restarted cleanly. Login session preserved.")
    return ok


def run_session_refresh() -> dict:
    """Preventive hygiene pass — restarts Safari to clear wedged state.

    Called by the scheduler every ~2h. Cooldown ensures back-to-back ticks
    don't bounce Safari twice.
    """
    log.info("[HYGIENE] Running preventive session refresh.")
    ok = restart_safari(reason="preventive_schedule")
    return {"restarted": ok, "ts": datetime.now().isoformat()}


def safe_run_session_refresh():
    """Scheduler wrapper. Logs failures but never crashes the scheduler.

    Does NOT call health.record_failure on a no-op (cooldown skip) — only on
    actual restart attempts. This avoids the preventive scheduler tripping
    the failure counter when it's working as designed.
    """
    from . import health
    try:
        result = run_session_refresh()
        if result.get("restarted"):
            health.record_success("hygiene")
    except Exception:
        log.info("[HYGIENE] Error during session refresh:")
        traceback.print_exc()
        health.record_failure("hygiene")
