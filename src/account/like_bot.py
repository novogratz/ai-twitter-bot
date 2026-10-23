"""Like-aggressive bot — like AI infra / asymmetric investing tweets every cycle.

Why: a like is the cheapest social signal on X. Each like sends a
notification → the recipient checks their notifs → many click through
to the Account's profile.

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
import random
import traceback
import urllib.parse

from ..core import account, config, settings
from ..core.logger import log
from ..core.state_store import GUARDED, StateFile
from ..guards import active_hours
from ..x import twitter_client
from ..x.twitter_client import LikeOutcome

# Guarded: the only record of the daily like cap.
LIKE_BOT_STATE = StateFile("like_bot_state.json", {}, GUARDED)


def _likes_per_cycle() -> int:
    return settings.get("LIKE_BOT_PER_CYCLE")


def _daily_cap() -> int:
    return settings.get("LIKE_BOT_DAILY_CAP")


def _cycle_seconds() -> float:
    return settings.get("LIKE_BOT_CYCLE_SECONDS")


def _load_daily_state() -> dict:
    today = active_hours.today_iso()
    state = LIKE_BOT_STATE.read()
    if active_hours.is_past_day(state.get("date")):
        return {"date": today, "count": 0}
    current = {"date": today, "count": int(state.get("count") or 0)}
    if state.get("date") != today:
        # Stamped today by the Mac's clock, ahead of Toronto's: restamp it,
        # or tomorrow would start with today's count.
        _save_daily_state(current)
    return current


def _save_daily_state(state: dict) -> None:
    LIKE_BOT_STATE.write(state)


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
    query = random.choice(account.current().searches.likes)
    encoded = urllib.parse.quote(query)
    tab = "top" if random.random() < settings.get("LIKE_TOP_TAB_PROBABILITY") else "live"
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
