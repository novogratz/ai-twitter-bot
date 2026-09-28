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

Three trigger paths:
  1. Preventive — main.py schedules run_session_refresh() every ~2h
     so we restart BEFORE Safari wedges.
  2. Reactive — health.record_failure asks for a restart once browser
     failures in a row reach its threshold.
  3. Blank pages — scraper._trigger_black_screen_recovery.

Every restart waits for the Safari lock, so it never quits Safari under a
session in progress. Its cooldown is the only delay between two restarts,
whichever path asks, and starts on every restart tried, failed or not; a
restart that succeeds resets the health failure counter here, the one
place (issue #302).
"""
import subprocess
import time
from datetime import datetime
from enum import Enum

from ..core.logger import log
from ..core.state_store import DISPOSABLE, StateFile
from ..guards.active_hours import OutsideActiveHours, may_act
from . import safari

# Disposable: losing it only allows one earlier Safari restart.
HYGIENE_STATE = StateFile("safari_hygiene_state.json", {}, DISPOSABLE)

# Don't restart Safari more than once in this window, whichever path asks
# (black_screen_recovery waits 5 min only). The preventive scheduler tick is
# every ~2h. This guards against a flapping bot causing rapid bounces.
MIN_GAP_SECONDS = 30 * 60  # 30 min


class RestartOutcome(Enum):
    """What restart_safari did. Truthy only for RESTARTED, so a caller that
    tests the result acts on a restart that succeeded only."""
    RESTARTED = "restarted"  # Safari quit, relaunched, x.com rendered
    REFUSED = "refused"      # cooldown, waking hours or a stop: Safari untouched
    FAILED = "failed"        # Safari quit and relaunched, x.com never rendered

    def __bool__(self):
        return self is RestartOutcome.RESTARTED


def _last_run_ts() -> float:
    try:
        return float(HYGIENE_STATE.read().get("last_run_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _mark_ran():
    HYGIENE_STATE.write({
        "last_run": datetime.now().isoformat(),
        "last_run_ts": time.time(),
    })


def _quit_safari() -> bool:
    """Quit Safari gracefully, then force-kill if it didn't go down.

    Cookies / localStorage / IndexedDB are file-based so login persists
    across the restart. Only volatile WebKit process state is lost — which
    is the whole point.
    """
    # Direct, not _run_applescript: the Safari being quit may be wedged, and
    # only this timeout guarantees the pkill below still runs.
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


_CLEAR_SW_AND_RELOAD_JS = """
(async () => {
  if ('serviceWorker' in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations();
    for (let r of regs) { await r.unregister(); }
  }
  if (window.caches) {
    const keys = await caches.keys();
    for (let k of keys) { await caches.delete(k); }
  }
  location.reload(true);
})();
""".strip()

_RENDER_CHECK_JS = """
(() => {
  const articles = document.querySelectorAll('article[data-testid="tweet"]').length;
  const main = document.querySelector('main');
  const bodyText = (document.body && document.body.innerText || '').trim();
  const url = location.href;
  if (articles > 0) return 'READY:articles:' + articles;
  if (main && bodyText.length > 300 && /Home|Following|For you|Accueil|Abonnements|Notifications|Search|Recherche/i.test(bodyText)) {
    return 'READY:shell:' + bodyText.length;
  }
  if (/login|i\\/flow\\/login/i.test(url) || /Sign in|Log in|Se connecter/i.test(bodyText)) {
    return 'LOGIN_REQUIRED';
  }
  return 'BLANK:' + bodyText.length + ':' + url;
})();
""".strip()


def _warm_up_xcom() -> bool:
    """Navigate to x.com, clear service workers/caches, hard reload.

    Prevents the 'black screen' where Safari restarts with stale SW cache
    and renders an empty app shell. Must run after Safari is fully up.
    """
    safari._run_applescript('''
tell application "Safari"
  activate
  if (count of windows) = 0 then make new document
  tell window 1
    set URL of current tab to "https://x.com/home"
  end tell
end tell
''', timeout_s=20)
    time.sleep(8)

    if not safari._run_js(_CLEAR_SW_AND_RELOAD_JS, 45, log_prefix="[HYGIENE]", activate=True):
        log.warning("[HYGIENE] x.com SW clear JS failed; the render check decides.")
    time.sleep(12)

    for attempt in range(3):
        status = safari._run_js(_RENDER_CHECK_JS, 20, log_prefix="[HYGIENE]", activate=True)
        if status.startswith("READY:"):
            log.info(f"[HYGIENE] x.com warmed up — service workers cleared, render verified ({status}).")
            return True
        if status == "LOGIN_REQUIRED":
            log.warning("[HYGIENE] x.com warm-up reached login page; manual login may be required.")
            return False

        log.warning(f"[HYGIENE] x.com still blank after warm-up attempt {attempt + 1}/3: "
                    f"{status[:200] or 'no answer'}")
        cache_bust = int(time.time())
        safari._run_applescript(f'''
tell application "Safari"
  activate
  tell window 1
    set URL of current tab to "https://x.com/home?bot_recover={cache_bust}"
  end tell
end tell
''', timeout_s=20)
        time.sleep(10)

    log.warning("[HYGIENE] x.com warm-up failed render verification after 3 attempts.")
    return False


def _launch_safari() -> bool:
    try:
        subprocess.run(
            ["open", "-a", "Safari"],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(4)
        # Bring it to the front so subsequent AppleScript `front window`
        # calls in src/x land on the right surface.
        safari._run_applescript('tell application "Safari" to activate', timeout_s=10)
        time.sleep(2)
        # Clear stale service workers and warm up x.com so the first scrape
        # hits a rendered page, not a black-screen app shell.
        return _warm_up_xcom()
    except Exception as e:
        log.warning(f"[HYGIENE] Safari launch failed: {e}")
        return False


def restart_safari(reason: str = "") -> RestartOutcome:
    """Quit + relaunch Safari: RESTARTED, REFUSED without touching Safari,
    or FAILED when x.com did not render after the relaunch.

    Cooldown-guarded — refuses to bounce more than once per MIN_GAP_SECONDS,
    UNLESS reason is 'black_screen_recovery' which uses a shorter 5-min gap
    so reactive recovery isn't blocked by the 30-min preventive cooldown.
    Every restart tried starts the cooldown, a FAILED one too; a REFUSED
    one does not.
    Login session survives because cookies live on disk. Outside waking
    hours, or once a stop was requested, it does nothing.

    It waits for the session holding the Safari lock, so a restart never
    pulls the tab from under a Reply or a read, and reads the cooldown
    once it has the lock. The lock is reentrant: a job that already holds
    it restarts at once.
    """
    if not may_act():
        log.info(f"[HYGIENE] Skipping restart outside waking hours. reason={reason}")
        return RestartOutcome.REFUSED
    try:
        with safari._safari_lock:
            return _restart_holding_lock(reason)
    except OutsideActiveHours:
        log.info(f"[HYGIENE] Skipping restart: waking hours ended while it waited for Safari. "
                 f"reason={reason}")
        return RestartOutcome.REFUSED


def _restart_holding_lock(reason: str) -> RestartOutcome:
    last = _last_run_ts()
    gap = time.time() - last
    effective_gap = 5 * 60 if reason == "black_screen_recovery" else MIN_GAP_SECONDS
    if gap < effective_gap:
        log.info(f"[HYGIENE] Skipping restart (last was {int(gap)}s ago, < {effective_gap}s cooldown). reason={reason}")
        return RestartOutcome.REFUSED

    log.warning(f"[HYGIENE] Restarting Safari. reason={reason or 'preventive'}")
    # A tried restart starts the cooldown even when it fails or raises:
    # otherwise every failure past the threshold bounces Safari again.
    try:
        _quit_safari()
        relaunched = _launch_safari()
    finally:
        _mark_ran()
    if not relaunched:
        return RestartOutcome.FAILED
    log.info("[HYGIENE] Safari restarted cleanly. Login session preserved.")
    from ..core import health  # health imports this module at load
    health.reset_after_restart(reason or "preventive")
    return RestartOutcome.RESTARTED


def run_session_refresh() -> dict:
    """Preventive hygiene pass — restarts Safari to clear wedged state.

    Called by the scheduler every ~2h. Cooldown ensures back-to-back ticks
    don't bounce Safari twice. A restart that succeeds resets the health
    failure counter inside restart_safari, as any restart does; the refresh
    itself never reaches health, and main.py keeps the job out of the
    counter.
    """
    log.info("[HYGIENE] Running preventive session refresh.")
    outcome = restart_safari(reason="preventive_schedule")
    return {"restarted": bool(outcome), "ts": datetime.now().isoformat()}
