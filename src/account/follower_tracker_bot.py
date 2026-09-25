"""Follower-count tracker — measure growth so we can tune.

Without a follower-count time series we can't tell which days/cycles
ACTUALLY drove growth vs. which just felt productive. This bot scrapes
the Account's profile every 30 min, parses the follower count from the profile
header via JS, and appends to follower_history.json.

No LLM, just one Safari visit + JS extraction.
"""
import re
import time
import traceback
from datetime import datetime

from ..core import config
from ..core.logger import log
from ..guards.follow_policy import FOLLOWER_HISTORY
from ..x import safari
from ..x.safari import _safari_lock, close_front_tab


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
    """Open the Account's profile, JS-extract the number next to 'Followers' / 'Abonnés'."""
    js_code = '''
    (function() {
        // Followers link looks like /<handle>/verified_followers or /followers.
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

    with _safari_lock:
        url = f"https://x.com/{config.BOT_HANDLE}"
        log.info(f"[FOLLOWER] Opening {url}")
        safari.open_url(url)
        time.sleep(7)

        raw = safari._run_js(js_code, 20, log_prefix="[FOLLOWER]", activate=True)
        close_front_tab()
        try:
            return _parse_count(raw)
        except ValueError:
            log.info(f"[FOLLOWER] Unreadable follower count: {raw[:40]!r}")
            return 0


def _load_history() -> list:
    return FOLLOWER_HISTORY.read()


def _save_history(arr: list):
    # Keep last 1500 samples — at 30 min cadence that's ~31 days.
    FOLLOWER_HISTORY.write(arr[-1500:])


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
    from ..core import health
    try:
        run_follower_tracker_cycle()
        health.record_success("follower_tracker")
    except Exception:
        log.info("[FOLLOWER] Error during follower-tracker cycle:")
        traceback.print_exc()
        health.record_failure("follower_tracker")
