"""Like-aggressive bot — like AI infra / asymmetric investing tweets every cycle.

Why: a like is the cheapest social signal on X. Each like sends a
notification → the recipient checks their notifs → many click through
to /TheAIShrink.

Strategy:
  - Every 4 min, pick a niche search query (rotating).
  - Open /search?q=... in live or top mode.
  - Like up to LIKE_BOT_PER_CYCLE listed posts through
    twitter_client.like_search_posts, so each like goes through like_tweet:
    liked cache, Blocked accounts, click then confirmation, ledger row.
    No like starts after LIKE_BOT_CYCLE_SECONDS, so the Safari lock is
    released for the reply jobs.
  - No replies, no follows — pure engagement noise. Cheap and effective.

Rate-conscious: 10 likes per cycle by default, at most LIKE_BOT_DAILY_CAP
(500) a day.
"""
import os
import random
import traceback
import urllib.parse

from ..core import config
from ..core.config import _PROJECT_ROOT
from ..core.logger import log
from ..x import twitter_client
from ..x.twitter_client import LikeOutcome

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
    return int(os.environ.get("LIKE_BOT_PER_CYCLE", "10"))


def _daily_cap() -> int:
    return int(os.environ.get("LIKE_BOT_DAILY_CAP", "500"))


def _cycle_seconds() -> float:
    return float(os.environ.get("LIKE_BOT_CYCLE_SECONDS", "30"))


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
    `like_tweet`. The daily count adds the LIKED and UNCONFIRMED outcomes."""
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

    log.info(f"[LIKE] {tab} search: {query}")
    outcomes = []
    try:
        twitter_client.like_search_posts(url, cycle_cap, _cycle_seconds(), outcomes)
    finally:
        # The walk fills `outcomes` as it goes, so a stop mid-walk still
        # counts what it clicked. An unconfirmed click may have landed on X:
        # it counts toward the cap though it has no ledger row.
        clicked = sum(o in (LikeOutcome.LIKED, LikeOutcome.UNCONFIRMED) for o in outcomes)
        state["count"] = int(state.get("count") or 0) + clicked
        _save_daily_state(state)

    liked = sum(o is LikeOutcome.LIKED for o in outcomes)
    log.info(
        f"[LIKE] Liked {liked} tweets on '{query}' ({tab}) "
        f"[{twitter_client.like_summary(outcomes)}] "
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
