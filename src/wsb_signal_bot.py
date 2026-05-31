"""WSB Signal Bot — weekly AI/Space stock hype quote.

Every Saturday: scrapes r/wallstreetbets for the hottest ticker,
filters to AI or space stocks only, finds the best tweet about it,
and quote-tweets it with a punchy @AISpaceDecoder take.
"""
import json
import os
import re
import traceback
import urllib.request
from datetime import date, datetime
from typing import Optional

from .config import QUOTE_MODEL, BOT_HANDLE, _PROJECT_ROOT
from .logger import log
from .twitter_client import scrape_x_search, quote_tweet
from .llm_client import run_llm, unwrap_text
from .engagement_log import log_reply

STATE_FILE = os.path.join(_PROJECT_ROOT, "wsb_signal_state.json")

# AI or space stocks we'll act on. Extend freely — the WSB scraper
# only picks from tickers it finds; this list gates which ones qualify.
ALLOWED_TICKERS = {
    # AI / semiconductors
    "NVDA", "AMD", "INTC", "AVGO", "QCOM", "MRVL", "ARM",
    "PLTR", "AI", "SOUN", "BBAI", "GFAI", "AAPL", "MSFT",
    "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "IONQ", "RGTI", "QUBT",  # quantum
    # Space
    "RKLB", "ASTS", "LUNR", "SPCE", "ASTR", "RDW", "MNTS",
    "LMT", "BA", "NOC", "RTX", "GD", "KTOS", "AJRD",
    "MAXR", "GSAT", "VSAT",
    # Space ETFs
    "UFO", "ARKX",
}

# Pattern: $TICKER anywhere in title/selftext, 2-5 uppercase letters
_TICKER_RE = re.compile(r"\$([A-Z]{2,5})\b")

WSB_API = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=50"
WSB_HEADERS = {
    "User-Agent": "Mozilla/5.0 AISpaceDecoder-bot/1.0",
}

QUOTE_PROMPT = """\
You are @AISpaceDecoder — The AI & Space Decoder. You just saw this tweet about ${ticker}:

@{author}: \"{tweet_text}\"

Write ONE punchy quote-tweet in English. Rules:
- Max 220 characters (original tweet renders below yours automatically).
- HOOK in first 5 words: a number, bold claim, or sharp observation.
- Voice: confident, slightly audacious, data-driven. Think quant analyst who also memes.
- You're excited about {ticker} because it sits at the AI/Space intersection — make that angle clear.
- Never make specific price predictions or claim "10x" or "to the moon".
- No hashtags. No filler. No "I think". No "This is not financial advice" disclaimers inline.
- End with 1-2 relevant emojis max (🚀 ⚡ 🛰️ 🤖 are on-brand).

Output the quote text ONLY. No quotes, no labels.
"""


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _fetch_wsb_tickers() -> list[tuple[str, int]]:
    """Return list of (TICKER, mention_count) from WSB hot, desc order."""
    req = urllib.request.Request(WSB_API, headers=WSB_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    posts = data.get("data", {}).get("children", [])
    counts: dict[str, int] = {}
    for post in posts:
        pd = post.get("data", {})
        blob = f"{pd.get('title', '')} {pd.get('selftext', '')}"
        for ticker in _TICKER_RE.findall(blob):
            counts[ticker] = counts.get(ticker, 0) + 1

    qualified = [(t, c) for t, c in counts.items() if t in ALLOWED_TICKERS]
    qualified.sort(key=lambda x: x[1], reverse=True)
    return qualified


def _find_best_tweet(ticker: str) -> Optional[dict]:
    """Search X for the best tweet about this ticker today."""
    queries = [
        f"${ticker} lang:en min_faves:20",
        f"${ticker} lang:en",
    ]
    candidates = []
    for q in queries:
        try:
            tweets = scrape_x_search(q, max_tweets=20, tab="latest")
            candidates.extend(tweets)
            if len(candidates) >= 10:
                break
        except Exception:
            pass

    if not candidates:
        return None

    from . import respect_list
    candidates = [c for c in candidates if not respect_list.is_protected(c.get("author", ""))]
    candidates = [c for c in candidates if (c.get("author", "").lower() != BOT_HANDLE.lower())]
    candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    return candidates[0] if candidates else None


def _generate_quote(ticker: str, author: str, tweet_text: str) -> Optional[str]:
    prompt = QUOTE_PROMPT.format(ticker=ticker, author=author, tweet_text=tweet_text)
    result = run_llm(prompt, QUOTE_MODEL, label="WSB_SIGNAL", output_json=False, timeout=60)
    if result.returncode != 0 or not result.stdout:
        return None
    text = unwrap_text(result.stdout).strip()
    if len(text) > 280:
        text = text[:277] + "..."
    return text or None


def run_wsb_signal_cycle() -> None:
    state = _load_state()
    week_key = date.today().strftime("%Y-W%W")

    if state.get("last_week") == week_key:
        log.info(f"[WSB_SIGNAL] Already ran this week ({week_key}). Skipping.")
        return

    log.info("[WSB_SIGNAL] Fetching WSB hot tickers...")
    try:
        tickers = _fetch_wsb_tickers()
    except Exception:
        log.info("[WSB_SIGNAL] Failed to fetch WSB:")
        traceback.print_exc()
        return

    if not tickers:
        log.info("[WSB_SIGNAL] No qualifying AI/Space tickers on WSB this week.")
        return

    log.info(f"[WSB_SIGNAL] Top picks: {tickers[:5]}")

    for ticker, count in tickers[:5]:
        log.info(f"[WSB_SIGNAL] Trying ${ticker} ({count} mentions)...")
        tweet = _find_best_tweet(ticker)
        if not tweet:
            log.info(f"[WSB_SIGNAL] No tweet found for ${ticker}, trying next.")
            continue

        author = tweet.get("author", "someone")
        text = tweet.get("text", "")
        likes = int(tweet.get("likes") or 0)
        url = tweet.get("url", "")

        log.info(f"[WSB_SIGNAL] Best tweet: @{author} ({likes} likes) — {text[:80]}")

        quote = _generate_quote(ticker, author, text)
        if not quote:
            log.info(f"[WSB_SIGNAL] LLM produced no quote for ${ticker}, trying next.")
            continue

        log.info(f"[WSB_SIGNAL] Quoting: {quote}")
        try:
            quote_tweet(url, quote)
            try:
                log_reply(url, quote, action_type="quote", source=f"WSB_SIGNAL/{ticker}")
            except Exception:
                pass
            state["last_week"] = week_key
            state["last_ticker"] = ticker
            state["last_run"] = datetime.utcnow().isoformat()
            _save_state(state)
            log.info(f"[WSB_SIGNAL] Posted ${ticker} quote. Done for week {week_key}.")
            return
        except Exception:
            log.info(f"[WSB_SIGNAL] Post failed for ${ticker}:")
            traceback.print_exc()

    log.info("[WSB_SIGNAL] No ticker produced a postable quote this week.")


def safe_run_wsb_signal_cycle() -> None:
    from . import health
    try:
        run_wsb_signal_cycle()
        health.record_success("wsb_signal")
    except Exception:
        log.info("[WSB_SIGNAL] Unhandled error:")
        traceback.print_exc()
        health.record_failure("wsb_signal")
