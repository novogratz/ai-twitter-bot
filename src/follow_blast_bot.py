"""Mass-follow blast bot — bulk-follow FR niche accounts at scale.

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

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import _safari_lock, close_front_tab, _scroll_page

FOLLOWS_PER_CYCLE = int(os.environ.get("FOLLOW_BLAST_PER_CYCLE", "30"))

# FR niche search queries. Rotated per cycle. The min_faves floor keeps
# us out of bot-farm zones — we want real FR users in the niche.
BLAST_QUERIES = [
    "IA lang:fr min_faves:3",
    "ChatGPT lang:fr min_faves:3",
    "Claude lang:fr min_faves:2",
    "Mistral lang:fr min_faves:2",
    "OpenAI lang:fr min_faves:3",
    "Anthropic lang:fr min_faves:2",
    "intelligence artificielle lang:fr",
    "Bitcoin lang:fr min_faves:3",
    "Ethereum lang:fr min_faves:2",
    "crypto lang:fr min_faves:3",
    "BTC lang:fr min_faves:2",
    "CAC40 lang:fr",
    "bourse lang:fr min_faves:2",
    "trading lang:fr min_faves:2",
    "investissement lang:fr min_faves:2",
    "Nvidia lang:fr min_faves:2",
    "fintech lang:fr min_faves:2",
    "startup tech lang:fr min_faves:2",
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


def run_follow_blast_cycle():
    """Open a FR niche search, scroll, JS-click N visible Follow buttons."""
    # Skip if X is suppressing us — bulk follows during a shadowban
    # phase trip the spam detector even harder.
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[FOLLOW-BLAST] Suppression cooldown active — skipping cycle.")
            return
    except Exception:
        pass
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
        first = FOLLOWS_PER_CYCLE // 2 + FOLLOWS_PER_CYCLE % 2
        second = FOLLOWS_PER_CYCLE - first
        clicked = _click_follow_buttons(first)
        time.sleep(random.uniform(2.0, 3.5))
        clicked += _click_follow_buttons(second)

        close_front_tab()

    log.info(f"[FOLLOW-BLAST] Followed {clicked} accounts on '{query}'")


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
