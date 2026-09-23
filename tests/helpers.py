"""Helpers shared by test files of several packages."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.editorial import editorial_bot as editorial
from src.guards import action_guard as ag, active_hours as hours
from src.x import x_urls


TORONTO = ZoneInfo("America/Toronto")


def clock(monkeypatch, value):
    monkeypatch.setattr(hours, "now_local", lambda: value)
    monkeypatch.setattr(ag, "now_local", lambda: value)
    monkeypatch.setattr(editorial, "now_local", lambda: value)


def _stop_requested(monkeypatch):
    import threading
    from src.guards import active_hours

    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(active_hours, "_STOP", stop)


def url(author, n=2063500000000000200):
    return f"https://x.com/{author}/status/{n}"


def _url(n, author="someone"):
    return f"https://x.com/{author}/status/20635000000000{n:05d}"


def fresh(handle, minutes=5, n=0):
    """A status URL posted `minutes` ago; `n` keeps URLs distinct."""
    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - minutes * 60_000
    return f"https://x.com/{handle}/status/{((ms - x_urls._TWITTER_EPOCH_MS) << 22) + n}"
