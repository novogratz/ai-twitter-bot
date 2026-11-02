"""Toronto wall-clock slots and elapsed eligible time, including DST folds."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..guards import active_hours

ZONE = ZoneInfo("America/Toronto")  # Montreal uses the same calendar/offset rules.


def utc_now():
    return datetime.now(timezone.utc)


def local(now):
    if now.tzinfo is None:
        raise ValueError("video timestamps must include a timezone")
    return now.astimezone(ZONE)


def eligible(now):
    return active_hours.is_active(local(now))


def clocks(cfg):
    minutes = []
    if not 5 <= len(cfg.windows) <= 8 or len(set(cfg.windows)) != len(cfg.windows) or not set(cfg.paired_windows) <= set(cfg.windows):
        raise ValueError("five to eight unique video windows with paired windows drawn from them are required")
    for value in cfg.windows:
        parsed = time.fromisoformat(value)
        if parsed.second or parsed.microsecond or parsed.tzinfo or parsed < active_hours.WAKE:
            raise ValueError("video slots must be minute precision during " + active_hours.window_label())
        minute = parsed.hour * 60 + parsed.minute
        minutes.append(minute)
        if value in cfg.paired_windows:
            minutes.append(minute + cfg.pair_minutes)
    minutes.sort()
    if not 5 <= len(minutes) <= 8 or len(set(minutes)) != len(minutes) or minutes[-1] >= 1440:
        raise ValueError("five to eight distinct video slots are required")
    if any(b - a < 15 for a, b in zip(minutes, minutes[1:])):
        raise ValueError("video slot clocks must be at least 15 minutes apart")
    return tuple(f"{n // 60:02}:{n % 60:02}" for n in minutes)


def slots(day, cfg):
    return [(f"{day}/{clock}", datetime.combine(day, time.fromisoformat(clock), ZONE))
            for clock in clocks(cfg)]


def primary_slot(slot_id, cfg):
    """Map a paired slot to its window's first slot; independent of list order."""
    day, clock = slot_id.split("/", 1)
    for window in cfg.windows:
        parsed = time.fromisoformat(window)
        minute = parsed.hour * 60 + parsed.minute
        base = f"{minute // 60:02}:{minute % 60:02}"
        second = minute + cfg.pair_minutes
        if clock == base or (window in cfg.paired_windows and clock == f"{second // 60:02}:{second % 60:02}"):
            return f"{day}/{base}"
    raise ValueError("slot is outside the configured video windows")


def upcoming_primary(now, cfg):
    """Protect one rolling day of main windows, including the next morning."""
    result = []
    for offset in (0, 1):
        for key, at in slots(local(now).date() + timedelta(days=offset), cfg):
            if primary_slot(key, cfg) == key and at.timestamp() >= now.timestamp():
                result.append((key, at))
    return result[:len(cfg.windows)]


def eligible_seconds(start, end):
    """Elapsed posting-eligible seconds; DST nights and interaction breaks do not count."""
    if end.timestamp() <= start.timestamp():
        return 0.0
    day, last = local(start).date(), local(end).date()
    total = 0.0
    while day <= last:
        wake = datetime.combine(day, active_hours.WAKE, ZONE)
        left = wake.timestamp()
        right = active_hours.bedtime(wake).timestamp()
        begin, finish = max(start.timestamp(), left), min(end.timestamp(), right)
        total += max(0, finish - begin)
        for hour in range(24):
            window = active_hours.break_window(datetime.combine(day, time(hour), ZONE))
            if window:
                total -= max(0, min(finish, window[1].timestamp()) - max(begin, window[0].timestamp()))
        day += timedelta(days=1)
    return total


def next_slot(now, cfg):
    for offset in (0, 1):
        for key, at in slots(local(now).date() + timedelta(days=offset), cfg):
            if at.timestamp() >= now.timestamp():
                return key, at
