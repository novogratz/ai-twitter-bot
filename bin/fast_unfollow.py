#!/usr/bin/env python3
"""FAST mass unfollow — operate on the /following PAGE, no per-profile visits.

The slow path opened each profile (full page load + 5s) before clicking. This
stays on x.com/<handle>/following and clicks the inline "Following" button on
each row, then the confirm dialog. ~5x faster.

How it works each loop:
  1. Click the FIRST still-followed row's Following button (data-testid$="-unfollow").
     Once unfollowed, that row's button becomes "-follow", so the next first
     "-unfollow" is always the next account to clear.
  2. Click the confirm in the modal.
  3. When no "-unfollow" buttons are loaded, scroll to load more; after several
     empty scrolls in a row, we're done.

SAFETY: requires MASS_UNFOLLOW_CONFIRM=1. Keeps a short delay between clicks
(rapid-fire on one page is still a suspension signal). Tune with env vars.

Usage:
    MASS_UNFOLLOW_CONFIRM=1 .venv/bin/python bin/fast_unfollow.py
"""
import os
import random
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.chdir(_REPO)

import webbrowser

from src.config import BOT_HANDLE
from src.logger import log
from src.twitter_client import _safari_eval_js, _safari_lock

# Delays (seconds). Short, but nonzero — the confirm modal needs a moment to
# render, and zero-delay clicking is a suspension trigger.
DIALOG_WAIT = float(os.environ.get("FAST_UNFOLLOW_DIALOG_WAIT", "0.8"))
AFTER_CONFIRM = float(os.environ.get("FAST_UNFOLLOW_AFTER", "0.5"))
SCROLL_WAIT = float(os.environ.get("FAST_UNFOLLOW_SCROLL_WAIT", "1.5"))
MAX_EMPTY_SCROLLS = int(os.environ.get("FAST_UNFOLLOW_MAX_EMPTY_SCROLLS", "6"))

CLICK_NEXT_JS = """
(function() {
    var btns = document.querySelectorAll('button[data-testid$="-unfollow"]');
    if (!btns.length) return 'NONE';
    var b = btns[0];
    var label = b.getAttribute('aria-label') || 'row';
    b.click();
    return label;
})()
"""

CONFIRM_JS = """
(function() {
    var b = document.querySelector('[data-testid="confirmationSheetConfirm"]');
    if (b) { b.click(); return 'CONFIRMED'; }
    return 'NO_CONFIRM';
})()
"""

SCROLL_JS = "(function(){ window.scrollBy(0, 2400); return 'SCROLLED'; })()"


def main() -> int:
    if os.environ.get("MASS_UNFOLLOW_CONFIRM") != "1":
        print("Refusing to run without MASS_UNFOLLOW_CONFIRM=1. This unfollows everyone.")
        return 2

    url = f"https://x.com/{BOT_HANDLE}/following"
    log.info(f"[FAST-UNFOLLOW] Opening {url}")
    with _safari_lock:
        webbrowser.open(url)
        time.sleep(5)

        total = 0
        empty_scrolls = 0
        while True:
            label = _safari_eval_js(CLICK_NEXT_JS)
            if label == "NONE" or not label:
                # Nothing loaded — scroll for more.
                _safari_eval_js(SCROLL_JS)
                empty_scrolls += 1
                log.info(f"[FAST-UNFOLLOW] No buttons; scrolling "
                         f"({empty_scrolls}/{MAX_EMPTY_SCROLLS}). total={total}")
                if empty_scrolls >= MAX_EMPTY_SCROLLS:
                    log.info("[FAST-UNFOLLOW] No more accounts after repeated scrolls. Done.")
                    break
                time.sleep(SCROLL_WAIT)
                continue

            empty_scrolls = 0
            time.sleep(DIALOG_WAIT)
            confirm = _safari_eval_js(CONFIRM_JS)
            if confirm == "CONFIRMED":
                total += 1
                log.info(f"[FAST-UNFOLLOW] ({total}) unfollowed {label}")
            else:
                log.info(f"[FAST-UNFOLLOW] {label}: no confirm dialog ({confirm}) — continuing")
            # short randomized gap for ban safety
            time.sleep(AFTER_CONFIRM + random.uniform(0, 0.4))

        log.info(f"[FAST-UNFOLLOW] FINISHED. Unfollowed {total} this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
