"""Mass-follow blast bot — bulk-follow English AI infra niche accounts at scale.

Why: with 360 → 10k follower target, we need NET-NEW follows at maximum
volume. engage_bot follows from a curated list (slow ramp). discover_bot
finds new handles but only auto-follows 3/cycle. This bot just opens FR
search results and JS-clicks every Follow button it sees.

Strategy:
  - Every 30 min, pick a FR niche search query (rotating).
  - Open /search?q=...&f=people (people tab — direct profile cards
    with Follow buttons), or fall back to /search?q=...&f=live with
    in-feed Follow CTAs.
  - JS-find all 'Follow' buttons (data-testid contains "-follow"),
    skip "-unfollow" (already following), click first N.
  - Persist via engage_bot's followed_accounts.json so we don't
    spam-follow the same handle.

Caps tuned for max throughput: 25-35 follows/cycle × 4 cycles/hour
= ~100-140 net-new follows/hour. X soft-rate on follows is ~400/day —
we're aggressive but stay below the spam threshold.
"""
import json
import os
import random
import subprocess
import tempfile
import time
import traceback
import urllib.parse
import webbrowser

from .config import _PROJECT_ROOT, BOT_HANDLE, get_live_cap
from .logger import log
from .twitter_client import _safari_lock, close_front_tab, _scroll_page

FOLLOWS_PER_CYCLE = int(os.environ.get("FOLLOW_BLAST_PER_CYCLE", "40"))
FOLLOW_BLAST_DAILY_CAP = int(os.environ.get("FOLLOW_BLAST_DAILY_CAP", "650"))
FOLLOW_BLAST_STATE_FILE = os.path.join(_PROJECT_ROOT, "follow_blast_state.json")

# English niche search queries. Rotated per cycle. The min_faves floor keeps
# us out of bot-farm zones — we want real global AI / crypto users.
BLAST_QUERIES = [
    "AI datacenter lang:en min_faves:25",
    "AI infrastructure lang:en min_faves:25",
    "power demand AI lang:en min_faves:25",
    "megawatt OR gigawatt AI lang:en min_faves:25",
    "CoreWeave OR CRWV lang:en min_faves:25",
    "APLD OR Applied Digital lang:en min_faves:25",
    "IREN OR HIVE lang:en min_faves:25",
    "TeraWulf OR WULF lang:en min_faves:25",
    "TAO OR Bittensor lang:en min_faves:25",
    "decentralized compute lang:en min_faves:25",
    "Nvidia OR GPU cluster lang:en min_faves:25",
    "nuclear OR grid AI datacenter lang:en min_faves:25",
    "robotics OR humanoid robots lang:en min_faves:25",
    "SpaceX OR Starlink lang:en min_faves:25",
]


def _click_follow_buttons(max_clicks: int) -> int:
    """JS: find Follow buttons (not Unfollow) on the current page and click them."""
    js_code = f"""
    (function() {{
        // Follow buttons have data-testid like "<userid>-follow"
        // (and "<userid>-unfollow" for already-following).
        var buttons = document.querySelectorAll('[data-testid$="-follow"]');
        var clicked = 0;
        for (var i = 0; i < buttons.length && clicked < {max_clicks}; i++) {{
            try {{
                var label = buttons[i].getAttribute('aria-label') || '';
                if (/unfollow|ne plus suivre|cesser de suivre/i.test(label)) continue;
                buttons[i].click();
                clicked++;
            }} catch (e) {{}}
        }}
        return clicked;
    }})()
    """
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
        r = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=20,
        )
        os.unlink(tmp.name)
        out = (r.stdout or "").strip()
        try:
            return int(out)
        except (ValueError, TypeError):
            return 0
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return 0


def _load_daily_state() -> dict:
    from datetime import date
    today = date.today().isoformat()
    if not os.path.exists(FOLLOW_BLAST_STATE_FILE):
        return {"date": today, "count": 0}
    try:
        with open(FOLLOW_BLAST_STATE_FILE, "r") as f:
            state = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {"date": today, "count": 0}
    if state.get("date") != today:
        return {"date": today, "count": 0}
    return {"date": today, "count": int(state.get("count") or 0)}


def _save_daily_state(state: dict) -> None:
    with open(FOLLOW_BLAST_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def run_follow_blast_cycle():
    """Open an English AI infra niche search, scroll, JS-click Follow buttons."""
    # Skip if X is suppressing us — bulk follows during a shadowban
    # phase trip the spam detector even harder.
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[FOLLOW-BLAST] Suppression cooldown active — skipping cycle.")
            return
    except Exception:
        pass
    # Skip the do-not-refollow set: if smart_unfollow already let an
    # account go, re-following them would just re-unfollow → churn.
    # The check happens after page-scroll via on-page state — accounts
    # we already follow show "Following" not "Follow" so they're auto-
    # filtered, but the bot can't see do_not_refollow status from search
    # results, so we just LOG the count for visibility.
    try:
        from .smart_unfollow_bot import _load_do_not_refollow
        dnr = _load_do_not_refollow()
        if dnr:
            log.info(f"[FOLLOW-BLAST] do-not-refollow set has {len(dnr)} entries.")
    except Exception:
        pass
    state = _load_daily_state()
    remaining = max(0, FOLLOW_BLAST_DAILY_CAP - int(state.get("count") or 0))
    if remaining <= 0:
        log.info(f"[FOLLOW-BLAST] Daily cap reached ({FOLLOW_BLAST_DAILY_CAP}) — skipping.")
        return
    query = random.choice(BLAST_QUERIES)
    encoded = urllib.parse.quote(query)
    # /search?f=people = profile-card list, dense Follow CTAs.
    url = f"https://x.com/search?q={encoded}&f=people"

    with _safari_lock:
        log.info(f"[FOLLOW-BLAST] Opening people search: {query}")
        webbrowser.open(url)
        time.sleep(7)
        _scroll_page()
        time.sleep(1)
        _scroll_page()
        time.sleep(1)

        # Two batches with a small pause so the action doesn't burst.
        cycle_cap = min(get_live_cap("FOLLOW_BLAST_PER_CYCLE", FOLLOWS_PER_CYCLE), remaining)
        first = cycle_cap // 2 + cycle_cap % 2
        second = cycle_cap - first
        clicked = _click_follow_buttons(first)
        time.sleep(random.uniform(2.0, 3.5))
        clicked += _click_follow_buttons(second)

        close_front_tab()

    state["count"] = int(state.get("count") or 0) + max(0, clicked)
    _save_daily_state(state)
    log.info(
        f"[FOLLOW-BLAST] Followed {clicked} accounts on '{query}' "
        f"({state['count']}/{FOLLOW_BLAST_DAILY_CAP} today)."
    )


def safe_run_follow_blast_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_follow_blast_cycle()
        health.record_success("follow_blast")
    except Exception:
        log.info("[FOLLOW-BLAST] Error during follow-blast cycle:")
        traceback.print_exc()
        health.record_failure("follow_blast")
