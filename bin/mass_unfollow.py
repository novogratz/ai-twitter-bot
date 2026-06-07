#!/usr/bin/env python3
"""Mass-unfollow driven directly on the x.com/<BOT_HANDLE>/following page.

Operator tool (/unfollow skill) — NOT a scheduled bot. Clicks each visible
'Following' button, confirms the modal, scrolls as the virtualized list
loads, repeats until the list is exhausted (or --max is hit).

Safety:
  - The protected keep-set is the CURRENT whitelist.json (all tiers +
    seeds[] handles — the 2026-06-07 spec's curated follow list). Those
    are never unfollowed: they're the accounts marquee_follow_bot is
    meant to be following, and recording their unfollow would block the
    re-follow for 30 days via the anti-churn ledger.
    `--keep legacy` restores the old wide keep-set (respect_list +
    engage/early-bird/mega target lists) for a gentler prune.
  - Every confirmed unfollow is recorded into action_ledger.json (30-day
    anti-churn so follow bots don't re-follow) and decrements
    following_count.json.
  - Jittered 3.5-7s spacing + a 20-40s breather every 25 unfollows.
  - Aborts after 5 consecutive failed confirm modals (likely action block).
  - Refuses to run while the bot scheduler is up (Safari lock conflict);
    override with --force.

Usage:
  .venv/bin/python bin/mass_unfollow.py [--max N] [--force]
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import action_guard, config  # noqa: E402


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
    from src.smart_unfollow_bot import _build_keep_set
    return _build_keep_set() | _whitelist_keep_set()


# NOTE: plain JS here — run_js() escapes backslashes + double quotes once
# when embedding into the AppleScript string.
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
    escaped = js.replace("\\", "\\\\").replace('"', '\\"')
    osa = (
        'tell application "Safari" to do JavaScript "%s" '
        "in current tab of front window" % escaped
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", osa], capture_output=True, text=True, timeout=30
        )
        out = (r.stdout or "").strip()
        if not out and r.stderr:
            return "OSAERR:" + r.stderr.strip()[:200]
        return out
    except subprocess.TimeoutExpired:
        return "OSAERR:timeout"


def _bot_is_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", r"python.*main\.py"], capture_output=True, text=True
    )
    return r.returncode == 0


def _reload_page() -> None:
    subprocess.run(
        ["osascript", "-e",
         'tell application "Safari" to do JavaScript "location.reload(); '
         "'RELOADED'\" in current tab of front window"],
        capture_output=True, text=True, timeout=15,
    )
    time.sleep(8)


def _ensure_following_page() -> None:
    """Navigate the front tab to /following if it isn't there already."""
    r = subprocess.run(
        ["osascript", "-e",
         'tell application "Safari" to get URL of current tab of front window'],
        capture_output=True, text=True, timeout=15,
    )
    url = (r.stdout or "").strip()
    target = f"https://x.com/{config.BOT_HANDLE}/following"
    if "/following" not in url:
        print(f"navigating to {target}", flush=True)
        subprocess.run(
            ["osascript", "-e",
             f'tell application "Safari" to set URL of current tab of front window to "{target}"'],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(6)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=10**6, help="stop after N unfollows")
    ap.add_argument("--force", action="store_true",
                    help="run even if the bot scheduler is up (Safari lock conflict)")
    ap.add_argument("--keep", choices=["whitelist", "legacy"], default="whitelist",
                    help="keep-set: 'whitelist' = current whitelist.json tiers+seeds "
                         "(full purge, default); 'legacy' = also keep respect_list + "
                         "engage/early-bird/mega targets (gentle prune)")
    ap.add_argument("--pace", choices=["normal", "fast", "insane"], default="normal",
                    help="normal ≈ 480/hr (3.5-7s jitter, breather every 25); "
                         "fast ≈ 1400/hr (1.2-2.5s jitter, breather every 100); "
                         "insane = minimal gaps, NEVER aborts — on a rate-limit "
                         "toast or repeated failed confirms it cools down "
                         "--cooldown-mins then resumes until the list is empty")
    ap.add_argument("--cooldown-mins", type=float, default=5.0,
                    help="cooldown on rate-limit detection (insane pace; grows "
                         "+50%% per consecutive hit, capped at 4x)")
    args = ap.parse_args()

    if args.pace == "insane":
        confirm_wait, gap_lo, gap_hi = 0.5, 0.4, 1.0
        breather_every, breather_lo, breather_hi = 200, 5, 10
    elif args.pace == "fast":
        confirm_wait, gap_lo, gap_hi = 0.7, 1.2, 2.5
        breather_every, breather_lo, breather_hi = 100, 15, 25
    else:
        confirm_wait, gap_lo, gap_hi = 1.2, 3.5, 7.0
        breather_every, breather_lo, breather_hi = 25, 20, 40
    auto_resume = args.pace == "insane"

    keep = _whitelist_keep_set() if args.keep == "whitelist" else _legacy_keep_set()
    pick_js = PICK_JS_TEMPLATE % json.dumps(sorted(keep))
    print("keep-set: %d handles (%s mode)" % (len(keep), args.keep), flush=True)

    if _bot_is_running() and not args.force:
        print("ABORT: bot scheduler is running — it shares Safari. "
              "Stop it first (/stop) or pass --force.", flush=True)
        sys.exit(1)

    _ensure_following_page()
    run_js(CLEAR_TAGS_JS)

    unfollowed = []
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
        time.sleep(mins * 60)
        noconfirm_streak = 0
        run_js(CLEAR_TAGS_JS)  # re-arm cells whose click never confirmed

    while len(unfollowed) < args.max:
        res = run_js(pick_js)
        if res.startswith("CLICK:"):
            empty_rounds = 0
            h = res[6:] or "unknown"
            time.sleep(confirm_wait)
            c = run_js(CONFIRM_JS)
            confirmed = c.startswith("CONFIRMED")
            toast = c.split("|TOAST:", 1)[1] if "|TOAST:" in c else ""
            if toast and _LIMIT_TOAST_RE.search(toast):
                print("rate-limit toast: %s" % toast.strip(), flush=True)
                if auto_resume:
                    cooldown("rate-limit toast")
                    continue
                print("ABORT: rate-limit toast", flush=True)
                break
            if confirmed:
                noconfirm_streak = 0
                reload_attempts = 0
                if limit_hits and len(unfollowed) % 50 == 0:
                    limit_hits = 0  # healthy streak → reset backoff
                unfollowed.append(h)
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
                    if auto_resume:
                        cooldown("5 consecutive failed confirms")
                        continue
                    print("ABORT: confirm failing repeatedly — possible action block",
                          flush=True)
                    break
                time.sleep(3)
            time.sleep(random.uniform(gap_lo, gap_hi))
            if unfollowed and len(unfollowed) % breather_every == 0:
                p = random.uniform(breather_lo, breather_hi)
                print("breather %.0fs" % p, flush=True)
                time.sleep(p)
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
                if auto_resume:
                    time.sleep(args.cooldown_mins * 60)
                _reload_page()
                run_js(CLEAR_TAGS_JS)
                empty_rounds = 0
                continue
            run_js(SCROLL_JS)
            time.sleep(2.5)
        else:
            empty_rounds += 1
            print("JS err:", res[:200], flush=True)
            if empty_rounds >= 6:
                print("ABORT: repeated JS errors", flush=True)
                break
            time.sleep(3)

    with open(os.path.join(ROOT, "mass_unfollow_results.json"), "w") as f:
        json.dump(unfollowed, f)
    print("TOTAL unfollowed: %d" % len(unfollowed), flush=True)


if __name__ == "__main__":
    main()
