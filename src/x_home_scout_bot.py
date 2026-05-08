"""X home-feed scout — read OUR network's pulse for real-time signal.

The home feed shows what the accounts we follow + their network are
reacting to RIGHT NOW. This is the strongest niche signal we can get
inside X — stronger than search (where everyone's posting random stuff)
and stronger than trends (which are noisy across topics).

Strategy:
  - Every 7 min, scrape /home (existing twitter_client.scrape_home_feed).
  - Filter to AI/crypto/finance niche via the same regex used by
    rss_signal_bot + hn_signal_bot.
  - Sort by likes desc.
  - Merge into external_signal.json under a 'X_HOME' source label so
    the news prompt sees what our circle is actually engaging with.

Different from breakout_bot (which scrapes search Top tab for viral)
and mega_watch_bot (which polls 10 specific accounts every 90s) —
this is the unfiltered home-network pulse.
"""
import json
import os
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import scrape_home_feed
from .rss_signal_bot import NICHE_HITS, SIGNAL_FILE


def _load_existing() -> dict:
    if not os.path.exists(SIGNAL_FILE):
        return {"items": []}
    try:
        with open(SIGNAL_FILE, "r") as f:
            return json.load(f) or {"items": []}
    except Exception:
        return {"items": []}


def run_home_scout_cycle():
    log.info("[X-HOME] Scraping home feed for niche-matched signal...")
    try:
        tweets = scrape_home_feed(max_tweets=20)
    except Exception:
        log.info("[X-HOME] Home feed scrape failed:")
        traceback.print_exc()
        return

    if not tweets:
        log.info("[X-HOME] No tweets scraped from home feed.")
        return

    items = []
    for t in tweets:
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if not NICHE_HITS.search(text):
            continue
        likes = int(t.get("likes") or 0)
        url = t.get("url") or ""
        if not url:
            continue
        author = (t.get("author") or "").lstrip("@")
        items.append({
            "src": f"X_HOME/{author}" if author else "X_HOME",
            "title": text[:200],
            "url": url,
            "score": likes,
            "ts": "",
        })

    if not items:
        log.info("[X-HOME] No niche-matched items in this home-feed pass.")
        return

    items.sort(key=lambda i: i["score"], reverse=True)

    # Merge into external_signal.json — same dedup-by-URL logic as RSS bot.
    existing = _load_existing().get("items", [])
    seen = {it["url"] for it in items}
    merged = list(items)
    for it in existing:
        if it.get("url") and it["url"] not in seen:
            merged.append(it)
            seen.add(it["url"])
    merged = merged[:35]

    payload = {
        "ts": datetime.now().isoformat(),
        "count": len(merged),
        "items": merged,
    }
    try:
        with open(SIGNAL_FILE, "w") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"[X-HOME] Wrote {len(items)} home-feed items, "
                 f"{len(merged)} total in signal.")
    except Exception:
        log.info("[X-HOME] Failed to write signal file:")
        traceback.print_exc()


def safe_run_home_scout_cycle():
    from . import health
    try:
        run_home_scout_cycle()
        health.record_success("x_home_scout")
    except Exception:
        log.info("[X-HOME] Error during home-feed scout cycle:")
        traceback.print_exc()
        health.record_failure("x_home_scout")
