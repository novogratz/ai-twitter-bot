"""Follow-your-engagers — the highest follow-back-probability follows.

Operator 2026-07-19 ("anything else to improve likes and follows?" → "do
all of them"): the people most likely to follow us back are the ones who
just engaged US. We already have them on disk for free: replied_back.json
holds the URLs of replies we replied back to — each URL's author is a
proven engager. This lane follows a small daily trickle of them through
the full follow chokepoint with `engager=True` (size/niche gates skipped —
their behavior proves both — English gate + caps + spacing + churn kept).

No new Safari scraping: the data source is a state file the replyback bot
already maintains.
"""
import json
import os
import re
import traceback
from datetime import date

from .config import _PROJECT_ROOT, BLOCKLIST, BOT_HANDLE
from .logger import log

REPLIED_BACK_FILE = os.path.join(_PROJECT_ROOT, "replied_back.json")
STATE_FILE = os.path.join(_PROJECT_ROOT, "follow_engagers_state.json")

_HANDLE_RE = re.compile(r"x\.com/([A-Za-z0-9_]{1,15})/status/")

# Big-media engager URLs sneak into replied_back (we reply back under news
# posts too) — following @business back is pointless for follow-backs.
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


def _engager_handles(limit: int = 200) -> list:
    """Newest-first engager handles from replied_back.json URLs."""
    try:
        with open(REPLIED_BACK_FILE) as f:
            urls = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(urls, list):
        return []
    handles, seen = [], set()
    for u in reversed(urls[-limit:]):  # newest engagers first
        m = _HANDLE_RE.search(str(u))
        if not m:
            continue
        h = m.group(1).lower()
        if h in seen:
            continue
        seen.add(h)
        handles.append(h)
    return handles


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

    from .twitter_client import follow_account
    from .action_guard import can_follow
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
        ok, why = can_follow(h, reciprocal=True)
        if not ok:
            if any(t in why for t in _TRANSIENT):
                log.info(f"[FOLLOW-ENGAGERS] Policy transient ({why}) — ending cycle, candidates preserved.")
                break
            # permanent refusal (churn/whitelist policy) — burn this one only
            attempted.add(h)
            st["attempted"] = list(attempted)
            continue
        attempted.add(h)
        st["attempted"] = list(attempted)
        if follow_account(h, engager=True):
            followed += 1
            st["count_today"] += 1
        _save_state(st)

    _save_state(st)
    log.info(f"[FOLLOW-ENGAGERS] Cycle done: {followed} engagers followed "
             f"({st['count_today']}/{per_day} today).")


def safe_run_follow_engagers_cycle():
    from . import health
    try:
        run_follow_engagers_cycle()
        health.record_success("follow_engagers")
    except Exception:
        log.info("[FOLLOW-ENGAGERS] Error during cycle:")
        traceback.print_exc()
        health.record_failure("follow_engagers")
