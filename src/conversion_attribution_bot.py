"""Conversion attribution — learn WHICH reply targets actually convert.

Closes the loop that engagement_targeting left open ("conversion attribution
can refine the weight later" — its per-author weight was static 1.0 forever).

Hourly:
  1. Scrape the freshest handles on our /followers page (new followers are
     listed first).
  2. Diff against the followers we've already seen (state file).
  3. For each NEW follower: if we replied in their thread (they authored a
     tweet we replied to) within the last ATTRIBUTION_WINDOW_HOURS, that's a
     CONVERSION — bump the author's weight in engagement_targets_log.json so
     engagement_targeting ranks their future posts higher.

Weight: +0.5 per conversion, capped at 3.0. No decay for now — winners just
rise. The reply→author mapping comes from engagement_log.csv (type=reply,
target_url carries the parent author's handle).
"""
import csv
import json
import os
import traceback
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT
from .logger import log

ENGAGEMENT_LOG = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
TARGETS_LOG = os.path.join(_PROJECT_ROOT, "engagement_targets_log.json")
STATE_FILE = os.path.join(_PROJECT_ROOT, "conversion_attribution_state.json")

ATTRIBUTION_WINDOW_HOURS = float(os.environ.get("ATTRIBUTION_WINDOW_HOURS", "48"))
WEIGHT_BUMP = float(os.environ.get("CONVERSION_WEIGHT_BUMP", "0.5"))
WEIGHT_CAP = float(os.environ.get("CONVERSION_WEIGHT_CAP", "3.0"))


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _recent_reply_authors() -> set:
    """Handles whose tweets we replied to within the attribution window."""
    cutoff = datetime.now() - timedelta(hours=ATTRIBUTION_WINDOW_HOURS)
    authors = set()
    try:
        with open(ENGAGEMENT_LOG) as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) < 4 or row[1] != "reply":
                    continue
                try:
                    if datetime.fromisoformat(row[0].replace(" ", "T")) < cutoff:
                        continue
                except ValueError:
                    continue
                url = row[3] or ""
                if "x.com/" in url:
                    try:
                        authors.add(url.split("x.com/")[1].split("/")[0].lower())
                    except IndexError:
                        pass
    except OSError:
        pass
    return authors


def run_conversion_attribution_cycle():
    from .followback_bot import _scrape_followers_list

    try:
        current = [h.lower() for h in (_scrape_followers_list(max_handles=30) or []) if h]
    except Exception:
        log.info("[ATTRIB] Followers scrape failed:")
        traceback.print_exc()
        return
    if not current:
        log.info("[ATTRIB] No followers scraped this cycle.")
        return

    state = _load_json(STATE_FILE, {})
    seen = set(state.get("seen", []))
    new_followers = [h for h in current if h not in seen]

    # First run: just seed the seen-set, no attribution (everyone is "new").
    if not seen:
        state["seen"] = current
        _save_json(STATE_FILE, state)
        log.info(f"[ATTRIB] Seeded follower baseline ({len(current)} handles).")
        return

    if not new_followers:
        log.info("[ATTRIB] No new followers since last cycle.")
        return

    reply_authors = _recent_reply_authors()
    conversions = [h for h in new_followers if h in reply_authors]

    targets = _load_json(TARGETS_LOG, {})
    authors_state = targets.setdefault("authors", {})
    for h in conversions:
        # Author keys in engagement_targets_log may carry original casing —
        # match case-insensitively.
        key = next((k for k in authors_state if k.lower() == h), h)
        rec = authors_state.setdefault(key, {"replies": 0, "weight": 1.0})
        old_w = float(rec.get("weight", 1.0))
        rec["weight"] = min(WEIGHT_CAP, old_w + WEIGHT_BUMP)
        rec["conversions"] = int(rec.get("conversions", 0)) + 1
        log.info(f"[ATTRIB] CONVERSION: @{h} followed after our reply — weight {old_w:.1f} → {rec['weight']:.1f}")
    if conversions:
        _save_json(TARGETS_LOG, targets)

    seen.update(new_followers)
    state["seen"] = list(seen)[-2000:]
    state["last_run"] = datetime.now().isoformat()
    _save_json(STATE_FILE, state)
    log.info(f"[ATTRIB] {len(new_followers)} new follower(s), {len(conversions)} attributed to replies.")


def safe_run_conversion_attribution_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_conversion_attribution_cycle()
        health.record_success("conversion_attribution")
    except Exception:
        log.info("[ATTRIB] Error during attribution cycle:")
        traceback.print_exc()
        health.record_failure("conversion_attribution")
