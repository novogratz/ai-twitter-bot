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
from typing import Optional

from .logger import log


_DDG_URL = "https://html.duckduckgo.com/html/"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def search_news(query: str, max_results: int = 6, timeout: int = 10) -> list[dict]:
    """Return [{url, title, snippet}] for the top N news-ish hits.

    Filters out X / Twitter / Reddit / HN since those aren't article sources.
    """
    if not query or not query.strip():
        return []
    params = urllib.parse.urlencode({"q": query})
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
        snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_html)).strip()[:240]
        if not title or not href.startswith("http"):
            continue
        results.append({"url": href, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def render_search_block(query: str, max_results: int = 6) -> str:
    """Run a search and format the results as a prompt-injectable block.
    Returns '' on empty / error so callers can append unconditionally."""
    hits = search_news(query, max_results=max_results)
    if not hits:
        return ""
    lines = [
        "==================================================",
        "WEB SEARCH RESULTS — frais (use these as your source URLs)",
        "==================================================",
        f"Query: {query}",
        "",
    ]
    for h in hits:
        lines.append(f"- {h['url']}")
        lines.append(f"  {h['title']}")
        if h.get("snippet"):
            lines.append(f"  > {h['snippet']}")
        lines.append("")
    return "\n".join(lines)


def search_for_news_topic(topic: str) -> str:
    """High-level helper: build a news-search query for a Décode topic
    and return the formatted prompt block."""
    topic_map = {
        "IA": "AI OpenAI Mistral Anthropic news today",
        "Crypto": "Bitcoin Ethereum crypto news today",
        "Investissement": "AI datacenter capex stargate market news today",
    }
    query = topic_map.get(topic, "AI crypto news today")
    return render_search_block(query, max_results=6)
