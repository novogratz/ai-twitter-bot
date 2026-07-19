"""Self-quote recycler — she QRTs herself with the follow-up angle.

Operator 2026-07-19 (pending idea since 2026-06-07 round 3, "quote-
yourself"): ~24h after one of our posts wins, quote-tweet it OURSELVES
with the update/second-take angle ("update on this…", "24 hours later and
this aged well/badly…"). A second life for proven content, a very human
move, and the QRT surfaces the original to everyone who missed it.

Max 1/day, evening window (the analyzer's measured best hours), winners
only (>= SELF_QUOTE_MIN_LIKES, 20-48h old — inside the hard 48h repost
rule by construction). Ships through the quote_tweet chokepoint (dedup,
caps, spacing, content guard) — a URL is marked consumed only after a
confirmed ship.
"""
import json
import os
import re
import traceback
from datetime import date, datetime, timezone

from .config import _PROJECT_ROOT, BOT_HANDLE, QUOTE_MODEL, PROFILE_LLM_PROVIDER
from .logger import log
from .llm_client import run_llm, unwrap_text
from .humanizer import humanize

STATE_FILE = os.path.join(_PROJECT_ROOT, "self_quote_state.json")

_TWITTER_EPOCH = 1288834974657


def _age_hours(url: str) -> float:
    m = re.search(r"/status/(\d+)", url or "")
    if not m:
        return -1.0
    ts_ms = (int(m.group(1)) >> 22) + _TWITTER_EPOCH
    t = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - t).total_seconds() / 3600


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        if isinstance(st, dict):
            return st
    except (OSError, json.JSONDecodeError):
        pass
    return {"date": "", "quoted": []}


def _save_state(st: dict) -> None:
    st["quoted"] = st.get("quoted", [])[-200:]
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=1)


SELF_QUOTE_PROMPT = """You are @TheAIShrink — THE AI THERAPIST. A woman, 35-40, practicing
therapist and mom, the sharpest AI mind on the timeline (warm, wry, zero bro-speak).

~24 hours ago YOU posted this, and it performed well:

"{post_text}"

You are now QUOTE-TWEETING YOUR OWN POST with the follow-up. The human move, not a rerun:
- The UPDATE: what happened since, the number that moved, the reaction it got.
- Or the SECOND TAKE: the angle you didn't have room for yesterday.
- Or the AGED CHECK: "24 hours later and this aged…" (well/badly — honest either way).

RULES:
- ENGLISH. ONE short line, max 180 chars. Casual, her voice.
- Must ADD something — never restate the original (it renders right below yours).
- No hashtags, no links, no em dashes. 0-1 emoji.
- If you genuinely have no fresh angle → output SKIP (a hollow self-quote reads desperate).

Output ONLY the quote text, or exactly SKIP."""


def run_self_quote_cycle():
    if os.environ.get("ENABLE_SELF_QUOTE", "1") != "1":
        log.info("[SELF-QUOTE] Disabled. Skipping.")
        return
    min_likes = int(os.environ.get("SELF_QUOTE_MIN_LIKES", "3"))

    st = _load_state()
    today = date.today().isoformat()
    if st.get("date") == today:
        log.info("[SELF-QUOTE] Already ran today. Skipping.")
        return

    from .twitter_client import scrape_profile_tweets, is_own_post, quote_tweet
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=20)
    except Exception:
        log.info("[SELF-QUOTE] Scrape failed:")
        traceback.print_exc()
        return
    quoted = set(st.get("quoted", []))
    candidates = []
    for t in tweets or []:
        url = t.get("url") or ""
        if not url or not is_own_post(t) or url in quoted:
            continue
        age = _age_hours(url)
        if not (20 <= age <= 48):
            continue
        likes = int(t.get("likes") or 0)
        if likes < min_likes:
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        candidates.append({"url": url, "likes": likes, "text": text})

    if not candidates:
        log.info(f"[SELF-QUOTE] No 20-48h own post with >= {min_likes} likes. Skipping (slot preserved).")
        return

    best = max(candidates, key=lambda c: c["likes"])
    result = run_llm(SELF_QUOTE_PROMPT.format(post_text=best["text"][:400]),
                     QUOTE_MODEL, label="SELF_QUOTE",
                     force_provider=PROFILE_LLM_PROVIDER)
    if result.returncode != 0:
        return
    comment = unwrap_text(result.stdout).strip()
    if not comment or comment.upper().startswith("SKIP"):
        log.info("[SELF-QUOTE] Model skipped (no fresh angle). Slot preserved.")
        return
    comment = humanize(comment)

    # Ship-gated bookkeeping: mark consumed + daily-done only on a
    # confirmed ship (the hot_quote slot-burn lesson).
    if quote_tweet(best["url"], comment):
        st["date"] = today
        st.setdefault("quoted", []).append(best["url"])
        _save_state(st)
        log.info(f"[SELF-QUOTE] Quoted own winner ({best['likes']} likes): {best['url']}")
    else:
        log.info("[SELF-QUOTE] Chokepoint refused — candidate + slot preserved for next cycle.")


def safe_run_self_quote_cycle():
    from . import health
    try:
        run_self_quote_cycle()
        health.record_success("self_quote")
    except Exception:
        log.info("[SELF-QUOTE] Error during cycle:")
        traceback.print_exc()
        health.record_failure("self_quote")
