"""One Toronto clock for scheduling, day budgets, and browser activity."""
from datetime import date, datetime, time, timedelta
from functools import wraps
import threading
from zoneinfo import ZoneInfo

from ..core import config
from ..core.logger import log


# Midnight to midnight means continuous activity, without a daily closing instant.
WINDOWS = ((time.min, time.min),)

_STOP = threading.Event()


def request_stop():
    _STOP.set()


class OutsideActiveHours(RuntimeError):
    """A running cycle reached bedtime; it must stop doing external work."""


def window_label() -> str:
    if _all_day():
        return f"24/7 {config.BOT_TIMEZONE}"
    windows = ", ".join(
        f"{start:%H:%M}–{'24:00' if end == time.min else end.strftime('%H:%M')}"
        for start, end in WINDOWS)
    return f"{windows} {config.BOT_TIMEZONE}"


def _all_day() -> bool:
    return WINDOWS == ((time.min, time.min),)


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.BOT_TIMEZONE))


def today_iso() -> str:
    """Today's Toronto day, as YYYY-MM-DD."""
    return now_local().date().isoformat()


def is_past_day(stamped) -> bool:
    """A stored day is over: before today in Toronto, or unreadable.

    A later day was stamped by the Mac's clock ahead of Toronto's, before
    issue #191: it counts as today, so a quota already spent stays spent.
    """
    try:
        return date.fromisoformat(stamped) < now_local().date()
    except (TypeError, ValueError):
        return True


def is_active(now: datetime | None = None) -> bool:
    local = (now or now_local()).astimezone(ZoneInfo(config.BOT_TIMEZONE))
    clock = local.time().replace(tzinfo=None)
    return any(start <= clock and (end == time.min or clock < end)
               for start, end in WINDOWS)


def stop_requested() -> bool:
    return _STOP.is_set()


def may_act(now: datetime | None = None) -> bool:
    """Waking hours and no stop requested: external work may start.

    The scheduler's pause/resume loop keeps using is_active(), which ignores
    the stop so shutdown never flips the scheduler back on.
    """
    return not stop_requested() and is_active(now)


def next_wake(now: datetime | None = None) -> datetime:
    local = (now or now_local()).astimezone(ZoneInfo(config.BOT_TIMEZONE))
    if _all_day():
        return local
    for start, _ in WINDOWS:
        wake = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        if local < wake:
            return wake
    wake = WINDOWS[0][0]
    return (local + timedelta(days=1)).replace(
        hour=wake.hour, minute=wake.minute, second=0, microsecond=0)


def require_active() -> None:
    if not may_act():
        raise OutsideActiveHours(f"Bot asleep: active {window_label()}")


def awake_job(fn):
    """Also gate queued jobs and work that crossed an activity boundary."""
    @wraps(fn)
    def run(*args, **kwargs):
        if not may_act():
            return None
        try:
            return fn(*args, **kwargs)
        except OutsideActiveHours:
            log.info("[%s] Stopped for bedtime.", fn.__name__)
            return None
    return run


def bedtime(now: datetime) -> datetime | None:
    """Close of the current or next window; None for continuous activity.

    An editorial slot opened during a break may still overlap the next
    window; the activity guard separately refuses all work during the break.
    """
    if _all_day():
        return None
    local = now.astimezone(ZoneInfo(config.BOT_TIMEZONE))
    clock = local.time().replace(tzinfo=None)
    end = next((end for _, end in WINDOWS if end == time.min or clock < end), WINDOWS[-1][1])
    close = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if end == time.min:
        close += timedelta(days=1)
    return close.astimezone(now.tzinfo)


def seconds_until_bedtime() -> float:
    now = now_local()
    if not may_act(now):
        return 0.0
    close = bedtime(now)
    return float("inf") if close is None else max(0.0, (close - now).total_seconds())
