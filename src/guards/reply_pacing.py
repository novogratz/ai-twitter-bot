"""Persist the cooldown before a Reply submit, even when its result is uncertain."""
from datetime import datetime, timedelta

from ..core import config
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile, StatePath, process_lock
from . import active_hours

PACE = StateFile("reply_pacing.json", {}, GUARDED)
LOCK = StatePath("reply_pacing.lock")


def remaining() -> float:
    value = PACE.read()
    if not value:
        return 0.0
    try:
        if set(value) != {"submitted_at", "next_at", "target"} or not isinstance(value["target"], str):
            raise ValueError("bad pacing record")
        submitted, due = (datetime.fromisoformat(value[key]) for key in ("submitted_at", "next_at"))
        if submitted.tzinfo is None or due.tzinfo is None or (due - submitted).total_seconds() < 300:
            raise ValueError("bad pacing timestamps")
    except (ValueError, TypeError, KeyError) as exc:
        raise StateUnreadable("Reply pacing unreadable; refusing a possible burst") from exc
    # Tightening the configured minimum also applies to a saved deadline.
    due = max(due, submitted + timedelta(seconds=config.MIN_SECONDS_BETWEEN_REPLIES))
    return max(0.0, (due - active_hours.now_local()).total_seconds())


def reserve(url: str) -> bool:
    """Last atomic check, immediately before submit. Never release uncertain work."""
    from . import action_guard
    if config.dry_run():
        return False
    with process_lock(LOCK):
        active_hours.require_active()
        if action_guard.too_soon(action_guard.REPLY):
            return False
        now = active_hours.now_local()
        gap = action_guard.spacing_gap_after(action_guard.REPLY, now)
        PACE.write({"submitted_at": now.isoformat(),
                    "next_at": (now + timedelta(seconds=gap)).isoformat(), "target": url})
    return True
