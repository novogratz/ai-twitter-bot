"""Transaction ordering, reentrancy and cancellation under contention."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from src.core import work_priority as priority


def queued(lock, count):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with lock._condition:
            if len(lock._waiters) == count:
                return
        time.sleep(.001)
    pytest.fail("worker did not queue")


def test_priority_then_fifo_without_interrupting_the_owner():
    lock, order = priority.PriorityLock(), []
    def run(label, rank):
        with priority.scope(rank), lock:
            order.append(label)
    with ThreadPoolExecutor(4) as pool:
        with lock:
            a = pool.submit(run, "scan", priority.BACKGROUND)
            queued(lock, 1)
            b = pool.submit(run, "reply", priority.REPLY)
            queued(lock, 2)
            c = pool.submit(run, "watch1", priority.WATCH)
            queued(lock, 3)
            d = pool.submit(run, "watch2", priority.WATCH)
            queued(lock, 4)
            with lock:  # recovery and parent likes nest under a browser owner
                assert order == []
        for task in (a, b, c, d):
            task.result(2)
    assert order == ["watch1", "watch2", "reply", "scan"]


def test_idle_spacing_owner_can_yield_to_urgent_work():
    lock, order = priority.PriorityLock(), []
    def urgent():
        with priority.scope(priority.WATCH), lock:
            order.append("urgent")
    with ThreadPoolExecutor(1) as pool:
        with priority.scope(priority.REPLY), lock:
            task = pool.submit(urgent)
            queued(lock, 1)
            assert lock.yield_to_urgent()
            order.append("resumed")
        task.result(2)
    assert order == ["urgent", "resumed"]


def test_cancelled_and_timed_out_waiters_leave_no_phantom_priority():
    stop = threading.Event()
    def check():
        if stop.is_set():
            raise RuntimeError("stopped")
    lock = priority.PriorityLock(check)
    with ThreadPoolExecutor(1) as pool:
        with lock:
            timed = pool.submit(lock.acquire, .01)
            assert timed.result(2) is False
            task = pool.submit(lock.acquire)
            queued(lock, 1)
            stop.set()
            with lock._condition:
                lock._condition.notify_all()
            with pytest.raises(RuntimeError, match="stopped"):
                task.result(2)
            assert lock._waiters == []
    stop.clear()
    with lock:
        assert lock.owned()


def test_priority_context_restores_after_failure():
    with pytest.raises(ValueError):
        with priority.scope(priority.WATCH):
            assert priority._priority.get() == priority.WATCH
            raise ValueError()
    assert priority._priority.get() == priority.BACKGROUND
