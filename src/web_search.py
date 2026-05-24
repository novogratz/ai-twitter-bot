"""Lightweight web search via DuckDuckGo HTML — no API key needed.

The bot's primary path (Claude) has WebSearch built in. When we fall back
to local ollama (qwen3.6) there's no native search. This module gives
ollama fresh URLs + snippets it can use as sources, so a Décode shipped
via the fallback still has real content backing it.

Best-effort. Returns [] on any error so callers can no-op cleanly.
"""
import html
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from .logger import log


_DDG_URL = "https://html.duckduckgo.com/html/"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Strip URLs that have a year in the path older than the current year.
# CoinDesk / Bloomberg / TC etc all encode publication date in the URL
# (e.g. /2024/02/08/...). Catches obviously-stale links before we even
# show them to the LLM. Match /YYYY/ where YYYY is 1990-currentYear-1.
_OLD_YEAR_RE = re.compile(r"/(19[9]\d|20[0-2]\d)/")


def _url_is_recent(url: str, max_year_offset: int = 0) -> bool:
    """True if URL's path doesn't reveal a year older than (current-offset).
    Offset=0 means current year only; 1 means current OR previous year."""
    m = _OLD_YEAR_RE.search(url or "")
    if not m:
        return True  # no year in path → can't tell, allow it
    try:
        year = int(m.group(1))
    except (ValueError, TypeError):
        return True
    return year >= (datetime.now().year - max_year_offset)


def search_news(query: str, max_results: int = 6, timeout: int = 10,
                date_filter: str = "w") -> list[dict]:
    """Return [{url, title, snippet}] for the top N news-ish hits.

    Filters out X / Twitter / Reddit / HN since those aren't article sources.

    date_filter: DuckDuckGo time scope — 'd' past day, 'w' past week
    (default), 'm' past month, 'y' past year, '' = no filter. Top 5
    weekly recap uses 'w'; breaking-news Décodes can use 'd'.
    """
    if not query or not query.strip():
        return []
    qs = {"q": query}
    if date_filter:
        qs["df"] = date_filter
    params = urllib.parse.urlencode(qs)
    req = urllib.request.Request(
        f"{_DDG_URL}?{params}",
        headers={"User-Agent": _UA},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        log.info(f"[WEBSEARCH] HTTP error: {e}")
        return []
    except Exception as e:
        log.info(f"[WEBSEARCH] unexpected error: {e}")
        return []

    results = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    for m in pattern.finditer(body):
        href_raw, title_html, snippet_html = m.groups()
        # DDG wraps outbound links in a redirect; unwrap.
        rd = re.search(r"uddg=([^&]+)", href_raw)
        href = urllib.parse.unquote(rd.group(1)) if rd else href_raw
        # Filter non-article hosts
        if any(d in href.lower() for d in (
            "x.com/", "twitter.com/", "reddit.com/", "news.ycombinator.com",
            "youtube.com/", "youtu.be/",
        )):
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        # 2026-05-23 PM: bumped snippet length 240 → 500 chars so the LLM
        # sees more of the article's lede (where the real numbers live).
        # Without this it hallucinates plausible-but-wrong numbers.
        snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_html)).strip()[:500]
        if not title or not href.startswith("http"):
            continue
        # Belt-and-suspenders: drop URLs with an obviously-old year in the
        # path even if DDG's df=w let one slip through.
        if not _url_is_recent(href):
            continue
        results.append({"url": href, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def render_search_block(query: str, max_results: int = 6,
                        date_filter: str = "w") -> str:
    """Run a search and format the results as a prompt-injectable block.
    Returns '' on empty / error so callers can append unconditionally."""
    hits = search_news(query, max_results=max_results, date_filter=date_filter)
    if not hits:
        return ""
    lines = [
        "==================================================",
        "WEB SEARCH RESULTS — frais (use these as your source URLs)",
        "==================================================",
        f"Query: {query} (date_filter={date_filter})",
        "",
    ]
    for h in hits:
        lines.append(f"- {h['url']}")
        lines.append(f"  {h['title']}")
        if h.get("snippet"):
            lines.append(f"  > {h['snippet']}")
        lines.append("")
    return "\n".join(lines)


def search_for_news_topic(topic: str, date_filter: str = "w") -> str:
    """High-level helper: build a news-search query for a Décode topic
    and return the formatted prompt block.

    date_filter defaults to past week so we never feed the LLM 2-year-old
    articles. Top 5 weekly recap: 'w'. Breaking-news single Décode: caller
    can pass 'd' for past-day-only.

    2026-05-22 PM: broadened to MULTIPLE sub-queries per topic — single
    query was too narrow for Top 5 (5 bullets need 5 different angles).
    Runs 3 queries, merges results, dedups by URL.
    """
    queries_by_topic = {
        "IA": [
            "AI datacenter power demand megawatt gigawatt news this week",
            "OpenAI Anthropic xAI compute GPU cluster datacenter news this week",
            "NVIDIA GPU power grid nuclear AI datacenter news this week",
            "robotics humanoid robots frontier tech AI infrastructure news this week",
        ],
        "Crypto": [
            "TAO Bittensor decentralized compute AI crypto news this week",
            "crypto mining AI hosting HIVE IREN TeraWulf Core Scientific news this week",
            "Bitcoin miners AI datacenter HPC MARA Riot CleanSpark news this week",
        ],
        "Investissement": [
            "CoreWeave CRWV Applied Digital APLD IREN HIVE SLNH AI datacenter stocks this week",
            "AI power generation grid nuclear datacenter stocks energy demand this week",
            "TeraWulf WULF Cipher CIFR Core Scientific CORZ AI hosting HPC this week",
        ],
        "Space": [
            "SpaceX Starship Starlink space infrastructure news this week",
            "Blue Origin New Glenn Rocket Lab launch capacity news this week",
            "satellite AI robotics space infrastructure frontier tech news this week",
            "SpaceX valuation Starlink revenue private markets news this week",
        ],
    }
    queries = queries_by_topic.get(topic, ["AI crypto news this week"])
    all_hits = []
    seen_urls = set()
    for q in queries:
        for hit in search_news(q, max_results=4, date_filter=date_filter):
            if hit["url"] in seen_urls:
                continue
            seen_urls.add(hit["url"])
            all_hits.append(hit)
        if len(all_hits) >= 12:
            break
    if not all_hits:
        return ""
    lines = [
        "==================================================",
        f"WEB SEARCH RESULTS — past week, multi-angle ({len(all_hits)} hits)",
        "Pick the URL whose title best matches bullet #1 — copy EXACTLY.",
        "==================================================",
        "",
    ]
    for h in all_hits:
        lines.append(f"- {h['url']}")
        lines.append(f"  {h['title']}")
        if h.get("snippet"):
            lines.append(f"  > {h['snippet']}")
        lines.append("")
    return "\n".join(lines)


def load_recent_signals(max_age_days: int = 10, limit: int = 10) -> list[dict]:
    """Pull article URLs from external_signal.json (RSS feed pool) that are
    ≤max_age_days old and NOT X/Twitter posts. Returns newest first.

    Why: the prompt's web_block was only DDG search results. The RSS pool
    (TechCrunch / CoinDesk / TheBlock / Bloomberg-style) is a much higher-
    signal source with real publication timestamps. Injecting it gives the
    LLM 5-10 fresh article URLs to pick from for bullet #1's link card.
    """
    import json as _json, os as _os
    from datetime import timedelta
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    path = _os.path.join(here, "external_signal.json")
    try:
        with open(path) as f:
            data = _json.load(f) or {}
    except (FileNotFoundError, _json.JSONDecodeError):
        return []
    items = data.get("items") or []
    cutoff = datetime.now() - timedelta(days=max_age_days)
    out = []
    for it in items:
        url = (it.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        if any(d in url.lower() for d in (
            "x.com/", "twitter.com/", "reddit.com/", "news.ycombinator.com",
        )):
            continue
        ts_raw = (it.get("ts") or "").strip()
        try:
            ts = datetime.fromisoformat(ts_raw)
            if ts < cutoff:
                continue
        except (ValueError, TypeError):
            # No timestamp — keep, can't verify age (RSS items have ts;
            # HN/Reddit may not — those are usually fresh anyway).
            pass
        out.append({
            "url": url,
            "title": (it.get("title") or "").strip(),
            "source": (it.get("source") or "").strip(),
            "ts": ts_raw,
        })
        if len(out) >= limit:
            break
    return out


def render_signals_block(items: list[dict]) -> str:
    """Format recent RSS-pool items as a prompt-injectable block."""
    if not items:
        return ""
    lines = [
        "==================================================",
        f"CURATED RSS / NEWS POOL — past 10 days ({len(items)} items)",
        "Real article URLs from TechCrunch / CoinDesk / TheBlock / etc.",
        "Use one of these as the trailing URL — copy EXACTLY.",
        "==================================================",
        "",
    ]
    for it in items:
        src = f" [{it['source']}]" if it.get("source") else ""
        lines.append(f"- {it['url']}{src}")
        lines.append(f"  {it['title']}")
        lines.append("")
    return "\n".join(lines)
