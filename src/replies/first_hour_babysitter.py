"""First-hour babysitter — reply velocity on our freshest post.

X's algorithm weights replies in a post's first ~60 minutes ~15x vs likes.
The replyback cycle already converses with
engagers, but on its normal cadence a hot first hour can slip by.

This bot runs every BABYSIT_CHECK_MINUTES: if our latest original post is
younger than BABYSIT_WINDOW_MINUTES, it triggers an extra replyback sweep so
every early commenter gets a fast, warm response while the algo is watching.
Outside the window it does nothing (near-zero Safari cost). All actual writes
still flow through the reply chokepoint (caps, spacing, one-reply-per-tweet,
truncation gate, @Graphseo typo).
"""
import traceback
from datetime import datetime

from ..core import settings
from ..core.history import load_history
from ..core.logger import log


def _latest_post_age_minutes() -> float:
    hist = load_history()
    try:
        ts = hist[-1].get("timestamp", "") if hist else ""
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60.0
    except (ValueError, IndexError, AttributeError):
        return 999_999.0


def run_babysit_cycle():
    age = _latest_post_age_minutes()
    if age > settings.get("BABYSIT_WINDOW_MINUTES"):
        log.debug(f"[BABYSIT] Latest post is {age:.0f} min old — outside the hot window, nothing to do.")
        return
    log.info(f"[BABYSIT] Latest post is {age:.0f} min old — extra replyback sweep (first-hour algo window).")
    from .notify_bot import run_replyback_cycle
    run_replyback_cycle()


def safe_run_babysit_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_babysit_cycle()
        health.record_success("babysitter")
    except Exception:
        log.info("[BABYSIT] Error during babysit cycle:")
        traceback.print_exc()
        health.record_failure("babysitter")
