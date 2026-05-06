"""Auto-tune bot — real-time strategy self-correction.

Why: strategy_agent + evolution_agent run every few hours. That's too slow
for the "10k followers next week" mission. We need second-by-second
self-correction signals. This bot reads engagement_log every 30 min,
computes per-source ROI on the most recent window, and writes a state
file (`auto_tune_state.json`) that other bots can READ to:
  - skip dead source paths
  - accelerate winning surfaces
  - throttle when we're near rate limits

What it tunes (write-side):
  - `auto_tune_state.json` keys:
      "winners": {source: avg_likes_30min}
      "losers":  {source: avg_likes_30min}    (sources to deprioritize)
      "boost_cadence_factor": float in [0.5..2.0]
      "post_cadence_factor": float in [0.5..2.0]
      "ts": ISO timestamp

Other bots can OPT-IN to read this file (we don't hard-couple — the
file is advisory). The strategy agent already runs the slower 12h cycle;
this is the fast-feedback complement.
"""
import csv
import json
import os
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE
from .logger import log

AUTO_TUNE_FILE = os.path.join(_PROJECT_ROOT, "auto_tune_state.json")

# Window we consider "recent" for the fast loop. Most replies/posts get
# their first 80% of likes within 1-2h, so 90 min is a fair signal.
LOOKBACK_MINUTES = int(os.environ.get("AUTO_TUNE_LOOKBACK_MIN", "90"))


def _read_recent_actions(window_min: int):
    """Yield (ts, type, text, target_url, source, pattern) tuples from the log
    within the last `window_min` minutes."""
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return []
    cutoff = datetime.now() - timedelta(minutes=window_min)
    rows = []
    try:
        with open(ENGAGEMENT_LOG_FILE, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 4:
                    continue
                ts_raw = row[0]
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                rows.append({
                    "ts": ts,
                    "type": row[1] if len(row) > 1 else "",
                    "text": row[2] if len(row) > 2 else "",
                    "target_url": row[3] if len(row) > 3 else "",
                    "source": row[4] if len(row) > 4 else "",
                    "pattern": row[5] if len(row) > 5 else "",
                })
    except Exception:
        log.info("[AUTO_TUNE] Failed to read engagement_log:")
        traceback.print_exc()
    return rows


def _compute_tuning(rows: list) -> dict:
    """Group recent activity by source and emit a tuning dict.

    Heuristic without scraping: we use ACTION COUNT per source as a proxy
    for productivity. A source path that produced 0 actions in 90min is
    broken (probably the scraper failing) — flag it. A source path with
    high count is healthy — boost cadence factor.

    For per-source TRUE ROI (likes earned), the slower strategy_agent
    handles it via the perf_log scrape. This bot is a velocity gauge,
    not a quality gauge.
    """
    by_source = defaultdict(int)
    by_type = defaultdict(int)
    for r in rows:
        if r["source"]:
            by_source[r["source"]] += 1
        by_type[r["type"]] += 1

    # Actions seen in the window. For our scale, healthy = 30-100/30min.
    total = sum(by_source.values())
    # When activity is high, push cadences slightly faster; when low,
    # slow them so we don't spam-fail. Capped to [0.6 .. 1.6].
    if total >= 60:
        post_factor = 0.7  # speed up
    elif total >= 30:
        post_factor = 0.85
    elif total >= 10:
        post_factor = 1.0
    else:
        post_factor = 1.5  # something is broken upstream — slow down

    # Top 5 sources by count are "winners". Bottom-half (count == 0 or 1
    # over the window) are "losers". The strategy agent does the harder
    # ROI math; we just expose the velocity snapshot.
    sorted_src = sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)
    winners = dict(sorted_src[:5])
    losers = {k: v for k, v in sorted_src if v <= 1}

    return {
        "ts": datetime.now().isoformat(),
        "window_min": LOOKBACK_MINUTES,
        "total_actions": total,
        "by_type": dict(by_type),
        "winners": winners,
        "losers": losers,
        "post_cadence_factor": post_factor,
        "boost_cadence_factor": 1.0,
    }


def run_auto_tune_cycle():
    """Compute per-source velocity over the recent window, write state file."""
    rows = _read_recent_actions(LOOKBACK_MINUTES)
    log.info(f"[AUTO_TUNE] Read {len(rows)} actions in last {LOOKBACK_MINUTES}min.")

    tuning = _compute_tuning(rows)
    try:
        with open(AUTO_TUNE_FILE, "w") as f:
            json.dump(tuning, f, indent=2)
        log.info(
            f"[AUTO_TUNE] Wrote state — total={tuning['total_actions']}, "
            f"factor={tuning['post_cadence_factor']}, "
            f"winners={list(tuning['winners'].keys())[:3]}"
        )
    except Exception:
        log.info("[AUTO_TUNE] Failed to write auto_tune_state.json:")
        traceback.print_exc()


def safe_run_auto_tune_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_auto_tune_cycle()
        health.record_success("auto_tune")
    except Exception:
        log.info("[AUTO_TUNE] Error during auto-tune cycle:")
        traceback.print_exc()
        health.record_failure("auto_tune")


def get_post_cadence_factor() -> float:
    """Read the current post cadence factor (1.0 = neutral)."""
    if not os.path.exists(AUTO_TUNE_FILE):
        return 1.0
    try:
        with open(AUTO_TUNE_FILE, "r") as f:
            d = json.load(f)
        f = float(d.get("post_cadence_factor", 1.0))
        return max(0.5, min(2.0, f))
    except Exception:
        return 1.0
