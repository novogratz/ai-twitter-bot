"""One Toronto clock for scheduling, day budgets, and browser activity."""
from datetime import date, datetime, time, timedelta
from functools import wraps
import threading
from zoneinfo import ZoneInfo

from ..core import config
from ..core.logger import log


WAKE = time(4, 30)
BEDTIME = time(23, 30)

_STOP = threading.Event()


def request_stop():
    _STOP.set()


class OutsideActiveHours(RuntimeError):
    """A running cycle reached bedtime; it must stop doing external work."""


def window_label() -> str:
    return f"{WAKE:%H:%M}–{BEDTIME:%H:%M} {config.BOT_TIMEZONE}"


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
    return WAKE <= local.time().replace(tzinfo=None) < BEDTIME


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
    wake = local.replace(hour=WAKE.hour, minute=WAKE.minute, second=0, microsecond=0)
    return wake if local < wake else wake + timedelta(days=1)


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
    """The BEDTIME that ends `now`'s day, in `now`'s timezone."""
    return now.replace(hour=BEDTIME.hour, minute=BEDTIME.minute, second=0, microsecond=0)


def seconds_until_bedtime() -> float:
    now = now_local()
    return max(0.0, (bedtime(now) - now).total_seconds())
