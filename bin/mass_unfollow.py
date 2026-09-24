#!/usr/bin/env python3
"""Mass-unfollow driven directly on the x.com/<BOT_HANDLE>/following page.

Operator tool (/unfollow skill) — NOT a scheduled bot. Clicks each visible
'Following' button, confirms the modal, scrolls as the virtualized list
loads, repeats until the list is exhausted (or --max is hit).

Safety:
  - The protected keep-set is the CURRENT whitelist.json (all tiers +
    seeds[] handles — the 2026-06-07 spec's curated follow list). Those
    are never unfollowed: they're the accounts the follow policy may
    follow, and recording their unfollow would block the re-follow for
    30 days via the anti-churn ledger.
    `--keep legacy` restores the old wide keep-set (respect_list +
    engage/early-bird/mega target lists) for a gentler prune.
  - Every confirmed unfollow is recorded into action_ledger.json (30-day
    anti-churn so follow bots don't re-follow) and decrements
    following_count.json.
  - Jittered 3.5-7s spacing + a 20-40s breather every 25 unfollows.
  - A rate-limit toast or 5 consecutive failed confirm modals trigger a
    cooldown, never an abort.
  - Refuses to start Overnight and stops before the next unfollow once
    Waking hours end (22:00 America/Toronto) or on SIGTERM/SIGINT.
    Safari is driven only through the src.x.safari primitives, which refuse
    to start a page script at that point: a click left unconfirmed keeps
    the modal open, and nothing is unfollowed or recorded.
  - Stops after --max unfollows, 150 by default.
  - Refuses to run while the bot scheduler is up (Safari lock conflict);
    override with --force.
  - mass_unfollow_results.json is rewritten after every unfollow, so an
    interrupted run still reports.

Usage:
  .venv/bin/python bin/mass_unfollow.py [--max N] [--force]
"""
import argparse
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.guards import action_guard, active_hours  # noqa: E402
from src.core import config  # noqa: E402
from src.x import safari  # noqa: E402

# Stays under X's unfollow quota of about 190 per window; at pace `normal`
# (~480/h) a run ends in about 27 minutes.
DEFAULT_MAX = 150

LOG_PREFIX = "[MASS_UNFOLLOW]"

_STOP = threading.Event()


def _on_signal(signum, frame) -> None:
    active_hours.request_stop()
    _STOP.set()


def _pause(seconds: float) -> None:
    """A sleep that SIGTERM/SIGINT cuts short."""
    _STOP.wait(seconds)


def _stop_reason() -> str:
    return ("stop signal" if active_hours.stop_requested()
            else "Waking hours ended (22:00 America/Toronto)")


def _must_stop() -> bool:
    """Overnight or a stop signal: no further unfollow."""
    if active_hours.may_act():
        return False
    print("STOP: %s" % _stop_reason(), flush=True)
    return True


def _save_results(unfollowed: list) -> None:
    with open(os.path.join(ROOT, "mass_unfollow_results.json"), "w") as f:
        json.dump(unfollowed, f)


def _whitelist_keep_set() -> set:
    """All whitelist tier handles + seeds[] handles (the curated follow list)."""
    keep = set()
    with open(os.path.join(ROOT, "whitelist.json")) as f:
        wl = json.load(f)
    for handles in (wl.get("tiers") or {}).values():
        keep |= {str(h).lower() for h in handles}
    for seed in wl.get("seeds") or []:
        h = (seed.get("handle") or "").strip().lstrip("@").lower()
        if h:
            keep.add(h)
    return keep


def _legacy_keep_set() -> set:
    """The wide keep-set of the retired smart_unfollow job, plus the whitelist."""
    from src.guards import respect_list
    from src.replies.early_bird_bot import EARLY_BIRD_ACCOUNTS
    from src.account.engage_bot import TARGET_ACCOUNTS
    from src.replies.mega_watch_bot import MEGA_ACCOUNTS
    keep = {h.lower() for h in respect_list.load()}
    for handles in (TARGET_ACCOUNTS, EARLY_BIRD_ACCOUNTS, MEGA_ACCOUNTS):
        keep |= {h.lower() for h in handles}
    wl = action_guard.load_whitelist()
    return keep | wl["tier1"] | wl["tier2"] | _whitelist_keep_set()


# NOTE: plain JS here — safari._run_js() reads it from a file, unescaped.
PICK_JS_TEMPLATE = (
    """
(function(){
  var keep = %s;
  var btns = document.querySelectorAll('[data-testid$="-unfollow"]:not([data-mu])');
  for (var i = 0; i < btns.length; i++) {
    var b = btns[i];
    var cell = b.closest('[data-testid="UserCell"]');
    var h = '';
    if (cell) {
      var ls = cell.querySelectorAll('a[href^="/"]');
      if (ls.length) h = (ls[0].getAttribute('href') || '').replace(/^\\//, '').split(/[\\/?]/)[0].toLowerCase();
    }
    if (h && keep.indexOf(h) >= 0) { b.setAttribute('data-mu', 'keep'); continue; }
    b.setAttribute('data-mu', 'clicked');
    b.click();
    return 'CLICK:' + h;
  }
  return 'NONE';
})()
"""
)

CONFIRM_JS = """
(function(){
  var out;
  var c = document.querySelector('[data-testid="confirmationSheetConfirm"]');
  if (c) { c.click(); out = 'CONFIRMED'; } else { out = 'NO_CONFIRM'; }
  var t = document.querySelector('[data-testid="toast"]');
  if (t) out += '|TOAST:' + t.textContent.replace(/["|]/g, ' ').slice(0, 120);
  return out;
})()
"""

# X surfaces rate-limits as a blue toast at the bottom of the page.
_LIMIT_TOAST_RE = re.compile(
    r"limit|unable|try again|wait|too many|restreint|r\xe9essayer|impossible",
    re.IGNORECASE,
)

SCROLL_JS = "window.scrollBy(0, 1800); 'SCROLLED'"

# Clear tags left by a previous run so a new keep-set is re-evaluated.
CLEAR_TAGS_JS = """
(function(){
  var t = document.querySelectorAll('[data-mu]');
  for (var i = 0; i < t.length; i++) t[i].removeAttribute('data-mu');
  return 'CLEARED:' + t.length;
})()
"""


def run_js(js: str) -> str:
    """The page answer, or an `OSAERR:` string when Safari gave none; the
    osascript error itself goes to bot.log under the `[MASS_UNFOLLOW]` tag."""
    return (safari._run_js(js, 30, log_prefix=LOG_PREFIX)
            or "OSAERR:no answer (see bot.log %s)" % LOG_PREFIX)


def _bot_is_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", r"python.*main\.py"], capture_output=True, text=True
    )
    return r.returncode == 0


def _reload_page() -> None:
    safari._run_js("location.reload(); 'RELOADED'", log_prefix=LOG_PREFIX)
    _pause(8)


def _ensure_following_page() -> None:
    """Navigate the front tab to /following if it isn't there already."""
    url = safari._run_js("location.href", log_prefix=LOG_PREFIX)
    target = f"https://x.com/{config.BOT_HANDLE}/following"
    if "/following" not in url:
        print(f"navigating to {target}", flush=True)
        safari._run_applescript(
            f'tell application "Safari" to set URL of current tab of front window to "{target}"',
            timeout_s=15)
        _pause(6)


def main() -> None:
    unfollowed = []
    try:
        _run(unfollowed)
    except active_hours.OutsideActiveHours:
        # Raised by a safari primitive before its osascript starts: the page
        # script did not run. Between a click and its confirm, the modal
        # stays open and nothing is unfollowed or recorded.
        print("STOP: %s" % _stop_reason(), flush=True)
    _save_results(unfollowed)
    print("TOTAL unfollowed: %d" % len(unfollowed), flush=True)


def _run(unfollowed: list) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=DEFAULT_MAX,
                    help="stop after N unfollows (default %(default)s)")
    ap.add_argument("--force", action="store_true",
                    help="run even if the bot scheduler is up (Safari lock conflict)")
    ap.add_argument("--keep", choices=["whitelist", "legacy"], default="whitelist",
                    help="keep-set: 'whitelist' = current whitelist.json tiers+seeds "
                         "(full purge, default); 'legacy' = also keep respect_list + "
                         "engage/early-bird/mega targets (gentle prune)")
    ap.add_argument("--pace", choices=["normal", "fast", "brisk", "insane"],
                    default="normal",
                    help="normal ≈ 480/hr (3.5-7s jitter, breather every 25 — "
                         "default); "
                         "fast ≈ 1400/hr (1.2-2.5s jitter, breather every 100); "
                         "brisk ≈ 2000/hr (0.8-1.8s jitter, breather every 150); "
                         "insane = minimal gaps (X drains its ~190/window quota "
                         "in minutes, then it's all cooldowns anyway)")
    ap.add_argument("--cooldown-mins", type=float, default=2.0,
                    help="cooldown on rate-limit detection (grows +50%% per "
                         "consecutive hit, capped at 4x); every pace cools down "
                         "and resumes — the run never aborts on a rate limit")
    args = ap.parse_args()

    if not active_hours.may_act():
        print("ABORT: Overnight. Waking hours are 04:30–22:00 America/Toronto.",
              flush=True)
        sys.exit(1)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if args.pace == "insane":
        confirm_wait, gap_lo, gap_hi = 0.5, 0.4, 1.0
        breather_every, breather_lo, breather_hi = 200, 5, 10
    elif args.pace == "brisk":
        confirm_wait, gap_lo, gap_hi = 0.6, 0.8, 1.8
        breather_every, breather_lo, breather_hi = 150, 8, 15
    elif args.pace == "fast":
        confirm_wait, gap_lo, gap_hi = 0.7, 1.2, 2.5
        breather_every, breather_lo, breather_hi = 100, 15, 25
    else:
        confirm_wait, gap_lo, gap_hi = 1.2, 3.5, 7.0
        breather_every, breather_lo, breather_hi = 25, 20, 40

    keep = _whitelist_keep_set() if args.keep == "whitelist" else _legacy_keep_set()
    pick_js = PICK_JS_TEMPLATE % json.dumps(sorted(keep))
    print("keep-set: %d handles (%s mode)" % (len(keep), args.keep), flush=True)

    if _bot_is_running() and not args.force:
        print("ABORT: bot scheduler is running — it shares Safari. "
              "Stop it first (/stop) or pass --force.", flush=True)
        sys.exit(1)

    _ensure_following_page()
    run_js(CLEAR_TAGS_JS)

    empty_rounds = 0
    noconfirm_streak = 0
    limit_hits = 0
    reload_attempts = 0

    def cooldown(reason: str) -> None:
        nonlocal noconfirm_streak, limit_hits
        limit_hits += 1
        mins = min(args.cooldown_mins * (1.5 ** (limit_hits - 1)),
                   args.cooldown_mins * 4)
        print("COOLDOWN %.1f min (#%d): %s" % (mins, limit_hits, reason), flush=True)
        _pause(mins * 60)
        noconfirm_streak = 0
        run_js(CLEAR_TAGS_JS)  # re-arm cells whose click never confirmed

    while len(unfollowed) < args.max:
        if _must_stop():
            break
        res = run_js(pick_js)
        if res.startswith("CLICK:"):
            empty_rounds = 0
            h = res[6:] or "unknown"
            _pause(confirm_wait)
            if _must_stop():  # the modal stays open: nothing unfollowed
                break
            c = run_js(CONFIRM_JS)
            confirmed = c.startswith("CONFIRMED")
            toast = c.split("|TOAST:", 1)[1] if "|TOAST:" in c else ""
            if toast and _LIMIT_TOAST_RE.search(toast):
                print("rate-limit toast: %s" % toast.strip(), flush=True)
                cooldown("rate-limit toast")
                continue
            if confirmed:
                noconfirm_streak = 0
                reload_attempts = 0
                if limit_hits and len(unfollowed) % 50 == 0:
                    limit_hits = 0  # healthy streak → reset backoff
                unfollowed.append(h)
                _save_results(unfollowed)
                try:
                    action_guard.record(action_guard.UNFOLLOW, target=h)
                    action_guard.adjust_following(-1)
                except Exception as e:  # ledger best-effort, never stop the run
                    print("ledger err:", e, flush=True)
                print("[%d] unfollowed @%s" % (len(unfollowed), h), flush=True)
            else:
                noconfirm_streak += 1
                print("no confirm for @%s (%s, streak %d)"
                      % (h, c, noconfirm_streak), flush=True)
                if noconfirm_streak >= 5:
                    cooldown("5 consecutive failed confirms")
                    continue
                _pause(3)
            _pause(random.uniform(gap_lo, gap_hi))
            if unfollowed and len(unfollowed) % breather_every == 0:
                p = random.uniform(breather_lo, breather_hi)
                print("breather %.0fs" % p, flush=True)
                _pause(p)
        elif res == "NONE":
            empty_rounds += 1
            if empty_rounds >= 6:
                # An empty viewport is ambiguous: list exhausted, OR the
                # rate-limit froze the list API so scrolling loads nothing
                # (false DONE observed 2026-06-07 at 190/~4K). Reload and
                # re-verify before believing it.
                reload_attempts += 1
                if reload_attempts >= 3:
                    print("DONE: no unfollow buttons after %d reloads — list "
                          "exhausted" % reload_attempts, flush=True)
                    break
                print("empty viewport — reload + re-verify (%d/3)"
                      % reload_attempts, flush=True)
                _pause(args.cooldown_mins * 60)
                if _must_stop():
                    break
                _reload_page()
                run_js(CLEAR_TAGS_JS)
                empty_rounds = 0
                continue
            run_js(SCROLL_JS)
            _pause(2.5)
        else:
            empty_rounds += 1
            print("JS err:", res[:200], flush=True)
            if empty_rounds >= 6:
                print("ABORT: repeated JS errors", flush=True)
                break
            _pause(3)


if __name__ == "__main__":
    main()
