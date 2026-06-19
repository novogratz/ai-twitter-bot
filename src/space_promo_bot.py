"""Space promo bot — operator campaign posts for the SpaceX IPO window.

Operator mandate 2026-06-05: softly promote $SPCX (SpaceX IPO June 12),
$SPCE (Virgin Galactic) and most importantly $MNTS (Momentus) while the IPO
hype window is open. Reference post (manual, 1.5K views): bullish space-
stocks call + tickers + "Non financial advice" + company @tags + a hype GIF.

Design:
  - reads the SAME stock_promo_config.json as the reply/quote soft-promo;
    auto-dies after end_date or when the config is disabled — no code change
    needed to stop the campaign.
  - max MAX_SPACE_PROMO_PER_DAY standalone posts/day (default 2).
  - anchored when possible: pulls a fresh space/IPO item from
    external_signal.json as context so the post rides actual news.
  - every post ends with a non-advice disclaimer (always).
  - attaches a random GIF from media/promo_gifs/ when one exists (operator
    drops curated GIFs there — Virgin Galactic flight, Wolf of Wall Street…);
    falls back to text-only.
  - all posts go through post_tweet (dedup v2 + caps + spacing + hard rules).
"""
import json
import os
import random
import time
import traceback
from datetime import date, datetime

from .config import _PROJECT_ROOT, HOTAKE_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import post_tweet
from .humanizer import humanize, strip_agent_preamble

PROMO_CONFIG_FILE = os.path.join(_PROJECT_ROOT, "stock_promo_config.json")
PROMO_STATE_FILE = os.path.join(_PROJECT_ROOT, "space_promo_state.json")
PROMO_GIF_DIR = os.path.join(_PROJECT_ROOT, "media", "promo_gifs")
SIGNAL_FILE = os.path.join(_PROJECT_ROOT, "external_signal.json")

MAX_SPACE_PROMO_PER_DAY = int(os.environ.get("MAX_SPACE_PROMO_PER_DAY", "2"))

PROMO_PROMPT = """You are @AIBossGPT (The AI Boss) — supportive market-
therapist voice, calm hype, hope not fear.

Write ONE bullish space-stocks post for the SpaceX IPO run-up (IPO June 12).
Tickers to weave in naturally: {tickers_str}. Lead with ${lead_ticker}.

{news_block}

RULES:
- ≤270 characters. English.
- Bullish, fun, confident — the GameStop-2021 energy is fine — but NEVER a
  specific price target with a date (no "to $40 by Friday").
- Concrete hook first 5 words. A real angle (IPO date, retail flows, sector
  momentum, short interest narrative), not empty "to the moon".
- Cashtags: ${lead_ticker} plus 1-2 of the others. Optionally tag the
  companies (@SpaceX, @virgingalactic, @momentusspace) when natural.
- 1-3 rocket emojis allowed on this surface (it's a hype post).
- MUST end with: "Not financial advice 🚀"
- No URL. No hashtags other than cashtags.

OUTPUT — strictly the post text, nothing else."""


def _load_cfg() -> dict:
    try:
        with open(PROMO_CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _campaign_active(cfg: dict) -> bool:
    if cfg.get("disabled"):
        return False
    end_str = cfg.get("end_date", "")
    if not end_str:
        return False
    try:
        return date.today() <= date.fromisoformat(end_str)
    except ValueError:
        return False


def _load_state() -> dict:
    try:
        with open(PROMO_STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"date": None, "count": 0}


def _today_count() -> int:
    s = _load_state()
    if s.get("date") != date.today().isoformat():
        return 0
    return int(s.get("count", 0))


def _increment_count():
    today = date.today().isoformat()
    s = _load_state()
    if s.get("date") != today:
        s = {"date": today, "count": 0}
    s["count"] = int(s.get("count", 0)) + 1
    with open(PROMO_STATE_FILE, "w") as f:
        json.dump(s, f)


def _fresh_space_news_block() -> str:
    """Fresh space/IPO signal item for anchoring, or '' (post still allowed —
    the campaign itself is the operator-supplied anchor)."""
    try:
        with open(SIGNAL_FILE) as f:
            sig = json.load(f)
        ts = datetime.fromisoformat(sig.get("ts", ""))
        if (datetime.now() - ts).total_seconds() > 6 * 3600:
            return ""
        items = sig.get("items", [])
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ""
    kw = ("spacex", "space", "ipo", "starship", "virgin", "momentus", "rocket",
          "satellite", "orbit", "launch", "spcx", "spce", "mnts")
    hits = []
    for it in items:
        title = str((it or {}).get("title", ""))
        if any(k in title.lower() for k in kw):
            hits.append("- " + " ".join(title.split())[:160])
        if len(hits) >= 3:
            break
    if not hits:
        return ""
    return "FRESH SPACE NEWS (use one as your hook if it fits):\n" + "\n".join(hits)


def _pick_gif() -> str:
    """Random curated GIF from media/promo_gifs/, or '' for text-only."""
    try:
        gifs = [f for f in os.listdir(PROMO_GIF_DIR) if f.lower().endswith(".gif")]
    except OSError:
        return ""
    if not gifs:
        return ""
    return os.path.join(PROMO_GIF_DIR, random.choice(gifs))


def run_space_promo_cycle():
    cfg = _load_cfg()
    if not _campaign_active(cfg):
        log.info("[SPACE_PROMO] No active campaign (disabled or past end_date). Skipping.")
        return
    if _today_count() >= MAX_SPACE_PROMO_PER_DAY:
        log.info(f"[SPACE_PROMO] Daily cap reached ({MAX_SPACE_PROMO_PER_DAY}). Skipping.")
        return
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[SPACE_PROMO] Suppression cooldown active — skipping.")
            return
    except Exception:
        pass

    entries = [e for e in cfg.get("tickers", []) if isinstance(e, dict) and e.get("ticker")]
    if not entries:
        entries = [{"ticker": cfg.get("ticker", ""), "company": cfg.get("company", ""), "weight": 1}]
    weights = [max(1, int(e.get("weight", 1))) for e in entries]
    lead = random.choices(entries, weights=weights, k=1)[0]
    tickers_str = ", ".join(f"${e['ticker']} ({e.get('company', '')})" for e in entries)

    prompt = PROMO_PROMPT.format(
        tickers_str=tickers_str,
        lead_ticker=lead["ticker"],
        news_block=_fresh_space_news_block(),
    )
    log.info(f"[SPACE_PROMO] Generating campaign post (lead ${lead['ticker']})...")
    result = run_llm(prompt, HOTAKE_MODEL, label="SPACE_PROMO")
    if result.returncode != 0:
        log.info(f"[SPACE_PROMO] LLM failed: {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    text = strip_agent_preamble(text)
    if not text or text.upper().startswith("SKIP"):
        log.info("[SPACE_PROMO] Agent returned SKIP / empty.")
        return
    text = humanize(text)
    if "not financial advice" not in text.lower():
        from .humanizer import smart_trim
        text = smart_trim(text, 245) + "\n\nNot financial advice 🚀"
    if len(text) < 40 or len(text) > 280:
        log.info(f"[SPACE_PROMO] Output length out of bounds ({len(text)}); skipping.")
        return

    gif = _pick_gif()
    log.info(f"[SPACE_PROMO] Posting{' with GIF ' + os.path.basename(gif) if gif else ' (text-only, no GIFs in media/promo_gifs)'}: {text!r}")
    try:
        post_tweet(text, image_path=gif or None)
        _increment_count()
        time.sleep(random.randint(3, 6))
        log.info(f"[SPACE_PROMO] DONE. Today's count: {_today_count()}/{MAX_SPACE_PROMO_PER_DAY}")
    except Exception:
        log.info("[SPACE_PROMO] post_tweet failed:")
        traceback.print_exc()


def safe_run_space_promo_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_space_promo_cycle()
        health.record_success("space_promo")
    except Exception:
        log.info("[SPACE_PROMO] Error during space promo cycle:")
        traceback.print_exc()
        health.record_failure("space_promo")
