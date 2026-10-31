"""Cooperative priority at transaction boundaries; never interrupt a browser write."""
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import count
import threading
import time

WATCH = 0
REPLY = 1
BACKGROUND = 2
_priority = ContextVar("work_priority", default=BACKGROUND)


@contextmanager
def scope(priority):
    token = _priority.set(min(priority, _priority.get()))
    try:
        yield
    finally:
        _priority.reset(token)


class PriorityLock:
    """Reentrant lock, ordered by priority then arrival, with cancellable waits.

    The owner finishes its transaction. Newly queued urgent work goes before
    routine waiters, without stealing the current page or exposing a composer.
    """
    def __init__(self, check=lambda: None):
        self._condition = threading.Condition()
        self._owner = None
        self._depth = 0
        self._waiters = []
        self._sequence = count()
        self._check = check

    def acquire(self, timeout=-1):
        ident = threading.get_ident()
        deadline = time.monotonic() + timeout if timeout >= 0 else None
        with self._condition:
            self._check()
            if self._owner == ident:
                self._depth += 1
                return True
            ticket = (_priority.get(), next(self._sequence))
            self._waiters.append(ticket)
            try:
                while self._owner is not None or ticket != min(self._waiters):
                    self._check()
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self._condition.wait(min(1.0, remaining) if remaining is not None else 1.0)
                self._check()
                self._owner, self._depth = ident, 1
                return True
            finally:
                self._waiters.remove(ticket)
                self._condition.notify_all()

    def release(self):
        with self._condition:
            if self._owner != threading.get_ident():
                raise RuntimeError("cannot release another worker's transaction")
            self._depth -= 1
            if not self._depth:
                self._owner = None
                self._condition.notify_all()

    def yield_to_urgent(self):
        """Only for an idle spacing wait, never for a browser transaction."""
        with self._condition:
            if (self._owner != threading.get_ident() or self._depth != 1
                    or not any(priority < _priority.get() for priority, _ in self._waiters)):
                return False
            self.release()
        self.acquire()
        return True

    def owned(self):
        with self._condition:
            return self._owner == threading.get_ident()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
