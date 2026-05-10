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

from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import _safari_lock, close_front_tab, _scroll_page

LIKE_QUERIES = [
    # FR AI
    "IA lang:fr min_faves:5",
    "ChatGPT lang:fr min_faves:5",
    "Claude lang:fr min_faves:3",
    "Mistral lang:fr min_faves:3",
    "OpenAI lang:fr min_faves:5",
    "Anthropic lang:fr min_faves:3",
    "intelligence artificielle lang:fr",
    "Hugging Face lang:fr",
    # FR crypto
    "Bitcoin lang:fr min_faves:5",
    "Ethereum lang:fr min_faves:3",
    "crypto lang:fr min_faves:5",
    "BTC lang:fr min_faves:3",
    # FR bourse
    "CAC40 lang:fr",
    "bourse lang:fr min_faves:3",
    "Nvidia lang:fr min_faves:3",
    "trading lang:fr min_faves:3",
    "investissement lang:fr min_faves:3",
    "actions lang:fr min_faves:3",
    # EN/global crypto + AI signals that train For You hard
    "Bitcoin OR BTC min_faves:20",
    "Ethereum OR ETH min_faves:15",
    "crypto OR stablecoin OR DeFi min_faves:15",
    "OpenAI OR Anthropic OR ChatGPT min_faves:20",
    "Nvidia OR GPU OR datacenter min_faves:20",
    "AI agents OR LLM min_faves:20",
    "NASDAQ OR stocks OR earnings min_faves:20",
    "Tesla OR Microsoft OR Meta AI min_faves:20",
]
TOP_TAB_PROBABILITY = float(os.environ.get("LIKE_TOP_TAB_PROBABILITY", "0.55"))

LIKES_PER_CYCLE = int(os.environ.get("LIKE_BOT_PER_CYCLE", "18"))


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


def run_like_cycle():
    """Open a niche search, scroll, JS-click N visible like buttons."""
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
        first = LIKES_PER_CYCLE // 2 + LIKES_PER_CYCLE % 2
        second = LIKES_PER_CYCLE - first
        clicked_total += _click_likes_on_page(first)
        time.sleep(random.uniform(1.5, 3.0))
        clicked_total += _click_likes_on_page(second)

        close_front_tab()

    log.info(f"[LIKE] Liked {clicked_total} tweets on '{query}' ({tab})")


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
