"""Engagement-velocity reply targeting — the growth engine (2026-06-02).

Replies are the primary growth lever, so spend them where they'll be seen.
Each run:
  1. Pull recent posts from the tier1 + tier2 whitelist accounts.
  2. Rank by VELOCITY = (likes + reposts) / hours_since_post — a post going off
     RIGHT NOW, weighted by a learned per-author multiplier.
  3. Reply to the top few with a language-matched, SUBSTANTIVE take (the
     content/substance gate rejects "great post"), through the rate-limited
     reply chokepoint (so the 30/day cap + spacing + validators all apply).
  4. Log every target + bump the author's reply tally so the ranking has a
     home to learn from (conversion attribution can refine the weight later).

Quality over volume: a handful of sharp replies on high-velocity whitelist
posts beats spraying low-signal threads.
"""
import json
import os
import random
import time
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT, BLOCKLIST, BOT_HANDLE
from .logger import log

_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_targets_log.json")
_OWN = BOT_HANDLE.lower()

# Tunables (config, not hardcoded logic).
HANDLES_PER_CYCLE = int(os.environ.get("ET_HANDLES_PER_CYCLE", "8"))
TWEETS_PER_HANDLE = int(os.environ.get("ET_TWEETS_PER_HANDLE", "10"))
TARGETS_PER_CYCLE = int(os.environ.get("ET_TARGETS_PER_CYCLE", "3"))
MAX_AGE_MINUTES = int(os.environ.get("ET_MAX_AGE_MINUTES", str(6 * 60)))
MIN_LIKES = int(os.environ.get("ET_MIN_LIKES", "5"))


def _load_log() -> dict:
    try:
        with open(_LOG_FILE) as f:
            d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("authors", {})
                d.setdefault("targets", [])
                return d
    except (OSError, json.JSONDecodeError):
        pass
    return {"authors": {}, "targets": []}


def _save_log(d: dict) -> None:
    d["targets"] = d.get("targets", [])[-500:]
    try:
        with open(_LOG_FILE, "w") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError:
        pass


def _author_weight(d: dict, handle: str) -> float:
    rec = d.get("authors", {}).get(handle.lower())
    if isinstance(rec, dict):
        try:
            return float(rec.get("weight", 1.0))
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def _velocity(t: dict, age_min: float) -> float:
    likes = int(t.get("likes") or 0)
    reposts = int(t.get("reposts") or t.get("retweets") or 0)
    hours = max(age_min / 60.0, 0.25)  # floor so a 5-min-old banger isn't ∞
    return (likes + reposts) / hours


def run_engagement_targeting_cycle():
    """Rank whitelist posts by velocity and reply to the hottest few."""
    from . import action_guard
    from .replied_store import load_replied, save_replied
    from .reply_bot import _tweet_age_minutes, _handle_from_url
    from .x_urls import is_reply_like_tweet
    from .direct_reply import _generate_single_reply, _is_on_niche, _is_fr_or_en
    from .reply_language import looks_english
    from .twitter_client import scrape_profile_tweets, reply_to_tweet

    # If the daily reply cap is already spent, don't even scrape.
    ok, why = action_guard.can_post(action_guard.REPLY)
    if not ok and "cap reached" in why:
        log.info(f"[ET] Reply budget exhausted ({why}) — skipping cycle.")
        return

    wl = action_guard.load_whitelist()
    handles = list(wl["tier1"] | wl["tier2"])
    if not handles:
        log.info("[ET] Whitelist empty — nothing to target.")
        return
    random.shuffle(handles)
    handles = handles[:HANDLES_PER_CYCLE]

    replied = load_replied()
    state = _load_log()
    candidates = []
    for handle in handles:
        try:
            tweets = scrape_profile_tweets(handle, max_tweets=TWEETS_PER_HANDLE)
        except Exception:
            log.info(f"[ET] scrape failed for @{handle}")
            continue
        for t in tweets or []:
            url = t.get("url")
            if not url or url in replied:
                continue
            author = (_handle_from_url(url) or t.get("author") or handle or "").lower()
            if author in BLOCKLIST or author == _OWN:
                continue
            text = (t.get("text") or "").strip()
            if not text or not _is_on_niche(text) or not _is_fr_or_en(text):
                continue
            if is_reply_like_tweet(t):
                continue
            if int(t.get("likes") or 0) < MIN_LIKES:
                continue
            age_min = _tweet_age_minutes(url)  # expects the URL string, not the dict
            if age_min > MAX_AGE_MINUTES:       # 9999 when unparseable → skipped (stale)
                continue
            score = _velocity(t, age_min) * _author_weight(state, author)
            candidates.append({"url": url, "author": author, "text": text,
                               "score": score, "age_min": age_min})

    if not candidates:
        log.info("[ET] No fresh high-velocity whitelist targets this cycle.")
        return

    candidates.sort(key=lambda c: c["score"], reverse=True)
    posted = 0
    for c in candidates:
        if posted >= TARGETS_PER_CYCLE:
            break
        ok, why = action_guard.can_post(action_guard.REPLY)
        if not ok:
            log.info(f"[ET] Reply policy stop ({why}).")
            break
        lang = "en" if looks_english(c["text"]) else "fr"
        log.info(f"[ET] Target @{c['author']} velocity={c['score']:.1f} "
                 f"age={c['age_min']:.0f}m lang={lang}")
        reply = _generate_single_reply(c["author"], c["text"], lang=lang)
        if not reply or not isinstance(reply, str):
            continue
        try:
            if not reply_to_tweet(c["url"], reply):
                replied.add(c["url"])  # in-memory only — no phantom learn/log
                continue
        except Exception:
            log.info(f"[ET] reply_to_tweet failed for {c['url']}")
            traceback.print_exc()
            continue
        replied.add(c["url"])
        # Learn: bump this author's reply tally (conversion attribution can
        # later adjust weight up/down based on like/reply/follow-back).
        rec = state["authors"].setdefault(c["author"], {"replies": 0, "weight": 1.0})
        rec["replies"] = int(rec.get("replies", 0)) + 1
        rec["last_ts"] = datetime.now().isoformat()
        state["targets"].append({"author": c["author"], "url": c["url"],
                                 "velocity": round(c["score"], 1),
                                 "ts": datetime.now().isoformat()})
        posted += 1

    save_replied(replied)
    _save_log(state)
    log.info(f"[ET] Replied to {posted} high-velocity whitelist target(s).")


def safe_run_engagement_targeting_cycle():
    from . import health
    try:
        run_engagement_targeting_cycle()
        health.record_success("engagement_targeting")
    except Exception:
        log.info("[ET] Error during engagement-targeting cycle:")
        traceback.print_exc()
        health.record_failure("engagement_targeting")
