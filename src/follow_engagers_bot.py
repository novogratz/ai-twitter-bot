"""Follow-your-engagers — the highest follow-back-probability follows.

Operator 2026-07-19 ("anything else to improve likes and follows?" → "do
all of them"): the people most likely to follow us back are the ones who
just engaged US. We already have them on disk for free: every Debate turn
the account shipped (replyback or debate) leaves a ledger row naming the
Engager it answered. This lane follows a small daily trickle of them
through the full follow chokepoint with `engager=True` (size/niche gates
skipped — their behavior proves both — English gate + caps + spacing +
churn kept).

No new Safari scraping: the data source is the action ledger.
"""
import json
import os
import traceback
from datetime import date, timedelta

from .guards import action_guard
from .x import x_urls
from .core.config import _PROJECT_ROOT, BLOCKLIST, BOT_HANDLE
from .core.logger import log

# replied_back.json stopped being written on 2026-09-23 (issue #100): the
# ledger's Debate turns replaced it. Its Engagers are read until they age out
# of the ledger's 90 days; delete this fallback and the file after 2026-12-22.
FROZEN_REPLIED_BACK_FILE = os.path.join(_PROJECT_ROOT, "replied_back.json")
STATE_FILE = os.path.join(_PROJECT_ROOT, "follow_engagers_state.json")

# Big-media accounts get Debate turns too (we reply back under news posts)
# — following @business back is pointless for follow-backs.
_SKIP_HANDLES = {"business", "cnbc", "reuters", "wsj", "ft", "bloomberg",
                 "watcherguru", "zerohedge", "unusual_whales", "cointelegraph"}


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        if isinstance(st, dict):
            return st
    except (OSError, json.JSONDecodeError):
        pass
    return {"date": "", "count_today": 0, "attempted": []}


def _save_state(st: dict) -> None:
    st["attempted"] = st.get("attempted", [])[-2000:]
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=1)


def _frozen_engager_handles() -> list:
    """Newest-first handles from the frozen replied_back.json URLs posted
    within the ledger's 90 days, the same window as the Debate turns."""
    try:
        with open(FROZEN_REPLIED_BACK_FILE) as f:
            urls = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(urls, list):
        return []
    handles = []
    for u in map(str, reversed(urls)):
        handle, age = x_urls.author(u), x_urls.age(u)
        if handle and age is not None and age <= timedelta(days=90):
            handles.append(handle)
    return handles


def _engager_handles(limit: int = 200) -> list:
    """Newest-first Engagers: Debate turn authors from the ledger, then the
    frozen replied_back.json."""
    handles = dict.fromkeys(action_guard.debate_turn_authors() + _frozen_engager_handles())
    return list(handles)[:limit]


def run_follow_engagers_cycle():
    if os.environ.get("ENABLE_FOLLOW_ENGAGERS", "1") != "1":
        log.info("[FOLLOW-ENGAGERS] Disabled. Skipping.")
        return
    per_day = int(os.environ.get("FOLLOW_ENGAGERS_PER_DAY", "10"))
    per_cycle = int(os.environ.get("FOLLOW_ENGAGERS_PER_CYCLE", "2"))

    st = _load_state()
    today = date.today().isoformat()
    if st.get("date") != today:
        st["date"] = today
        st["count_today"] = 0
    if st["count_today"] >= per_day:
        log.info(f"[FOLLOW-ENGAGERS] Daily cap reached ({per_day}). Skipping.")
        return

    attempted = set(st.get("attempted", []))
    own = BOT_HANDLE.lower()
    followed = 0

    from .x.twitter_client import DRY_RUN_RECORDED, follow_account
    # 2026-07-28 fix: 262 candidates were burned into `attempted` by
    # TRANSIENT policy refusals (the 3500 total-following ceiling blocked
    # every follow for days). Pre-check the policy CHEAPLY: a transient
    # refusal (spacing gap, daily cap, total ceiling) ends the cycle
    # WITHOUT burning the candidate; only an actual attempt (which caches
    # its own quality-reject) marks a handle attempted.
    _TRANSIENT = ("too soon", "cap reached", "ceiling")
    for h in _engager_handles():
        if followed >= per_cycle or st["count_today"] >= per_day:
            break
        if h == own or h in BLOCKLIST or h in _SKIP_HANDLES or h in attempted:
            continue
        ok, why = action_guard.can_follow(h, reciprocal=True)
        if not ok:
            if any(t in why for t in _TRANSIENT):
                log.info(f"[FOLLOW-ENGAGERS] Policy transient ({why}) — ending cycle, candidates preserved.")
                break
            # permanent refusal (churn/whitelist policy) — burn this one only
            attempted.add(h)
            st["attempted"] = list(attempted)
            continue
        result = follow_account(h, engager=True)
        if result is DRY_RUN_RECORDED:
            # Followed no one: the Engager stays fresh and uncounted, but
            # the dry run still stops at the live per-cycle bound.
            followed += 1
            continue
        attempted.add(h)
        st["attempted"] = list(attempted)
        if result:
            followed += 1
            st["count_today"] += 1
        _save_state(st)

    _save_state(st)
    log.info(f"[FOLLOW-ENGAGERS] Cycle done: {followed} engagers followed "
             f"({st['count_today']}/{per_day} today).")


def safe_run_follow_engagers_cycle():
    from .core import health
    try:
        run_follow_engagers_cycle()
        health.record_success("follow_engagers")
    except Exception:
        log.info("[FOLLOW-ENGAGERS] Error during cycle:")
        traceback.print_exc()
        health.record_failure("follow_engagers")
