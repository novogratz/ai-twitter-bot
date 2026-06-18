#!/usr/bin/env python3
"""One-shot MASS UNFOLLOW — wipe everyone (operator clean-slate request).

Unfollows EVERY account in /following, ignoring the whitelist, the anti-churn
cooldown, and the daily cap (sets MASS_UNFOLLOW_FORCE=1). Re-scrapes /following
each pass and loops until the list is empty (or no progress is made).

It KEEPS a small randomized inter-action delay — going zero-delay is the fastest
way to get the account flagged/suspended, which would defeat the purpose.

SAFETY:
  - Requires MASS_UNFOLLOW_CONFIRM=1 in the environment, so it can never run by
    accident.
  - Honors DRY_RUN=1 (logs intended unfollows, executes none).

Usage (from repo root):
    MASS_UNFOLLOW_CONFIRM=1 .venv/bin/python bin/mass_unfollow.py
    # dry run first:
    DRY_RUN=1 MASS_UNFOLLOW_CONFIRM=1 .venv/bin/python bin/mass_unfollow.py
"""
import os
import random
import sys
import time

# Run from the repo root so relative imports + state files resolve.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.chdir(_REPO)

# Force the unfollow guard to bypass whitelist / churn / daily cap.
os.environ["MASS_UNFOLLOW_FORCE"] = "1"

from src.config import BOT_HANDLE
from src.logger import log
from src.smart_unfollow_bot import _scrape_handle_list
from src.twitter_client import unfollow_account

# Minimum delay between unfollows (seconds). Even on a "drain now" wipe, keep
# this nonzero — rapid-fire unfollows are a textbook suspension trigger.
MIN_DELAY = int(os.environ.get("MASS_UNFOLLOW_MIN_DELAY", "3"))
MAX_DELAY = int(os.environ.get("MASS_UNFOLLOW_MAX_DELAY", "6"))
# Stop after this many full passes that unfollow nobody (handles that won't
# clear — protected-by-X, deactivated, scrape misses).
MAX_STALE_PASSES = 3
# Hard cap on total passes (0 = unlimited). Set to 1 for a single-batch run or
# to validate the Safari/scrape path without committing to a full drain.
MAX_PASSES = int(os.environ.get("MASS_UNFOLLOW_MAX_PASSES", "0"))


def main() -> int:
    if os.environ.get("MASS_UNFOLLOW_CONFIRM") != "1":
        print("Refusing to run without MASS_UNFOLLOW_CONFIRM=1 in the environment.")
        print("This unfollows EVERY account you follow. See the file header.")
        return 2

    dry = os.environ.get("DRY_RUN") == "1"
    log.info(f"[MASS-UNFOLLOW] Starting clean-slate wipe for @{BOT_HANDLE} "
             f"(dry_run={dry}). MASS_UNFOLLOW_FORCE on.")

    total = 0
    failed = set()           # handles we tried but couldn't unfollow
    stale_passes = 0
    pass_num = 0

    while True:
        if MAX_PASSES and pass_num >= MAX_PASSES:
            log.info(f"[MASS-UNFOLLOW] Reached MAX_PASSES={MAX_PASSES}. Stopping.")
            break
        pass_num += 1
        following = _scrape_handle_list(f"https://x.com/{BOT_HANDLE}/following", 200)
        # Drop self + anything already known-stuck.
        following = [h for h in following
                     if h.lower() != BOT_HANDLE.lower() and h not in failed]
        if not following:
            log.info(f"[MASS-UNFOLLOW] Pass {pass_num}: /following is empty. Done.")
            break

        log.info(f"[MASS-UNFOLLOW] Pass {pass_num}: {len(following)} to unfollow "
                 f"(total so far: {total}).")
        progressed = 0
        for h in following:
            try:
                if unfollow_account(h):
                    total += 1
                    progressed += 1
                    log.info(f"[MASS-UNFOLLOW] ({total}) unfollowed @{h}")
                else:
                    failed.add(h)
            except Exception as e:
                log.info(f"[MASS-UNFOLLOW] @{h} error: {e}")
                failed.add(h)
            time.sleep(random.randint(MIN_DELAY, MAX_DELAY))

        if progressed == 0:
            stale_passes += 1
            log.info(f"[MASS-UNFOLLOW] Pass {pass_num} made no progress "
                     f"({stale_passes}/{MAX_STALE_PASSES} stale).")
            if stale_passes >= MAX_STALE_PASSES:
                log.info("[MASS-UNFOLLOW] Too many stale passes — stopping. "
                         f"{len(failed)} handles could not be cleared: "
                         f"{sorted(failed)[:30]}")
                break
        else:
            stale_passes = 0

    log.info(f"[MASS-UNFOLLOW] FINISHED. Unfollowed {total} account(s). "
             f"{len(failed)} left unresolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
