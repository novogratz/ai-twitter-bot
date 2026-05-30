"""Follower-count tracker — measure growth so we can tune.

Without a follower-count time series we can't tell which days/cycles
ACTUALLY drove growth vs. which just felt productive. This bot scrapes
/AISpaceDecoder every 30 min, parses the follower count from the profile
header via JS, and appends to follower_history.json. The
meta_strategy_agent reads the recent slope on every cycle and feeds
'we gained N followers in the last 24h' into its prompt.

No LLM, just one Safari visit + JS extraction.
"""
import json
import os
import re
import subprocess
import tempfile
import time
import traceback
import webbrowser
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import _safari_lock, close_front_tab

FOLLOWER_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "follower_history.json")


def _parse_count(s: str) -> int:
    """X renders counts as '1,234' or '1.2K' or '1.5M'. Normalize to int."""
    if not s:
        return 0
    s = s.strip().replace(",", "").replace(" ", "").replace("\xa0", "")
    m = re.match(r"^([\d.]+)\s*([KMm])?$", s)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else 0
    val = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    if suffix == "k":
        return int(val * 1000)
    if suffix == "m":
        return int(val * 1_000_000)
    return int(val)


def _scrape_follower_count() -> int:
    """Open /AISpaceDecoder, JS-extract the number next to 'Followers' / 'Abonnés'."""
    js_code = '''
    (function() {
        // Followers link looks like /AISpaceDecoder/verified_followers or /followers.
        var anchors = document.querySelectorAll('a[href$="/followers"], a[href$="/verified_followers"]');
        for (var a of anchors) {
            // The count is in the first child span (or a nested span with text).
            var spans = a.querySelectorAll('span');
            for (var s of spans) {
                var t = (s.textContent || '').trim();
                if (/^[\\d.,KMkm\\s\\u202f\\xa0]+$/.test(t) && t.length > 0) {
                    return t;
                }
            }
        }
        return '';
    })()
    '''
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    tmp.write(js_code)
    tmp.close()
    applescript = f'''
    tell application "Safari" to activate
    set jsCode to (read POSIX file "{tmp.name}")
    tell application "Safari"
        set result to do JavaScript jsCode in current tab of front window
    end tell
    '''

    with _safari_lock:
        url = f"https://x.com/{BOT_HANDLE}"
        log.info(f"[FOLLOWER] Opening {url}")
        webbrowser.open(url)
        time.sleep(7)

        try:
            r = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True, text=True, timeout=20,
            )
            os.unlink(tmp.name)
            close_front_tab()
            if r.returncode != 0:
                log.info(f"[FOLLOWER] JS failed: {r.stderr[:160]}")
                return 0
            raw = (r.stdout or "").strip()
            return _parse_count(raw)
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            try:
                close_front_tab()
            except Exception:
                pass
            log.info("[FOLLOWER] Scrape exception:")
            traceback.print_exc()
            return 0


def _load_history() -> list:
    if not os.path.exists(FOLLOWER_HISTORY_FILE):
        return []
    try:
        with open(FOLLOWER_HISTORY_FILE, "r") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_history(arr: list):
    # Keep last 1500 samples — at 30 min cadence that's ~31 days.
    arr = arr[-1500:]
    with open(FOLLOWER_HISTORY_FILE, "w") as f:
        json.dump(arr, f, indent=2)


def get_growth_block() -> str:
    """Render a prompt block summarising recent follower delta. Empty when
    we don't have at least 2 samples."""
    arr = _load_history()
    if len(arr) < 2:
        return ""
    latest = arr[-1]
    now_ts = datetime.fromisoformat(latest["ts"])
    now_count = int(latest.get("count") or 0)

    def find_delta(hours: int) -> int:
        cutoff = now_ts - timedelta(hours=hours)
        for entry in reversed(arr[:-1]):
            try:
                ts = datetime.fromisoformat(entry["ts"])
            except (ValueError, KeyError):
                continue
            if ts <= cutoff:
                return now_count - int(entry.get("count") or 0)
        return now_count - int(arr[0].get("count") or 0)

    d1 = find_delta(1)
    d24 = find_delta(24)
    d168 = find_delta(168)

    return (
        "==================================================\n"
        "FOLLOWER GROWTH SIGNAL (your scoreboard)\n"
        "==================================================\n"
        f"Current followers: {now_count}\n"
        f"Last 1h:    {d1:+d}\n"
        f"Last 24h:   {d24:+d}\n"
        f"Last 7d:    {d168:+d}\n"
        "Goal: 10k. Every tweet you write should pass the test:\n"
        "'will this earn ONE follow?' If not → SKIP.\n"
    )


def run_follower_tracker_cycle():
    count = _scrape_follower_count()
    if count <= 0:
        log.info("[FOLLOWER] Scrape returned 0 — likely DOM miss; skipping save.")
        return
    arr = _load_history()
    prev = int(arr[-1]["count"]) if arr else None
    arr.append({"ts": datetime.now().isoformat(), "count": count})
    _save_history(arr)
    if prev is not None:
        delta = count - prev
        log.info(f"[FOLLOWER] Count: {count} ({delta:+d} since last sample).")
    else:
        log.info(f"[FOLLOWER] First sample logged: {count}.")


def safe_run_follower_tracker_cycle():
    from . import health
    try:
        run_follower_tracker_cycle()
        health.record_success("follower_tracker")
    except Exception:
        log.info("[FOLLOWER] Error during follower-tracker cycle:")
        traceback.print_exc()
        health.record_failure("follower_tracker")
