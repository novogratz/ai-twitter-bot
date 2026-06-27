"""Big-account topic-discovery follow bot (rebuilt 2026-06-12).

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

FOLLOWS_PER_CYCLE = int(os.environ.get("FOLLOW_BLAST_PER_CYCLE", "2"))
FOLLOW_BLAST_DAILY_CAP = int(os.environ.get("FOLLOW_BLAST_DAILY_CAP", "25"))
FOLLOW_BLAST_STATE_FILE = os.path.join(_PROJECT_ROOT, "follow_blast_state.json")

# EN big-topic search queries (operator 2026-06-12: "search for new topics
# then follow the big accounts"). High min_faves = the authors are big.
# 2026-06-27 operator: "target accounts in AI industry" + "don't target
# small accounts" — every query is AI-industry now (no pure crypto/macro/
# finance lanes); the FOLLOW_MIN_FOLLOWERS gate filters out small ones.
BLAST_QUERIES = [
    "OpenAI OR Anthropic OR xAI OR Gemini OR Mistral lang:en min_faves:500",
    "\"AI agents\" OR AGI OR \"reasoning model\" OR LLM lang:en min_faves:500",
    "Nvidia OR \"AI capex\" OR \"AI datacenter\" OR TSMC OR CoreWeave lang:en min_faves:500",
    "\"AI stocks\" OR Palantir OR \"AI trade\" OR \"AI bubble\" lang:en min_faves:500",
    "ChatGPT OR Claude OR \"AI tools\" OR \"AI startup\" lang:en min_faves:500",
    "\"machine learning\" OR \"AI research\" OR \"AI model\" OR \"open source AI\" lang:en min_faves:300",
    "\"AI safety\" OR \"AI alignment\" OR robotics OR \"humanoid robot\" lang:en min_faves:300",
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


def run_follow_blast_cycle():
    """Search one big EN niche topic, follow the authors of the top posts
    through the full follow chokepoint (caps, spacing, churn, quality gate)."""
    from . import config as _cfg
    if not _cfg.ENABLE_FOLLOW_BLAST:
        log.info("[FOLLOW-BLAST] Disabled (ENABLE_FOLLOW_BLAST=0).")
        return
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[FOLLOW-BLAST] Suppression cooldown active — skipping cycle.")
            return
    except Exception:
        pass
    state = _load_daily_state()
    remaining = max(0, FOLLOW_BLAST_DAILY_CAP - int(state.get("count") or 0))
    if remaining <= 0:
        log.info(f"[FOLLOW-BLAST] Daily cap reached ({FOLLOW_BLAST_DAILY_CAP}) — skipping.")
        return
    # Cheap pre-check: if the chokepoint would refuse on pacing anyway,
    # save the whole Safari search for a cycle that can convert.
    from . import action_guard
    ok, why = action_guard.can_follow("probe_pacing_only")
    if not ok and "too soon" in why:
        log.info(f"[FOLLOW-BLAST] Spacing not elapsed ({why}) — skipping cycle cheap.")
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
    # biggest parent post first.
    def _likes(t):
        try:
            return int(t.get("likes") or 0)
        except (TypeError, ValueError):
            return 0

    seen = set()
    candidates = []
    for t in sorted(tweets, key=_likes, reverse=True):
        url = t.get("url", "") or ""
        try:
            handle = url.split("x.com/")[1].split("/")[0]
        except IndexError:
            continue
        h = handle.lower()
        if not handle or h in seen or h == (BOT_HANDLE or "").lower():
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
        f"[FOLLOW-BLAST] Followed {followed} big account(s) from '{query}' "
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
