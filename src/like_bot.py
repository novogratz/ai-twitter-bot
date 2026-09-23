"""Like-aggressive bot — bulk-like AI infra / asymmetric investing tweets every cycle.

Why: a like is the cheapest social signal on X. Each like sends a
notification → the recipient checks their notifs → many click through
to /TheAIShrink. With ~20 likes per cycle and ~4 cycles per hour, that's
~80 outbound notifications/hour.

Strategy:
  - Every 15 min, pick a niche search query (rotating).
  - Open /search?q=... in live or top mode.
  - JS-click N visible like buttons (skip already-liked = unlike state).
  - No replies, no follows — pure engagement noise. Cheap and effective.

Rate-conscious: 15-20 likes/cycle × 4 cycles/hour = ~80/hour. X soft-rate
on likes is ~1000/hour. We're far below.
"""
import os
import random
import subprocess
import tempfile
import time
import traceback
import urllib.parse
import webbrowser

from .active_hours import require_active
from . import config
from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import _safari_lock, close_front_tab, _scroll_page

LIKE_QUERIES = [
    "AI datacenter OR power demand lang:en min_faves:50",
    "megawatt OR gigawatt OR nuclear AI lang:en min_faves:50",
    "CoreWeave OR CRWV OR APLD lang:en min_faves:50",
    "IREN OR HIVE OR TeraWulf OR WULF lang:en min_faves:50",
    "TAO OR Bittensor OR decentralized compute lang:en min_faves:50",
    "Nvidia OR GPU OR compute cluster lang:en min_faves:50",
    "robotics OR humanoid robots OR frontier tech lang:en min_faves:50",
    "SpaceX OR Starlink OR space infrastructure lang:en min_faves:50",
]
TOP_TAB_PROBABILITY = float(os.environ.get("LIKE_TOP_TAB_PROBABILITY", "0.55"))
LIKE_BOT_STATE_FILE = os.path.join(_PROJECT_ROOT, "like_bot_state.json")


def _likes_per_cycle() -> int:
    # Environment only, read each cycle: live_strategy.json must not raise it.
    return int(os.environ.get("LIKE_BOT_PER_CYCLE", "40"))


def _daily_cap() -> int:
    return int(os.environ.get("LIKE_BOT_DAILY_CAP", "3000"))


def _click_likes_on_page(max_clicks: int) -> int:
    """JS: find unliked like buttons on the page and click them."""
    # This path runs osascript itself, so it must check the clock and the
    # stop the way twitter_client._run_applescript does.
    require_active()
    js_code = f"""
    (function() {{
        var buttons = document.querySelectorAll('[data-testid="like"]');
        var clicked = 0;
        for (var i = 0; i < buttons.length && clicked < {max_clicks}; i++) {{
            try {{
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
    import json
    from datetime import date
    today = date.today().isoformat()
    if not os.path.exists(LIKE_BOT_STATE_FILE):
        return {"date": today, "count": 0}
    try:
        with open(LIKE_BOT_STATE_FILE, "r") as f:
            state = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {"date": today, "count": 0}
    if state.get("date") != today:
        return {"date": today, "count": 0}
    return {"date": today, "count": int(state.get("count") or 0)}


def _save_daily_state(state: dict) -> None:
    import json
    with open(LIKE_BOT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def run_like_cycle():
    """Open a niche search, scroll, JS-click N visible like buttons."""
    state = _load_daily_state()
    daily_cap = _daily_cap()
    remaining = max(0, daily_cap - int(state.get("count") or 0))
    if remaining <= 0:
        log.info(f"[LIKE] Daily cap reached ({daily_cap}) — skipping.")
        return
    cycle_cap = min(_likes_per_cycle(), remaining)
    query = random.choice(LIKE_QUERIES)
    encoded = urllib.parse.quote(query)
    tab = "top" if random.random() < TOP_TAB_PROBABILITY else "live"
    url = f"https://x.com/search?q={encoded}&f={tab}"
    if config.dry_run():
        log.info(f"[LIKE][DRY_RUN] would like up to {cycle_cap} "
                 f"tweets on '{query}' ({tab}).")
        return

    with _safari_lock:
        log.info(f"[LIKE] Opening {tab} search: {query}")
        webbrowser.open(url)
        time.sleep(7)

        # Scroll twice to populate ~20-30 articles.
        _scroll_page()
        time.sleep(1)
        _scroll_page()
        time.sleep(1)

        # Pause briefly between batches so the action doesn't burst.
        clicked_total = 0
        # Two batches of half so we space out the JS clicks slightly.
        first = cycle_cap // 2 + cycle_cap % 2
        second = cycle_cap - first
        try:
            clicked_total += _click_likes_on_page(first)
            time.sleep(random.uniform(1.5, 3.0))
            clicked_total += _click_likes_on_page(second)
        finally:
            # A stop between batches must still count the first batch.
            state["count"] = int(state.get("count") or 0) + max(0, clicked_total)
            _save_daily_state(state)

        close_front_tab()

    log.info(
        f"[LIKE] Liked {clicked_total} tweets on '{query}' ({tab}) "
        f"({state['count']}/{daily_cap} today)."
    )


def safe_run_like_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_like_cycle()
        health.record_success("like")
    except Exception:
        log.info("[LIKE] Error during like cycle:")
        traceback.print_exc()
        health.record_failure("like")
