"""Bounded process-local pipeline measurements; never admission or posting state."""
from contextlib import contextmanager
from collections import defaultdict
import threading
import time


class Tracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = None
        self.buckets = {}

    def record(self, stage, outcome, seconds=0, items=0, *, now=None):
        now = time.time() if now is None else now
        minute = int(now // 60)
        with self.lock:
            if self.started is None:
                self.started = now
            self.buckets = {m: values for m, values in self.buckets.items() if minute - 59 <= m <= minute}
            values = self.buckets.setdefault(minute, {})
            row = values.setdefault((stage, outcome), dict(count=0, seconds=0.0, maximum_seconds=0.0, items=0))
            row["count"] += 1
            row["seconds"] += max(0, seconds)
            row["maximum_seconds"] = max(row["maximum_seconds"], seconds)
            row["items"] += max(0, items)

    def snapshot(self, *, now=None):
        now = time.time() if now is None else now
        minute = int(now // 60)
        with self.lock:
            stages = defaultdict(dict)
            for m, values in self.buckets.items():
                if not minute - 59 <= m <= minute:
                    continue
                for (stage, outcome), row in values.items():
                    total = stages[stage].setdefault(outcome, dict(count=0, seconds=0.0, maximum_seconds=0.0, items=0))
                    for key in ("count", "seconds", "items"):
                        total[key] += row[key]
                    total["maximum_seconds"] = max(total["maximum_seconds"], row["maximum_seconds"])
            for outcomes in stages.values():
                for row in outcomes.values():
                    row["mean_seconds"] = round(row["seconds"] / row["count"], 2)
                    row["seconds"] = round(row["seconds"], 2)
                    row["maximum_seconds"] = round(row["maximum_seconds"], 2)
            start = max(self.started or now, (minute - 59) * 60)
            elapsed = max(0, now - start)
            confirmed = stages.get("send", {}).get("shipped", {}).get("count", 0)
            return dict(started_at=self.started, window_start=start, window_end=now,
                        observed_seconds=round(elapsed, 1), stages=dict(stages),
                        confirmed_per_hour=round(confirmed * 3600 / elapsed, 1) if elapsed >= 60 else None,
                        scope="Current process; last 60 minute buckets. Resets on restart. Empty reads may mean no results or unavailable pages. Worker times overlap and are not total elapsed time.")


TRACKER = Tracker()


def record(stage, outcome, seconds=0, items=0):
    try:
        TRACKER.record(stage, outcome, seconds, items)
    except Exception:
        pass  # Losing optional telemetry must never hide a confirmed write.


def snapshot():
    try:
        return TRACKER.snapshot()
    except Exception:
        return {"unavailable": True}


@contextmanager
def measure(stage):
    start, outcome = time.monotonic(), "completed"
    try:
        yield
    except BaseException:
        outcome = "interrupted"
        raise
    finally:
        record(stage, outcome, time.monotonic() - start)
