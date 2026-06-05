"""Engine-health watchdog — catch a collapsed surface in hours, not days.

Post-mortem 2026-06-05: retweets ran 140/day → 0 for TWO DAYS (dropped scrape
timestamps) and replies 397 → 42 (eaten JSON) before anyone noticed — the
collapse was invisible in bot.log noise and only obvious in engagement_log.csv
daily counts.

This bot runs hourly: for each action type it compares today's count SO FAR
against the average count at the same hour-of-day over the previous 7 days.
If today's pace is below ALERT_RATIO (40%) of the baseline (and the baseline
is meaningful), it logs a loud alert and records it in
engine_health_alerts.json (picked up by the daily digest / operator).
"""
import csv
import json
import os
import traceback
from collections import defaultdict
from datetime import date, datetime, timedelta

from .config import _PROJECT_ROOT
from .logger import log

ENGAGEMENT_LOG = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
ALERTS_FILE = os.path.join(_PROJECT_ROOT, "engine_health_alerts.json")

ALERT_RATIO = float(os.environ.get("ENGINE_HEALTH_ALERT_RATIO", "0.4"))
MIN_BASELINE = float(os.environ.get("ENGINE_HEALTH_MIN_BASELINE", "5"))
WATCHED_TYPES = ("reply", "retweet", "quote", "post", "hotake")


def _counts_by_day_hour() -> dict:
    """{(date_str, type): count_up_to_current_hour} for the last 8 days."""
    cutoff = (date.today() - timedelta(days=8)).isoformat()
    hour_now = datetime.now().hour
    counts: dict = defaultdict(int)
    try:
        with open(ENGAGEMENT_LOG) as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if len(row) < 2:
                    continue
                ts, kind = row[0], row[1]
                if len(ts) < 13 or ts[:10] < cutoff:
                    continue
                try:
                    row_hour = int(ts[11:13])
                except ValueError:
                    continue
                # Same-hour-of-day comparison: only count actions up to the
                # current hour so today's partial day compares fairly.
                if row_hour <= hour_now:
                    counts[(ts[:10], kind)] += 1
    except OSError:
        pass
    return counts


def run_engine_health_cycle():
    today = date.today().isoformat()
    counts = _counts_by_day_hour()
    prev_days = [(date.today() - timedelta(days=i)).isoformat() for i in range(1, 8)]

    alerts = []
    summary = []
    for kind in WATCHED_TYPES:
        baseline_vals = [counts.get((d, kind), 0) for d in prev_days]
        active_days = [v for v in baseline_vals if v > 0]
        if not active_days:
            continue  # surface was never active this week — nothing to compare
        baseline = sum(active_days) / len(active_days)
        today_count = counts.get((today, kind), 0)
        summary.append(f"{kind}: {today_count} vs {baseline:.0f} avg")
        if baseline >= MIN_BASELINE and today_count < ALERT_RATIO * baseline:
            alerts.append(
                f"{kind} collapsed: {today_count} today vs ~{baseline:.0f} "
                f"by this hour over the last 7 days ({today_count / baseline:.0%})"
            )

    log.info(f"[ENGINE_HEALTH] {'; '.join(summary) if summary else 'no baseline yet'}")
    if not alerts:
        return

    for a in alerts:
        log.error(f"[ENGINE_HEALTH] ⚠️ ALERT: {a}")
    payload = {"ts": datetime.now().isoformat(), "alerts": alerts}
    try:
        existing = []
        if os.path.exists(ALERTS_FILE):
            with open(ALERTS_FILE) as f:
                existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
        existing.append(payload)
        with open(ALERTS_FILE, "w") as f:
            json.dump(existing[-50:], f, indent=2)
    except (OSError, json.JSONDecodeError):
        pass


def safe_run_engine_health_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_engine_health_cycle()
        health.record_success("engine_health")
    except Exception:
        log.info("[ENGINE_HEALTH] Error during health cycle:")
        traceback.print_exc()
        health.record_failure("engine_health")
