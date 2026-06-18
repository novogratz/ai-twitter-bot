"""Stock Promo Bot — auto-rotates the promoted stock every ~2 weeks.

Scrapes r/wallstreetbets for the hottest AI or space stock, updates
stock_promo_config.json so reply/quote bots naturally weave it in.
Runs daily — the dedup logic only acts when the current promo is
expired or within 3 days of expiry.
"""
import json
import os
import re
import traceback
import urllib.request
from datetime import date, datetime, timedelta
from typing import Optional

from .config import QUOTE_MODEL, BOT_HANDLE, _PROJECT_ROOT
from .logger import log
from .twitter_client import scrape_x_search, quote_tweet
from .llm_client import run_llm, unwrap_text
from .engagement_log import log_reply

CONFIG_FILE = os.path.join(_PROJECT_ROOT, "stock_promo_config.json")
STATE_FILE = os.path.join(_PROJECT_ROOT, "stock_promo_state.json")

TICKER_COMPANY = {
    "NVDA": "NVIDIA", "AMD": "AMD", "INTC": "Intel", "AVGO": "Broadcom",
    "QCOM": "Qualcomm", "MRVL": "Marvell", "ARM": "Arm Holdings",
    "PLTR": "Palantir", "AI": "C3.ai", "SOUN": "SoundHound AI",
    "BBAI": "BigBear.ai", "GFAI": "Guardforce AI",
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet",
    "GOOG": "Alphabet", "META": "Meta", "AMZN": "Amazon", "TSLA": "Tesla",
    "IONQ": "IonQ", "RGTI": "Rigetti Computing", "QUBT": "Quantum Computing Inc",
    "RKLB": "Rocket Lab", "ASTS": "AST SpaceMobile", "LUNR": "Intuitive Machines",
    "SPCE": "Virgin Galactic", "ASTR": "Astra", "RDW": "Redwire",
    "MNTS": "Momentus", "LMT": "Lockheed Martin", "BA": "Boeing",
    "NOC": "Northrop Grumman", "RTX": "Raytheon", "GD": "General Dynamics",
    "KTOS": "Kratos Defense", "MAXR": "Maxar", "GSAT": "Globalstar",
    "VSAT": "Viasat",
}

_ALLOWED_TICKERS = set(TICKER_COMPANY.keys())
_TICKER_RE = re.compile(r"\$([A-Z]{2,5})\b")
WSB_API = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=50"
WSB_HEADERS = {"User-Agent": "Mozilla/5.0 AIBossGPT-bot/1.0"}
LOOKAHEAD_DAYS = 3


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _fetch_hot_tickers() -> list[tuple[str, int]]:
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
    qualified = [(t, c) for t, c in counts.items() if t in _ALLOWED_TICKERS]
    qualified.sort(key=lambda x: x[1], reverse=True)
    return qualified


def _find_best_tweet(ticker: str) -> Optional[dict]:
    queries = [f"${ticker} lang:en min_faves:20", f"${ticker} lang:en"]
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


def _should_find_new_stock(cfg: dict) -> bool:
    end_str = cfg.get("end_date", "")
    if not end_str:
        return True
    try:
        end = date.fromisoformat(end_str)
    except ValueError:
        return True
    days_left = (end - date.today()).days
    return days_left <= LOOKAHEAD_DAYS


ANNOUNCE_PROMPT = """You are @AIBossGPT. You just found the hottest AI/Space stock on WallStreetBets: ${ticker} ({company}).

Write ONE punchy tweet (max 220 chars) announcing why you're watching ${ticker}.
- Hook in the first 5 words.
- Mention it's the WSB crowd's pick.
- Sound bullish but not obnoxious.
- No price targets. No emojis. No hashtags.
- Output the tweet text ONLY."""


def run_stock_promo_cycle() -> None:
    today = date.today()
    cfg = _load_config()
    state = _load_state()

    # Operator kill-switch (2026-06-02): when the config is disabled or
    # ENABLE_STOCK_PROMO=0, do nothing — don't promote a ticker and don't
    # auto-rotate to a new one. Stops the $SPCE promo from being replaced by
    # another WSB pick. Re-enable by setting "disabled": false + ENABLE_STOCK_PROMO=1.
    if cfg.get("disabled") or os.environ.get("ENABLE_STOCK_PROMO", "0") != "1":
        log.info("[STOCK_PROMO] Disabled (kill-switch) — no ticker promoted, no rotation.")
        return

    # Operator-locked campaign (2026-06-05: $MNTS/$SPCX/$SPCE SpaceX-IPO
    # window): the rotation bot must NEVER replace it with a WSB pick.
    if cfg.get("operator_locked"):
        log.info(f"[STOCK_PROMO] Operator-locked campaign active until {cfg.get('end_date')} — no rotation.")
        return

    if not _should_find_new_stock(cfg):
        log.info(f"[STOCK_PROMO] Current promo ${cfg.get('ticker')} still active until {cfg.get('end_date')}. Skipping.")
        return

    last_scan = state.get("last_scan_date", "")
    if last_scan == today.isoformat():
        log.info("[STOCK_PROMO] Already scanned today. Skipping.")
        return

    log.info("[STOCK_PROMO] Current promo expired or expiring. Scanning WSB for next pick...")
    try:
        tickers = _fetch_hot_tickers()
    except Exception:
        log.info("[STOCK_PROMO] WSB fetch failed:")
        traceback.print_exc()
        return

    if not tickers:
        log.info("[STOCK_PROMO] No qualifying AI/Space tickers found on WSB.")
        return

    current_ticker = cfg.get("ticker", "")
    for ticker, count in tickers:
        if ticker == current_ticker:
            continue
        company = TICKER_COMPANY.get(ticker, ticker)
        new_end = today + timedelta(days=14)
        cfg["ticker"] = ticker
        cfg["company"] = company
        cfg["start_date"] = today.isoformat()
        cfg["end_date"] = new_end.isoformat()
        _save_config(cfg)
        state["last_scan_date"] = today.isoformat()
        state["last_ticker"] = ticker
        _save_state(state)
        log.info(f"[STOCK_PROMO] New pick: ${ticker} ({company}) — promoting until {new_end}.")

        try:
            tweet = _find_best_tweet(ticker)
            if tweet:
                quote = _announce_pick(ticker, company, tweet)
                if quote:
                    quote_tweet(tweet.get("url", ""), quote)
                    log.info(f"[STOCK_PROMO] Announce quote posted for ${ticker}.")
        except Exception:
            log.info("[STOCK_PROMO] Announce post failed (non-fatal):")
            traceback.print_exc()
        return

    log.info("[STOCK_PROMO] No new ticker to pick (only current ticker found or none).")


def _announce_pick(ticker: str, company: str, tweet: dict) -> Optional[str]:
    prompt = ANNOUNCE_PROMPT.format(ticker=ticker, company=company)
    result = run_llm(prompt, QUOTE_MODEL, label="STOCK_PROMO_ANNOUNCE", timeout=30)
    if result.returncode != 0 or not result.stdout:
        return None
    text = unwrap_text(result.stdout).strip()
    if not text or text.upper() == "SKIP":
        return None
    from .humanizer import smart_trim
    return smart_trim(text, 280)


def safe_run_stock_promo_cycle() -> None:
    # DISABLED 2026-06-18 (AI Big Boss): stock promotion is off-brand for a
    # purely-AI account. Set ENABLE_OFFLANE_BOTS=1 to re-enable.
    if os.environ.get("ENABLE_OFFLANE_BOTS", "0") != "1":
        return
    from . import health
    try:
        run_stock_promo_cycle()
        health.record_success("stock_promo")
    except Exception:
        log.info("[STOCK_PROMO] Unhandled error:")
        traceback.print_exc()
        health.record_failure("stock_promo")
