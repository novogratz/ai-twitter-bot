"""Daily state cleanup — keep the bot running smoothly when fully autonomous.

Long-running bots accumulate state: bot.log grows unbounded, replied_tweets
JSON crosses 50k entries, engagement_log.csv hits hundreds of MB. None of
this kills the bot, but startup gets slow and disk fills. This bot does
the housekeeping daily so the user never has to.

Strategy:
  - Once per day (idempotent via cleanup_state.json).
  - Rotate bot.log if > 100MB (keep last 30MB tail).
  - Trim engagement_log.csv to last 90 days.
  - Cap replied_tweets.json at 5000 entries.
  - Cap retweeted.json at 1000 entries.
  - Cap promoted_replies.json, breakout_history.json, spike_history.json
    at 500 each.
  - Cap pin_history.json at 30, viral_followed_up.json at 500.
"""
import csv
import json
import os
import shutil
import traceback
from datetime import date, datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE, REPLIED_FILE, HISTORY_FILE
from .logger import log

CLEANUP_STATE_FILE = os.path.join(_PROJECT_ROOT, "cleanup_state.json")
LOG_FILE = os.path.join(_PROJECT_ROOT, "bot.log")
ERR_FILE = os.path.join(_PROJECT_ROOT, "bot.err")

_MAX_LOG_BYTES = 100 * 1024 * 1024  # 100 MB
_TAIL_LOG_BYTES = 30 * 1024 * 1024  # keep last 30 MB after rotation
_ENGAGEMENT_LOG_KEEP_DAYS = 90

# Per-file caps for various JSON arrays.
# 2026-05-16: replied_tweets 5000 → 50000 (matches reply_bot._REPLIED_CAP).
# A profile re-shares old tweets often enough that 5000 wasn't enough memory
# to avoid duplicate replies a month apart.
_JSON_CAPS = {
    "replied_tweets.json": 50000,
    "replied_back.json": 10000,
    "retweeted.json": 5000,
    "quoted_tweets.json": 5000,
    "promoted_replies.json": 500,
    "breakout_history.json": 500,
    "spike_history.json": 200,
    "viral_followed_up.json": 500,
    "boost_history.json": 500,
}


def _already_ran_today() -> bool:
    if not os.path.exists(CLEANUP_STATE_FILE):
        return False
    try:
        with open(CLEANUP_STATE_FILE, "r") as f:
            return json.load(f).get("date") == date.today().isoformat()
    except Exception:
        return False


def _mark_ran_today():
    with open(CLEANUP_STATE_FILE, "w") as f:
        json.dump({"date": date.today().isoformat(), "ts": datetime.now().isoformat()}, f)


def _rotate_large_log(path: str, max_bytes: int, tail_bytes: int):
    """If path > max_bytes, archive a copy then truncate to last tail_bytes."""
    if not os.path.exists(path):
        return
    size = os.path.getsize(path)
    if size <= max_bytes:
        return
    log.info(f"[CLEANUP] Rotating {os.path.basename(path)} ({size} bytes)")
    archive = f"{path}.{date.today().isoformat()}.archive"
    try:
        # Save the head as an archive once per day.
        if not os.path.exists(archive):
            shutil.copy(path, archive)
        # Keep the tail in-place so launchd's stdout pipe stays valid.
        with open(path, "rb") as f:
            f.seek(-tail_bytes, os.SEEK_END)
            tail = f.read()
        with open(path, "wb") as f:
            f.write(b"# rotated " + datetime.now().isoformat().encode() + b"\n")
            f.write(tail)
        log.info(f"[CLEANUP] Truncated {os.path.basename(path)} to last {len(tail)} bytes.")
    except Exception:
        log.info(f"[CLEANUP] Rotation failed for {path}:")
        traceback.print_exc()


def _trim_engagement_log(path: str, keep_days: int):
    """Drop rows older than `keep_days` from the CSV."""
    if not os.path.exists(path):
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    try:
        kept = []
        dropped = 0
        with open(path, "r", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 1:
                    kept.append(row)
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                except (ValueError, IndexError):
                    kept.append(row)
                    continue
                if ts < cutoff:
                    dropped += 1
                    continue
                kept.append(row)
        if dropped == 0:
            return
        tmp = path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerows(kept)
        os.replace(tmp, path)
        log.info(f"[CLEANUP] Trimmed {dropped} rows from engagement_log (>{keep_days}d old).")
    except Exception:
        log.info("[CLEANUP] Engagement log trim failed:")
        traceback.print_exc()


def _cap_json_array(path: str, cap: int):
    """If path is a JSON list/dict-of-lists with > cap entries, slice to last N."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return  # leave untouched if not parseable

    changed = False
    if isinstance(data, list):
        if len(data) > cap:
            data = data[-cap:]
            changed = True
    elif isinstance(data, dict):
        # Heuristic: if the dict has a "history" / "items" / "pinned" / "handles"
        # array-like key, cap that.
        for k in ("history", "items", "pinned", "handles", "entries"):
            if isinstance(data.get(k), list) and len(data[k]) > cap:
                data[k] = data[k][-cap:]
                changed = True

    if changed:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log.info(f"[CLEANUP] Capped {os.path.basename(path)} to {cap} entries.")
        except Exception:
            log.info(f"[CLEANUP] Cap-write failed for {path}:")
            traceback.print_exc()


def run_cleanup_cycle():
    if _already_ran_today():
        return

    log.info("[CLEANUP] Running daily housekeeping...")

    # 1. Rotate logs if oversized.
    _rotate_large_log(LOG_FILE, _MAX_LOG_BYTES, _TAIL_LOG_BYTES)
    _rotate_large_log(ERR_FILE, _MAX_LOG_BYTES, _TAIL_LOG_BYTES)

    # 2. Trim engagement log.
    _trim_engagement_log(ENGAGEMENT_LOG_FILE, _ENGAGEMENT_LOG_KEEP_DAYS)

    # 3. Cap JSON arrays.
    for fname, cap in _JSON_CAPS.items():
        _cap_json_array(os.path.join(_PROJECT_ROOT, fname), cap)

    _mark_ran_today()
    log.info("[CLEANUP] Done.")


def safe_run_cleanup_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_cleanup_cycle()
        health.record_success("cleanup")
    except Exception:
        log.info("[CLEANUP] Error during cleanup cycle:")
        traceback.print_exc()
        health.record_failure("cleanup")
