"""External-signal scout — Hacker News + Reddit for real-time tech pulse.

The news_agent already does WebSearch but searches return Google-indexed
results that lag the actual conversation by hours. HN front page and
r/MachineLearning hot are leading indicators — what's posted on those
two surfaces today usually shows up in Bloomberg / TechCrunch in 6-12h.

Output: external_signal.json with the top 20 AI/crypto/tech items
seen in the last 30 min. agent.py + breakout_bot.py + hotake_agent.py
inject this as supplemental context so the news pipeline sees the
real-time pulse, not just yesterday's wires.

No LLM, no Twitter — pure HTTP scraping. Best-effort, never blocks.
"""
import json
import os
import re
import traceback
import urllib.request
from datetime import datetime

from .config import _PROJECT_ROOT
from .logger import log

SIGNAL_FILE = os.path.join(_PROJECT_ROOT, "external_signal.json")

HN_API = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
REDDIT_ML = "https://www.reddit.com/r/MachineLearning/hot.json?limit=25"
REDDIT_CRYPTO = "https://www.reddit.com/r/CryptoCurrency/hot.json?limit=25"

# Niche-keyword filter — same intent as retweet_bot.NICHE_KEYWORDS but
# inline so we don't tangle imports.
NICHE_HITS = re.compile(
    r"\b("
    r"ai|a\.i\.|artificial intelligence|machine learning|llm|"
    r"openai|anthropic|claude|chatgpt|gpt|gemini|llama|mistral|"
    r"nvidia|nvda|deepmind|agi|datacenter|gpu|tpu|chip|"
    r"hugging\s?face|perplexity|copilot|"
    r"bitcoin|btc|ethereum|eth|crypto|stablecoin|coinbase|binance|"
    r"defi|nft|solana|"
    r"stock|nasdaq|s&p|s\&p|cac40|ipo|earnings|fed|fomc|"
    r"tesla|apple|google|alphabet|meta|amazon|microsoft|"
    r"valuation|billion|trillion"
    r")\b",
    re.IGNORECASE,
)


def _http_json(url: str, timeout: int = 6) -> dict:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "kzer-ai-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _scrape_hn(limit: int = 30) -> list:
    ids = _http_json(HN_API)
    if not isinstance(ids, list):
        return []
    out = []
    for i in ids[:limit]:
        item = _http_json(HN_ITEM.format(id=i))
        if not item:
            continue
        title = item.get("title") or ""
        url = item.get("url") or f"https://news.ycombinator.com/item?id={i}"
        score = int(item.get("score") or 0)
        if NICHE_HITS.search(title):
            out.append({
                "src": "HN",
                "title": title[:200],
                "url": url,
                "score": score,
            })
    return out


def _scrape_reddit(api_url: str, src_label: str) -> list:
    data = _http_json(api_url)
    if not isinstance(data, dict):
        return []
    out = []
    for child in (data.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        title = d.get("title") or ""
        if not NICHE_HITS.search(title):
            continue
        out.append({
            "src": src_label,
            "title": title[:200],
            "url": "https://www.reddit.com" + (d.get("permalink") or ""),
            "score": int(d.get("score") or 0),
        })
    return out


def run_signal_cycle():
    log.info("[HN-SIGNAL] Scraping HN + Reddit...")
    items = []
    try:
        items.extend(_scrape_hn(30))
    except Exception:
        log.info("[HN-SIGNAL] HN scrape failed:")
        traceback.print_exc()
    try:
        items.extend(_scrape_reddit(REDDIT_ML, "r/ML"))
    except Exception:
        log.info("[HN-SIGNAL] Reddit ML scrape failed:")
        traceback.print_exc()
    try:
        items.extend(_scrape_reddit(REDDIT_CRYPTO, "r/CC"))
    except Exception:
        log.info("[HN-SIGNAL] Reddit crypto scrape failed:")
        traceback.print_exc()

    # Sort by score desc, dedup by url, cap at 20.
    items.sort(key=lambda x: x["score"], reverse=True)
    seen = set()
    unique = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        unique.append(it)
        if len(unique) >= 20:
            break

    payload = {
        "ts": datetime.now().isoformat(),
        "count": len(unique),
        "items": unique,
    }
    try:
        with open(SIGNAL_FILE, "w") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"[HN-SIGNAL] Wrote {len(unique)} items.")
    except Exception:
        log.info("[HN-SIGNAL] Failed to write signal file:")
        traceback.print_exc()


def render_signal_block(max_items: int = 8) -> str:
    """Render the most recent external signal as a prompt block for the
    news / breakout / hotake agents. Empty string if no signal file yet."""
    if not os.path.exists(SIGNAL_FILE):
        return ""
    try:
        with open(SIGNAL_FILE, "r") as f:
            d = json.load(f)
    except Exception:
        return ""
    items = (d.get("items") or [])[:max_items]
    if not items:
        return ""
    lines = ["==================================================",
             "EXTERNAL SIGNAL — what HN + Reddit are reacting to NOW",
             "==================================================",
             "(scraped from HN front page + r/MachineLearning + r/CC; the"
             " stories below are leading indicators that usually hit"
             " Bloomberg/TechCrunch in 6-12h. If any of these match a"
             " trusted-source article from your WebSearch, prefer it —"
             " you're probably the first to react.)\n"]
    for it in items:
        lines.append(f"- [{it.get('src','?')} {it.get('score',0)} pts] {it.get('title','')[:160]}")
        lines.append(f"  {it.get('url','')}")
    return "\n".join(lines)


def safe_run_signal_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_signal_cycle()
        health.record_success("hn_signal")
    except Exception:
        log.info("[HN-SIGNAL] Error during signal cycle:")
        traceback.print_exc()
        health.record_failure("hn_signal")
