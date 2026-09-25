"""Follow-your-engagers — the highest follow-back-probability follows.

Operator 2026-07-19 ("anything else to improve likes and follows?" → "do
all of them"): the people most likely to follow us back are the ones who
just engaged US. We already have them on disk for free: every Debate turn
the account shipped (replyback or debate) leaves a ledger row naming the
Engager it answered. This lane follows a small daily trickle of them
through the full follow chokepoint, which finds them Engagers in the same
ledger (follow_policy.engagers): size/niche gates skipped — their behavior
proves both — English gate + caps + spacing + churn kept.

No new Safari scraping: the data source is the action ledger.
"""
import os
import traceback
from datetime import date

from ..guards import follow_policy
from ..core.config import BLOCKLIST, BOT_HANDLE
from ..core.logger import log
from ..core.state_store import GUARDED, StateFile

# Guarded: it alone holds this job's daily cap and the handles already tried.
STATE = StateFile("follow_engagers_state.json",
                  {"date": "", "count_today": 0, "attempted": []}, GUARDED)

# Big-media accounts get Debate turns too (we reply back under news posts)
# — following @business back is pointless for follow-backs.
_SKIP_HANDLES = {"business", "cnbc", "reuters", "wsj", "ft", "bloomberg",
                 "watcherguru", "zerohedge", "unusual_whales", "cointelegraph"}


def _load_state() -> dict:
    return STATE.read()


def _save_state(st: dict) -> None:
    st["attempted"] = st.get("attempted", [])[-2000:]
    STATE.write(st)


def _engager_handles(limit: int = 200) -> list:
    """Newest-first Engagers, as the follow policy knows them."""
    return follow_policy.engagers()[:limit]


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

    from ..x.twitter_client import FollowOutcome, follow_account
    # 2026-07-28 fix: 262 candidates were burned into `attempted` by
    # TRANSIENT policy refusals (the 3500 total-following ceiling blocked
    # every follow for days). A refusal on the follow budget (spacing, daily
    # cap, total ceiling) ends the cycle WITHOUT burning the candidate; any
    # other outcome marks the handle attempted. An unreadable whitelist
    # raises out of the cycle, before any candidate is marked.
    for h in _engager_handles():
        if followed >= per_cycle or st["count_today"] >= per_day:
            break
        if h == own or h in BLOCKLIST or h in _SKIP_HANDLES or h in attempted:
            continue
        result = follow_account(h)
        if result.is_budget_refusal:
            log.info(f"[FOLLOW-ENGAGERS] Follow budget: {result.value} — ending cycle, candidates preserved.")
            break
        if result is FollowOutcome.DRY_RUN:
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
    from ..core import health
    try:
        run_follow_engagers_cycle()
        health.record_success("follow_engagers")
    except Exception:
        log.info("[FOLLOW-ENGAGERS] Error during cycle:")
        traceback.print_exc()
        health.record_failure("follow_engagers")
