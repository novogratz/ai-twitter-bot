"""One Toronto clock for scheduling, day budgets, and browser activity."""
from datetime import date, datetime, time, timedelta
from functools import wraps
import hashlib
import threading
from zoneinfo import ZoneInfo

from ..core import config, settings
from ..core.logger import log


WAKE = time(4, 30)
BEDTIME = time(0, 0)

_STOP = threading.Event()


def request_stop():
    _STOP.set()


class OutsideActiveHours(RuntimeError):
    """A running cycle reached bedtime; it must stop doing external work."""


class ScheduledBreak(OutsideActiveHours):
    """The Account is taking its scheduled pause, not experiencing a failure."""


def break_window(now: datetime | None = None) -> tuple[datetime, datetime] | None:
    """A stable per-hour plan shared by workers and preserved across restarts."""
    minutes = settings.get("HOURLY_BREAK_MINUTES")
    if not minutes:
        return None
    local = (now or now_local()).astimezone(ZoneInfo(config.BOT_TIMEZONE))
    key = f"{settings.get('BOT_ACCOUNT')}:{local:%Y-%m-%d-%H}"
    seed = hashlib.sha256(key.encode()).digest()
    if seed[0] % 4 == 0:
        return None
    start = local.replace(minute=35 + seed[1] % 16, second=0, microsecond=0)
    wake = local.replace(hour=WAKE.hour, minute=WAKE.minute, second=0, microsecond=0)
    if not is_active(start) or start < wake + timedelta(hours=1):
        return None
    return start, min(start + timedelta(minutes=minutes), bedtime(start))


def break_until(now: datetime | None = None) -> datetime | None:
    local = (now or now_local()).astimezone(ZoneInfo(config.BOT_TIMEZONE))
    window = break_window(local)
    return window[1] if window and window[0] <= local < window[1] else None


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
    clock = local.time().replace(tzinfo=None)
    if BEDTIME <= WAKE:
        return clock >= WAKE or clock < BEDTIME
    return WAKE <= clock < BEDTIME


def stop_requested() -> bool:
    return _STOP.is_set()


def may_act(now: datetime | None = None) -> bool:
    """External work may start in Waking hours, outside breaks and shutdown."""
    now = now or now_local()
    return not stop_requested() and is_active(now) and break_until(now) is None


def next_wake(now: datetime | None = None) -> datetime:
    local = (now or now_local()).astimezone(ZoneInfo(config.BOT_TIMEZONE))
    wake = local.replace(hour=WAKE.hour, minute=WAKE.minute, second=0, microsecond=0)
    return wake if local < wake else wake + timedelta(days=1)


def require_active() -> None:
    now = now_local()
    if stop_requested() or not is_active(now):
        raise OutsideActiveHours(f"Bot asleep: active {window_label()}")
    end = break_until(now)
    if end is not None:
        raise ScheduledBreak(f"Scheduled break until {end.isoformat(timespec='minutes')}")


def awake_job(fn):
    """Also gate queued jobs and work that crossed the BEDTIME boundary."""
    @wraps(fn)
    def run(*args, **kwargs):
        if not may_act():
            return None
        try:
            return fn(*args, **kwargs)
        except ScheduledBreak:
            log.info("[%s] Stopped for a scheduled break.", fn.__name__)
            return None
        except OutsideActiveHours:
            log.info("[%s] Stopped for bedtime.", fn.__name__)
            return None
    return run


def bedtime(now: datetime) -> datetime:
    """The BEDTIME that ends `now`'s day, in `now`'s timezone."""
    end = now.replace(hour=BEDTIME.hour, minute=BEDTIME.minute, second=0, microsecond=0)
    if BEDTIME <= WAKE and now.time().replace(tzinfo=None) >= WAKE:
        end += timedelta(days=1)
    return end


def seconds_until_bedtime() -> float:
    now = now_local()
    return max(0.0, (bedtime(now) - now).total_seconds())


def seconds_until_pause() -> float:
    """Model requests stop at the next break or bedtime, whichever comes first."""
    now = now_local()
    if not is_active(now) or break_until(now) is not None:
        return 0.0
    end = bedtime(now)
    for hour in range(now.hour, 24):
        window = break_window(now.replace(hour=hour))
        if window and now < window[0] < end:
            end = window[0]
            break
    return max(0.0, (end - now).total_seconds())
