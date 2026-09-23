"""Debate bot — she argues back, warmly, and keeps the rally going.

Operator 2026-07-19: "make her do more debates with people and reply to
other people replies and get her on a roll. She is the sharpest AI
therapist that has the highest knowledge in AI of the world."

Mechanic: scrape the mentions tab (people replying to our replies/posts
anywhere on X — the one surface the replyback bot's own-latest-tweet scan
never sees), and answer the fresh ones with a sharp, warm comeback that
lands one number/mechanism and invites the next round. Each further
response from them is a new mention, so the rally continues naturally —
bounded by the per-author daily Debate turn cap, counted at the reply
chokepoint and shared with replyback, so no thread spirals.

Contracts honored: reply_to_tweet chokepoint (one-reply-per-tweet dedup,
caps, spacing, language) — NO caller-side premark; log only on a confirmed
ship; Safari work only inside the client primitives.
"""
import os
import re
import time
import traceback
from datetime import datetime, timezone

from .config import BLOCKLIST, BOT_HANDLE, REPLY_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text
from .humanizer import humanize

_TWITTER_EPOCH = 1288834974657


def _tweet_age_hours(url: str) -> float:
    m = re.search(r"/status/(\d+)", url or "")
    if not m:
        return 9999.0
    ts_ms = (int(m.group(1)) >> 22) + _TWITTER_EPOCH
    tweet_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - tweet_time).total_seconds() / 3600


def _handle_from_url(url: str) -> str:
    m = re.search(r"x\.com/([^/]+)/status/", url or "")
    return m.group(1).lower() if m else ""


DEBATE_PROMPT = """You are @TheAIShrink — THE AI THERAPIST. A woman, 45, a practicing
therapist and a mom, and THE sharpest AI mind on the timeline: you know every model, every
release, every benchmark, every filing — better than anyone in this thread.

Someone just responded to something you said. This is a DEBATE — your favorite sport. You are
on a roll, and your job is to keep the rally going:

THEIR MESSAGE (from @{author}):
"{tweet_text}"

HOW SHE DEBATES (all four, every time):
1. STAY WARM. You're a therapist — you never get rattled, never hostile, never condescending.
   Unshockable, amused, generous. The reader should think "she's enjoying this."
2. LAND ONE FACT. One exact number, named mechanism, or specific release that settles or
   advances the point. That's your moat: you actually know this stuff cold.
3. CONCEDE WITH CHARM when they're right ("fair, that part's true — but here's the piece
   that changes it"). Being persuadable makes the win land harder when you hold your ground.
4. KEEP THE RALLY GOING. End on a short pointed question or a claim they'll want to answer.
   A debate that dies in one exchange is a missed audience.

RULES:
- MATCH THEIR LANGUAGE (EN reply to EN, FR to FR). Default EN if unsure.
- 80-220 chars. Casual, human, her voice — zero bro-speak, no em dashes, no hashtags,
  no emojis needed.
- Never insult them, their intelligence, or their work. Debate the CLAIM.
- If their message is pure abuse, spam, a bot, or has nothing to engage with → output SKIP.
- If it's simple praise/agreement with no debatable content → a warm one-line thank-you
  with a small bonus insight is fine (that converts followers too).

Output ONLY the reply text, or exactly SKIP."""


def _debates_enabled() -> bool:
    """Read at call time (side-effect-env rule)."""
    return os.environ.get("ENABLE_DEBATES", "1") == "1"


def run_debate_cycle():
    if not _debates_enabled():
        log.info("[DEBATE] Disabled (ENABLE_DEBATES=0). Skipping.")
        return

    max_per_cycle = int(os.environ.get("DEBATE_MAX_PER_CYCLE", "3"))
    max_age_hours = float(os.environ.get("DEBATE_MAX_AGE_HOURS", "24"))

    from . import action_guard
    from .twitter_client import scrape_mentions, reply_to_tweet
    from .reply_bot import load_replied
    mentions = scrape_mentions(max_tweets=20)
    if not mentions:
        log.info("[DEBATE] No mentions scraped this cycle.")
        return

    replied = load_replied()
    own = BOT_HANDLE.lower()
    posted = 0
    skipped = {"own": 0, "old": 0, "replied": 0, "blocklist": 0, "turncap": 0}

    # Freshest first — a debate is won in the first minutes.
    mentions.sort(key=lambda t: _tweet_age_hours(t.get("url") or ""))

    for t in mentions:
        if posted >= max_per_cycle:
            break
        url = t.get("url") or ""
        author = _handle_from_url(url)
        if not url or not author:
            continue
        if author == own:
            skipped["own"] += 1
            continue
        if author in BLOCKLIST:
            skipped["blocklist"] += 1
            continue
        if _tweet_age_hours(url) > max_age_hours:
            skipped["old"] += 1
            continue
        if url in replied:
            skipped["replied"] += 1
            continue
        # Early skip saves the model call; the chokepoint enforces the cap.
        if not action_guard.can_debate_turn(author)[0]:
            skipped["turncap"] += 1
            continue

        text = (t.get("text") or "").strip()
        if not text:
            continue

        prompt = DEBATE_PROMPT.format(author=author, tweet_text=text[:500])
        result = run_llm(prompt, REPLY_MODEL, label="DEBATE")
        if result.returncode != 0:
            continue
        reply = unwrap_text(result.stdout).strip()
        if not reply or reply.upper().startswith("SKIP"):
            continue
        reply = humanize(reply)

        # No premark — the chokepoint owns the replied store. Ship-gated
        # bookkeeping only (phantom-log family).
        if reply_to_tweet(url, reply, debate_turn=True):
            posted += 1
            from .engagement_log import log_reply
            log_reply(url, reply, "reply", source=f"DEBATE/{author}")
            time.sleep(3)

    log.info(f"[DEBATE] Cycle done: {posted} debate replies posted "
             f"(skips: {', '.join(f'{k}={v}' for k, v in skipped.items() if v)}).")


def safe_run_debate_cycle():
    from . import health
    try:
        run_debate_cycle()
        health.record_success("debate")
    except Exception:
        log.info("[DEBATE] Error during debate cycle:")
        traceback.print_exc()
        health.record_failure("debate")
