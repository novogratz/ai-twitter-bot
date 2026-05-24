"""Like-aggressive bot — bulk-like crypto / AI / bourse tweets every cycle.

Why: a like is the cheapest social signal on X. Each like sends a
notification → the recipient checks their notifs → many click through
to /kzer_ai. With ~20 likes per cycle and ~4 cycles per hour, that's
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

from .config import _PROJECT_ROOT, get_live_cap
from .logger import log
from .twitter_client import _safari_lock, close_front_tab, _scroll_page

LIKE_QUERIES = [
    "Bitcoin OR BTC lang:en min_faves:50",
    "Ethereum OR ETH lang:en min_faves:50",
    "crypto OR stablecoin OR DeFi lang:en min_faves:50",
    "OpenAI OR Anthropic OR ChatGPT lang:en min_faves:50",
    "Nvidia OR GPU OR datacenter lang:en min_faves:50",
    "AI agents OR LLM lang:en min_faves:50",
    "NASDAQ OR stocks OR earnings lang:en min_faves:50",
    "Tesla OR Microsoft OR Meta AI lang:en min_faves:50",
]
TOP_TAB_PROBABILITY = float(os.environ.get("LIKE_TOP_TAB_PROBABILITY", "0.55"))

LIKES_PER_CYCLE = int(os.environ.get("LIKE_BOT_PER_CYCLE", "18"))
LIKE_BOT_DAILY_CAP = int(os.environ.get("LIKE_BOT_DAILY_CAP", "1800"))
LIKE_BOT_STATE_FILE = os.path.join(_PROJECT_ROOT, "like_bot_state.json")


def _click_likes_on_page(max_clicks: int) -> int:
    """JS: find unliked like buttons on the page and click them."""
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
    remaining = max(0, LIKE_BOT_DAILY_CAP - int(state.get("count") or 0))
    if remaining <= 0:
        log.info(f"[LIKE] Daily cap reached ({LIKE_BOT_DAILY_CAP}) — skipping.")
        return
    query = random.choice(LIKE_QUERIES)
    encoded = urllib.parse.quote(query)
    tab = "top" if random.random() < TOP_TAB_PROBABILITY else "live"
    url = f"https://x.com/search?q={encoded}&f={tab}"

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
        cycle_cap = min(get_live_cap("LIKE_BOT_PER_CYCLE", LIKES_PER_CYCLE), remaining)
        first = cycle_cap // 2 + cycle_cap % 2
        second = cycle_cap - first
        clicked_total += _click_likes_on_page(first)
        time.sleep(random.uniform(1.5, 3.0))
        clicked_total += _click_likes_on_page(second)

        close_front_tab()

    state["count"] = int(state.get("count") or 0) + max(0, clicked_total)
    _save_daily_state(state)
    log.info(
        f"[LIKE] Liked {clicked_total} tweets on '{query}' ({tab}) "
        f"({state['count']}/{LIKE_BOT_DAILY_CAP} today)."
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
