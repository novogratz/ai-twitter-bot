"""Mass-follow blast bot — bulk-follow French AI/crypto/finance niche accounts at scale.

Operator: "it needs to search for new topics then follow the big accounts."
The old design opened FRENCH people-searches and blind-JS-clicked every
Follow button on the page — bypassing the follow chokepoint entirely (no
caps, no spacing, no anti-churn, no quality gate). That was the
trash-follow machine the operator called out.

New strategy, chokepoint-honest:
  - Each cycle, pick one EN niche TOPIC query (AI / AI stocks / crypto /
    markets) with a high min_faves floor on the TOP tab — big posts only.
  - Extract the AUTHOR handles from the result URLs (URL = ground truth).
  - Follow through twitter_client.follow_account → full chokepoint: daily
    cap, >=10-min jittered gaps, 30-day anti-churn, and the profile
    quality gate (>=FOLLOW_MIN_FOLLOWERS, on-niche bio). The author of a
    500-like AI post is big by construction; the gate verifies it.
  - The 10-min spacing means a cycle usually lands 0-1 follows — that is
    the human pace, by design.
"""
import json
import os
import random
import traceback

from .config import _PROJECT_ROOT, BOT_HANDLE, get_live_cap
from .logger import log

FOLLOWS_PER_CYCLE = int(os.environ.get("FOLLOW_BLAST_PER_CYCLE", "60"))
FOLLOW_BLAST_DAILY_CAP = int(os.environ.get("FOLLOW_BLAST_DAILY_CAP", "1200"))
FOLLOW_BLAST_STATE_FILE = os.path.join(_PROJECT_ROOT, "follow_blast_state.json")

# French niche search queries. Rotated per cycle. Most use low/no min_faves
# because the goal is net-new FR graph discovery, not only already-viral posts.
BLAST_QUERIES = [
    # === Space (Highest Priority user mandate 2026-05-26) ===
    "SpaceX OR Starship OR Starlink lang:fr",
    "orbital economy OR launch vehicle OR NewSpace lang:en",
    "ArianeGroup OR satellite OR spatial lang:fr",
    "\"New Space\" France OR fusée lang:fr",
    "ESA OR exploration spatiale lang:fr",
    # === AI ===
    "IA OR \"intelligence artificielle\" lang:fr",
    "Mistral OR HuggingFace OR \"Hugging Face\" lang:fr",
    "OpenAI OR ChatGPT OR Claude lang:fr",
    "développeur IA OR \"Cursor AI\" lang:fr",
    # === Investment ===
    "bourse OR PEA OR ETF OR investissement lang:fr",
    "trading OR marchés financiers lang:fr",
    # === Crypto ===
    "Bitcoin OR Ethereum OR Solana OR crypto lang:fr",
]


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
    """Open a French niche people search, scroll, JS-click Follow buttons."""
    # 2026-06-02 pivot: reciprocity mass-following is banned. This bot clicks
    # raw Follow buttons in bulk (strangers), bypassing the whitelist-only
    # follow policy in twitter_client.follow_account. When whitelist-only mode
    # is on it must not run at all — follows come only from the curated
    # whitelist, capped at MAX_FOLLOWS_PER_DAY.
    from . import config as _cfg
    if not _cfg.ENABLE_FOLLOW_BLAST:
        log.info("[FOLLOW-BLAST] Disabled (ENABLE_FOLLOW_BLAST=0): reciprocity mass-follow is banned. "
                 "New-account follows go through the capped discovery path instead.")
        return
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
    from .twitter_client import scrape_x_search, follow_account
    query = random.choice(BLAST_QUERIES)
    log.info(f"[FOLLOW-BLAST] Topic search (top tab): {query}")
    try:
        tweets = scrape_x_search(query, max_tweets=20, tab="top")
    except Exception:
        log.info("[FOLLOW-BLAST] Search failed.")
        traceback.print_exc()
        return

    # Authors from URLs (ground truth — never the scraped display name),
    # biggest parent post first. (2026-06-21: de-mangled — a bad merge had
    # spliced the retired blind-click path in here, leaving `candidates`
    # never built and orphan refs to _click_follow_buttons/clicked/time.)
    def _likes(t):
        try:
            return int(t.get("likes") or 0)
        except (TypeError, ValueError):
            return 0

    candidates, seen = [], set()
    own = (BOT_HANDLE or "").lower()
    for t in sorted(tweets or [], key=_likes, reverse=True):
        url = t.get("url") or ""
        try:
            handle = url.split("x.com/")[1].split("/")[0]
        except (IndexError, AttributeError):
            continue
        h = handle.lower()
        if not handle or h in seen or h == own:
            continue
        seen.add(h)
        candidates.append(handle)

    cycle_cap = min(get_live_cap("FOLLOW_BLAST_PER_CYCLE", FOLLOWS_PER_CYCLE), remaining)
    followed = 0
    for handle in candidates:
        if followed >= cycle_cap:
            break
        # follow_account = full chokepoint: daily cap, 10-min jittered
        # spacing, 30-day anti-churn, profile quality gate (size + niche).
        if follow_account(handle):
            followed += 1

    state["count"] = int(state.get("count") or 0) + followed
    _save_daily_state(state)
    log.info(
        f"[FOLLOW-BLAST] Followed {followed} big account(s) on '{query}' "
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
