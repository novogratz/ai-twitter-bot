"""One Toronto clock for scheduling, day budgets, and browser activity."""
from datetime import date, datetime, time, timedelta
from functools import wraps
import threading
from zoneinfo import ZoneInfo

from ..core import config
from ..core.logger import log


WAKE = time(5)
BEDTIME = time(0)
ACTIVE_WINDOWS = ((time(5), time(10)), (time(14), time(15)),
                  (time(17), time(19)), (time(22), time(0)))

_STOP = threading.Event()


def request_stop():
    _STOP.set()


class OutsideActiveHours(RuntimeError):
    """A running cycle reached bedtime; it must stop doing external work."""


def window_label() -> str:
    windows = ", ".join(f"{start:%H:%M}–{end:%H:%M}" if end != time(0)
                        else f"{start:%H:%M}–24:00" for start, end in ACTIVE_WINDOWS)
    return windows + " " + config.BOT_TIMEZONE


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
    return any(start <= clock and (end == time(0) or clock < end)
               for start, end in ACTIVE_WINDOWS)


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
    for start, _ in ACTIVE_WINDOWS:
        wake = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        if local < wake:
            return wake
    return (local + timedelta(days=1)).replace(hour=WAKE.hour, minute=WAKE.minute, second=0, microsecond=0)


def require_active() -> None:
    if not may_act():
        raise OutsideActiveHours(f"Bot asleep: active {window_label()}")


def awake_job(fn):
    """Also gate queued jobs and work that crossed the BEDTIME boundary."""
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


def bedtime(now: datetime) -> datetime:
    """End of the current Toronto active window; now itself while asleep."""
    for start, end in ACTIVE_WINDOWS:
        if start <= now.time().replace(tzinfo=None) and (end == time(0) or now.time().replace(tzinfo=None) < end):
            day = now + timedelta(days=1) if end == time(0) else now
            return day.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    return now


def seconds_until_bedtime() -> float:
    now = now_local()
    return max(0.0, (bedtime(now) - now).total_seconds())
