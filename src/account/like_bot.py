"""Like-aggressive bot — bulk-like AI infra / asymmetric investing tweets every cycle.

Why: a like is the cheapest social signal on X. Each like sends a
notification → the recipient checks their notifs → many click through
to /TheAIShrink. With ~20 likes per cycle and ~4 cycles per hour, that's
~80 outbound notifications/hour.

Strategy:
  - Every 15 min, pick a niche search query (rotating).
  - Open /search?q=... in live or top mode.
  - Like up to N listed posts through twitter_client._like_posts_on_page,
    so each like goes through like_tweet: liked cache, Blocked accounts,
    click then confirmation, ledger row.
  - No replies, no follows — pure engagement noise. Cheap and effective.

Rate-conscious: 15-20 likes/cycle × 4 cycles/hour = ~80/hour. X soft-rate
on likes is ~1000/hour. We're far below.
"""
import os
import random
import time
import traceback
import urllib.parse
import webbrowser

from ..core import config
from ..core.config import _PROJECT_ROOT
from ..core.logger import log
from ..guards import action_guard
from ..x import twitter_client
from ..x.safari import _safari_lock, close_front_tab, _scroll_page

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
    """Open a niche search, scroll, like up to N listed posts through
    `like_tweet`. The daily count adds the LIKED outcomes only."""
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

        outcomes = []
        liked_before = action_guard.count_today(action_guard.LIKE)
        try:
            outcomes = twitter_client._like_posts_on_page(
                cycle_cap, lambda post: True,
                page_ok=lambda page: urllib.parse.urlparse(page).path == "/search")
        finally:
            # like_tweet writes one ledger row per LIKED and the Safari lock
            # keeps every other like out, so the ledger delta still counts the
            # likes that shipped when a stop interrupts the walk.
            liked = max(0, action_guard.count_today(action_guard.LIKE) - liked_before)
            state["count"] = int(state.get("count") or 0) + liked
            _save_daily_state(state)

        close_front_tab()

    log.info(
        f"[LIKE] Liked {liked} tweets on '{query}' ({tab}) "
        f"[{twitter_client._like_summary(outcomes)}] "
        f"({state['count']}/{daily_cap} today)."
    )


def safe_run_like_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_like_cycle()
        health.record_success("like")
    except Exception:
        log.info("[LIKE] Error during like cycle:")
        traceback.print_exc()
        health.record_failure("like")
