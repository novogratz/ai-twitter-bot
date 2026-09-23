"""One Toronto clock for scheduling, day budgets, and browser activity."""
from datetime import datetime, time, timedelta
from functools import wraps
import threading
from zoneinfo import ZoneInfo

from ..core import config
from ..core.logger import log


_STOP = threading.Event()


def request_stop():
    _STOP.set()


class OutsideActiveHours(RuntimeError):
    """A running cycle reached bedtime; it must stop doing external work."""


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.BOT_TIMEZONE))


def is_active(now: datetime | None = None) -> bool:
    local = (now or now_local()).astimezone(ZoneInfo(config.BOT_TIMEZONE))
    return time(4, 30) <= local.time().replace(tzinfo=None) < time(22, 0)


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
    wake = local.replace(hour=4, minute=30, second=0, microsecond=0)
    return wake if local < wake else wake + timedelta(days=1)


def require_active() -> None:
    if not may_act():
        raise OutsideActiveHours("Bot asleep: active 04:30–22:00 America/Toronto")


def awake_job(fn):
    """Also gate queued jobs and work that crossed the 22:00 boundary."""
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


def seconds_until_bedtime() -> float:
    now = now_local()
    return max(0.0, (now.replace(hour=22, minute=0, second=0, microsecond=0) - now).total_seconds())
