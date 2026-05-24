"""X feed scout — read and train OUR network's pulse for real-time signal.

Home/For You shows what X is pushing. Following shows what our chosen graph
is posting. Targeted searches pull the account back toward crypto / AI /
bourse when the feed drifts.

Strategy:
  - Every cycle, scrape /home and the Following tab.
  - Also scrape targeted X searches for crypto / AI / bourse.
  - Filter to AI/crypto/finance niche via the same regex used by
    rss_signal_bot + hn_signal_bot.
  - Sort by likes desc.
  - Merge into external_signal.json under X_* source labels so
    the news prompt sees what our circle is actually engaging with.

Different from breakout_bot (which scrapes search Top tab for viral)
and mega_watch_bot (which polls 10 specific accounts every 90s) —
this is the unfiltered home-network pulse.
"""
import json
import os
import random
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import scrape_following_feed, scrape_home_feed, scrape_x_search
from .rss_signal_bot import NICHE_HITS, SIGNAL_FILE

SEARCH_QUERIES = [
    "AI datacenter OR power demand lang:en min_faves:100",
    "megawatt OR gigawatt OR nuclear AI lang:en min_faves:100",
    "CoreWeave OR CRWV OR APLD lang:en min_faves:100",
    "IREN OR HIVE OR TeraWulf lang:en min_faves:100",
    "TAO OR Bittensor OR decentralized compute lang:en min_faves:100",
    "Nvidia OR GPU OR compute cluster lang:en min_faves:100",
    "robotics OR humanoid robots OR frontier tech lang:en min_faves:100",
    "SpaceX OR Starlink OR space infrastructure lang:en min_faves:100",
]
SEARCHES_PER_CYCLE = int(os.environ.get("X_FEED_SEARCHES_PER_CYCLE", "2"))


def _load_existing() -> dict:
    if not os.path.exists(SIGNAL_FILE):
        return {"items": []}
    try:
        with open(SIGNAL_FILE, "r") as f:
            return json.load(f) or {"items": []}
    except Exception:
        return {"items": []}


def _collect_feed_items() -> list[tuple[str, dict]]:
    """Scrape Home, Following, and targeted searches. Each client helper owns
    the Safari lock, so keep this sequential and bounded."""
    collected = []

    try:
        log.info("[X-FEED] Scraping Home / For You for niche-matched signal...")
        collected.extend(("X_HOME", t) for t in scrape_home_feed(max_tweets=20) or [])
    except Exception:
        log.info("[X-FEED] Home feed scrape failed:")
        traceback.print_exc()

    try:
        log.info("[X-FEED] Scraping Following tab for niche-matched signal...")
        collected.extend(("X_FOLLOWING", t) for t in scrape_following_feed(max_tweets=25) or [])
    except Exception:
        log.info("[X-FEED] Following feed scrape failed:")
        traceback.print_exc()

    queries = random.sample(SEARCH_QUERIES, k=min(SEARCHES_PER_CYCLE, len(SEARCH_QUERIES)))
    for query in queries:
        try:
            tab = "top" if random.random() < 0.6 else "live"
            log.info(f"[X-FEED] Searching X {tab}: {query}")
            collected.extend((f"X_SEARCH/{tab}/{query}", t) for t in scrape_x_search(query, max_tweets=12, tab=tab) or [])
        except Exception:
            log.info(f"[X-FEED] Search scrape failed for {query!r}:")
            traceback.print_exc()
    return collected


def run_home_scout_cycle():
    scraped = _collect_feed_items()

    if not scraped:
        log.info("[X-FEED] No tweets scraped from Home/Following/search.")
        return

    items = []
    for source, t in scraped:
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
            "src": f"{source}/{author}" if author else source,
            "title": text[:200],
            "url": url,
            "score": likes,
            "ts": "",
        })

    if not items:
        log.info("[X-FEED] No niche-matched items in this feed/search pass.")
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
        log.info(f"[X-FEED] Wrote {len(items)} feed/search items, "
                 f"{len(merged)} total in signal.")
    except Exception:
        log.info("[X-FEED] Failed to write signal file:")
        traceback.print_exc()


def safe_run_home_scout_cycle():
    from . import health
    try:
        run_home_scout_cycle()
        health.record_success("x_home_scout")
    except Exception:
        log.info("[X-FEED] Error during feed scout cycle:")
        traceback.print_exc()
        health.record_failure("x_home_scout")
