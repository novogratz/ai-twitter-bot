"""Follow-back bot — scrape our followers list and follow them back.

Why: reciprocity is the single highest-leverage follower-growth tactic
on X. ~10-30% of accounts you follow follow back if you're in their
niche. The existing reciprocity loop only fires when someone REPLIES
to us — that misses 90% of new followers (lurkers + likers).

Strategy:
  - Once per ~2h, visit /AISpaceDecoder/followers via Safari + JS scrape.
  - Get the list of @handles currently following us.
  - Follow back any handle we haven't followed yet, capped at FOLLOW_CAP
    per cycle (don't burn the daily follow budget all at once).
  - Persist via engage_bot's followed_accounts.json so we don't double-follow.

Safety: handle whitelist heuristic — skip obvious bots (handle made of
random alphanumerics with no vowels, length=15) and BLOCKLIST entries.
"""
import json
import os
import random
import re
import subprocess
import tempfile
import time
import traceback

from .config import _PROJECT_ROOT, BOT_HANDLE, BLOCKLIST
from .logger import log
from .twitter_client import follow_account, _safari_lock, close_front_tab, _run_applescript, _scroll_page

import webbrowser

FOLLOW_BACK_CAP_PER_CYCLE = int(os.environ.get("FOLLOWBACK_CAP", "8"))


def _looks_like_real_handle(handle: str) -> bool:
    """Cheap bot-handle filter."""
    if not handle or len(handle) > 15:
        return False
    h = handle.lower()
    if h in BLOCKLIST:
        return False
    # Pure-alphanumeric with no vowels = likely a bot (e.g., xkprz9821).
    if not re.search(r"[aeiouAEIOU]", handle):
        return False
    # Mostly digits = throwaway.
    digits = sum(1 for c in handle if c.isdigit())
    if digits >= len(handle) * 0.6:
        return False
    return True


def _scrape_followers_list(max_handles: int = 30) -> list[str]:
    """Open /AISpaceDecoder/followers and scrape the @handles visible on the page."""
    js_code = """
    (function() {
        var handles = [];
        var seen = {};
        var anchors = document.querySelectorAll('a[role="link"][href^="/"]');
        for (var i = 0; i < anchors.length && handles.length < MAX; i++) {
            var h = anchors[i].getAttribute('href') || '';
            var m = h.match(/^\\/([A-Za-z0-9_]+)$/);
            if (!m) continue;
            var u = m[1];
            // Skip non-profile paths
            if (['home','explore','notifications','messages','i','search',
                 'compose','settings','intent','login','signup'].indexOf(u) !== -1) continue;
            if (seen[u]) continue;
            seen[u] = 1;
            handles.push(u);
        }
        return handles.join(',');
    })()
    """.replace("MAX", str(max_handles * 2))

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    tmp.write(js_code)
    tmp.close()

    applescript = f'''
    tell application "Safari" to activate
    set jsCode to (read POSIX file "{tmp.name}")
    tell application "Safari"
        set result to do JavaScript jsCode in current tab of front window
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=30,
        )
        os.unlink(tmp.name)
        if result.returncode != 0:
            log.info(f"[FOLLOWBACK] JS failed: {result.stderr[:200]}")
            return []
        raw = (result.stdout or "").strip()
        if not raw:
            return []
        handles = [h for h in raw.split(",") if h]
        return handles[:max_handles]
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        log.info("[FOLLOWBACK] Scrape exception:")
        traceback.print_exc()
        return []


def run_followback_cycle():
    """Visit /AISpaceDecoder/followers and follow back fresh ones."""
    from .engage_bot import _load_followed, _save_followed

    followed = _load_followed()

    with _safari_lock:
        url = f"https://x.com/{BOT_HANDLE}/followers"
        log.info(f"[FOLLOWBACK] Opening {url}")
        webbrowser.open(url)
        time.sleep(8)
        # Scroll twice to load 30-50 followers.
        _scroll_page()
        time.sleep(2)
        _scroll_page()
        time.sleep(2)

        candidates = _scrape_followers_list(max_handles=50)
        close_front_tab()

    if not candidates:
        log.info("[FOLLOWBACK] No candidates scraped.")
        return

    log.info(f"[FOLLOWBACK] Scraped {len(candidates)} follower handles. Filtering.")

    fresh = []
    for h in candidates:
        if h.lower() == BOT_HANDLE.lower():
            continue
        if h in followed:
            continue
        if not _looks_like_real_handle(h):
            log.info(f"[FOLLOWBACK] Skipping suspicious handle @{h}")
            continue
        fresh.append(h)

    if not fresh:
        log.info("[FOLLOWBACK] No fresh follow-back candidates after filtering.")
        return

    # Cap per cycle so we don't burn the daily follow budget.
    random.shuffle(fresh)
    pick = fresh[:FOLLOW_BACK_CAP_PER_CYCLE]
    log.info(f"[FOLLOWBACK] Following back {len(pick)} accounts: {pick}")

    for h in pick:
        try:
            ok = follow_account(h)
            if ok:
                followed.add(h)
                _save_followed(followed)
            time.sleep(random.randint(3, 6))
        except Exception:
            log.info(f"[FOLLOWBACK] Follow @{h} failed:")
            traceback.print_exc()

    log.info(f"[FOLLOWBACK] Cycle done. Total followed (bot history): {len(followed)}")


def safe_run_followback_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_followback_cycle()
        health.record_success("followback")
    except Exception:
        log.info("[FOLLOWBACK] Error during follow-back cycle:")
        traceback.print_exc()
        health.record_failure("followback")
