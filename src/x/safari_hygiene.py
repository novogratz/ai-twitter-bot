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

from ..core.config import _PROJECT_ROOT
from ..core.logger import log
from ..guards.active_hours import OutsideActiveHours
from . import safari

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
    try:
        subprocess.run(
            ["osascript", "-e", '''
tell application "Safari"
  activate
  if (count of windows) = 0 then make new document
  tell window 1
    set URL of current tab to "https://x.com/home"
  end tell
end tell
'''],
            capture_output=True, text=True, timeout=20,
        )
        time.sleep(8)

        # A failure is logged by _run_js under [HYGIENE]; the render check
        # below decides.
        safari._run_js(_CLEAR_SW_AND_RELOAD_JS, 45, log_prefix="[HYGIENE]", activate=True)
        time.sleep(12)

        for attempt in range(3):
            status = safari._run_js(_RENDER_CHECK_JS, 20, log_prefix="[HYGIENE]", activate=True)
            if status.startswith("READY:"):
                log.info(f"[HYGIENE] x.com warmed up — service workers cleared, render verified ({status}).")
                return True
            if status == "LOGIN_REQUIRED":
                log.warning("[HYGIENE] x.com warm-up reached login page; manual login may be required.")
                return False

            log.warning(f"[HYGIENE] x.com still blank after warm-up attempt {attempt + 1}/3: {status[:200]}")
            cache_bust = int(time.time())
            subprocess.run(
                ["osascript", "-e", f'''
tell application "Safari"
  activate
  tell window 1
    set URL of current tab to "https://x.com/home?bot_recover={cache_bust}"
  end tell
end tell
'''],
                capture_output=True, text=True, timeout=20,
            )
            time.sleep(10)

        log.warning("[HYGIENE] x.com warm-up failed render verification after 3 attempts.")
        return False
    except OutsideActiveHours:
        raise
    except Exception as e:
        log.warning(f"[HYGIENE] x.com warm-up failed (non-fatal): {e}")
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
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to activate'],
            capture_output=True, text=True, timeout=10,
        )
        time.sleep(2)
        # Clear stale service workers and warm up x.com so the first scrape
        # hits a rendered page, not a black-screen app shell.
        return _warm_up_xcom()
    except Exception as e:
        log.warning(f"[HYGIENE] Safari launch failed: {e}")
        return False


def restart_safari(reason: str = "") -> bool:
    """Quit + relaunch Safari. Returns True on success.

    Cooldown-guarded — refuses to bounce more than once per MIN_GAP_SECONDS,
    UNLESS reason is 'black_screen_recovery' which uses a shorter 5-min gap
    so reactive recovery isn't blocked by the 30-min preventive cooldown.
    Login session survives because cookies live on disk.
    """
    last = _last_run_ts()
    gap = time.time() - last
    effective_gap = 5 * 60 if reason == "black_screen_recovery" else MIN_GAP_SECONDS
    if gap < effective_gap:
        log.info(f"[HYGIENE] Skipping restart (last was {int(gap)}s ago, < {effective_gap}s cooldown). reason={reason}")
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
    from ..core import health
    try:
        result = run_session_refresh()
        if result.get("restarted"):
            health.record_success("hygiene")
    except Exception:
        log.info("[HYGIENE] Error during session refresh:")
        traceback.print_exc()
        health.record_failure("hygiene")


def safe_run_periodic_warmup():
    """Scheduler wrapper: clear SW + hard-reload x.com every 30 min.

    Lighter than a full restart — no Safari quit, just evict stale service
    workers so the app shell stays fresh during long runs.
    Takes the safari lock so it doesn't race with active scrape cycles.
    """
    try:
        from .safari import _safari_lock
        log.info("[HYGIENE] Periodic SW warmup — clearing x.com service workers.")
        with _safari_lock:
            ok = _warm_up_xcom()
        if ok:
            log.info("[HYGIENE] Periodic SW warmup done.")
        else:
            log.warning("[HYGIENE] Periodic SW warmup returned False (non-fatal).")
    except Exception:
        log.warning("[HYGIENE] Periodic SW warmup error (non-fatal):")
        traceback.print_exc()
