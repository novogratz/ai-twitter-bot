"""RSS signal aggregator — beat WebSearch by 20+ minutes on breaking news.

WebSearch (Google indexed) lags actual publication by 30-60 minutes.
RSS feeds publish within seconds of the article going live. So if we
poll trusted-outlet RSS every 5 minutes, we see scoops 20-50 minutes
before the news agent's WebSearch would surface them.

This is the "before everyone else" lever the user keeps asking for.

Strategy:
  - Every 5 min, fetch RSS from ~20 trusted outlets in parallel.
  - Parse with stdlib xml.etree (no feedparser dependency).
  - Filter through the same niche keyword regex as hn_signal_bot.
  - Sort by published_at desc.
  - Merge with HN/Reddit signal (just-after written by hn_signal_bot)
    into external_signal.json — single source of truth for the news
    pipeline.

No LLM, no Safari, pure HTTP. Best-effort, never blocks the bot.
"""
import json
import os
import re
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from .config import _PROJECT_ROOT
from .logger import log

SIGNAL_FILE = os.path.join(_PROJECT_ROOT, "external_signal.json")
RSS_CACHE_FILE = os.path.join(_PROJECT_ROOT, "rss_signal_cache.json")

# Trusted RSS feeds. Ordered roughly by scoop quality + freshness.
# Tier 1: wires + scoop outlets (Bloomberg/Reuters/FT/Information).
# Tier 2: AI/crypto specialised press (TC, Verge, Wired, CoinDesk).
# Tier 3: market/macro (CNBC, Axios, Yahoo Finance).
RSS_FEEDS = [
    # AI tech press
    ("TechCrunch AI",     "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("TechCrunch",        "https://techcrunch.com/feed/"),
    ("The Verge",         "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica",      "https://feeds.arstechnica.com/arstechnica/index"),
    ("Wired",             "https://www.wired.com/feed/rss"),
    ("VentureBeat AI",    "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review",   "https://www.technologyreview.com/feed/"),
    # Crypto press
    ("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",     "https://cointelegraph.com/rss"),
    ("The Block",         "https://www.theblock.co/rss.xml"),
    ("Decrypt",           "https://decrypt.co/feed"),
    # Finance / macro / business
    ("CNBC Tech",         "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
    ("CNBC Top",          "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Yahoo Finance",     "https://finance.yahoo.com/news/rssindex"),
    ("Axios Tech",        "https://api.axios.com/feed/technology/"),
    ("Reuters Tech",      "https://www.reutersagency.com/feed/?best-sectors=technology&post_type=best"),
]

# Niche-keyword filter — tweet must hit one of these.
NICHE_HITS = re.compile(
    r"\b("
    r"ai|a\.i\.|artificial intelligence|machine learning|llm|"
    r"openai|anthropic|claude|chatgpt|gpt|gemini|llama|mistral|"
    r"nvidia|nvda|deepmind|agi|datacenter|gpu|tpu|chip|"
    r"compute|hpc|power demand|power generation|electricity|grid|"
    r"nuclear|megawatt|gigawatt|coreweave|crusoe|applied digital|"
    r"iren|hive|soluna|terawulf|cipher mining|core scientific|"
    r"hugging\s?face|perplexity|copilot|robot|robotics|humanoid|agent|"
    r"bitcoin|btc|ethereum|eth|crypto|stablecoin|coinbase|binance|"
    r"defi|nft|solana|tao|bittensor|decentralized compute|"
    r"stock|nasdaq|s&p|s\&p|cac40|ipo|earnings|fed|fomc|"
    r"tesla|apple|google|alphabet|meta|amazon|microsoft|"
    r"valuation|billion|trillion|spacex|starlink|frontier tech"
    r")\b",
    re.IGNORECASE,
)


def _http_get(url: str, timeout: int = 6) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse_pub_date(s: str) -> datetime:
    if not s:
        return datetime.min
    try:
        d = parsedate_to_datetime(s)
        return d.replace(tzinfo=None) if d.tzinfo else d
    except (TypeError, ValueError):
        # Atom-style: 2026-05-08T12:34:56Z
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            return datetime.min


def _parse_feed(name: str, url: str, max_age_hours: int = 12) -> list:
    """Fetch + parse one feed. Return niche-matched items < max_age_hours."""
    try:
        body = _http_get(url, timeout=6)
    except Exception:
        return []

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    items = []
    cutoff = datetime.now() - timedelta(hours=max_age_hours)

    # RSS 2.0: <channel><item><title/><link/><pubDate/>...
    # Atom 1.0: <feed><entry><title/><link href=.../><published/>...
    # Try both.
    rss_items = root.findall(".//item")
    atom_items = root.findall("{http://www.w3.org/2005/Atom}entry")
    raw = rss_items if rss_items else atom_items

    for el in raw:
        # Title
        t_el = el.find("title") or el.find("{http://www.w3.org/2005/Atom}title")
        title = (t_el.text or "").strip() if t_el is not None else ""
        if not title:
            continue
        if not NICHE_HITS.search(title):
            continue

        # Link
        link = ""
        link_el = el.find("link")
        if link_el is not None and link_el.text:
            link = link_el.text.strip()
        else:
            atom_link = el.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = atom_link.attrib.get("href", "").strip()
        if not link:
            continue

        # Pub date
        pub_el = (
            el.find("pubDate")
            or el.find("{http://purl.org/dc/elements/1.1/}date")
            or el.find("{http://www.w3.org/2005/Atom}published")
            or el.find("{http://www.w3.org/2005/Atom}updated")
        )
        pub = _parse_pub_date(pub_el.text if pub_el is not None else "")
        if pub > datetime.min and pub < cutoff:
            continue

        items.append({
            "src": name,
            "title": title[:200],
            "url": link,
            "score": 0,  # RSS has no score; sort by recency
            "ts": pub.isoformat() if pub > datetime.min else "",
        })
    return items


def _scrape_all_feeds() -> list:
    """Fetch every RSS feed in parallel — bounded thread pool."""
    out = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_parse_feed, name, url): name for name, url in RSS_FEEDS}
        for fut in as_completed(futures, timeout=30):
            try:
                items = fut.result(timeout=10)
                out.extend(items)
            except Exception:
                # Individual feed failure is normal (timeout, 403, etc.)
                pass
    return out


def _load_existing_signal() -> dict:
    if not os.path.exists(SIGNAL_FILE):
        return {"items": []}
    try:
        with open(SIGNAL_FILE, "r") as f:
            return json.load(f) or {"items": []}
    except Exception:
        return {"items": []}


def run_rss_signal_cycle():
    log.info("[RSS] Fetching trusted-outlet RSS feeds in parallel...")
    t0 = time.time()
    rss_items = _scrape_all_feeds()
    elapsed = time.time() - t0
    log.info(f"[RSS] Got {len(rss_items)} niche items from RSS in {elapsed:.1f}s.")

    # Merge with whatever HN/Reddit pass already wrote. Dedup by URL,
    # prefer RSS entries (they have a real timestamp).
    existing = _load_existing_signal().get("items", [])
    seen = {it["url"] for it in rss_items}
    merged = list(rss_items)
    for it in existing:
        if it.get("url") and it["url"] not in seen:
            merged.append(it)
            seen.add(it["url"])

    # Sort: items with a timestamp by recency desc; items without (HN/Reddit)
    # by score desc. RSS items rise to the top because they're freshest.
    def sort_key(it):
        ts = it.get("ts") or ""
        try:
            t = datetime.fromisoformat(ts) if ts else datetime.min
        except (ValueError, TypeError):
            t = datetime.min
        score = int(it.get("score") or 0)
        # Use ts primary (recency), score secondary.
        return (t, score)

    merged.sort(key=sort_key, reverse=True)
    merged = merged[:30]  # cap

    payload = {
        "ts": datetime.now().isoformat(),
        "count": len(merged),
        "items": merged,
    }
    try:
        with open(SIGNAL_FILE, "w") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"[RSS] Wrote {len(merged)} merged items to external_signal.json.")
    except Exception:
        log.info("[RSS] Failed to write signal file:")
        traceback.print_exc()


def safe_run_rss_signal_cycle():
    from . import health
    try:
        run_rss_signal_cycle()
        health.record_success("rss_signal")
    except Exception:
        log.info("[RSS] Error during RSS cycle:")
        traceback.print_exc()
        health.record_failure("rss_signal")
