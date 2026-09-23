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

Contracts honored: Reply admission judges each mention, Debate turn cap
included, before the model call; the reply_to_tweet chokepoint judges it
again with the text — NO caller-side premark; log only on a confirmed
ship; Safari work only inside the client primitives.
"""
import os
import time
import traceback
from collections import Counter
from datetime import timedelta

from . import x_urls
from .config import REPLY_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text
from .humanizer import humanize
from .reply_admission import judge_parent

# Mentions this job drops until restart: definitive Reply admission
# refusals and mentions the model declined.
_skipped: set = set()


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

    from .twitter_client import scrape_mentions, reply_to_tweet
    mentions = scrape_mentions(max_tweets=20)
    if not mentions:
        log.info("[DEBATE] No mentions scraped this cycle.")
        return

    posted = 0
    skips = Counter()

    # Freshest first — a debate is won in the first minutes.
    mentions.sort(key=lambda t: x_urls.age(t.get("url") or "") or timedelta.max)

    for t in mentions:
        if posted >= max_per_cycle:
            break
        url = t.get("url") or ""
        if not url or url in _skipped:
            continue
        age = x_urls.age(url)
        if age is None or age > timedelta(hours=max_age_hours):
            skips["old"] += 1
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        verdict = judge_parent(url, debate_turn=True)
        if not verdict:
            skips[verdict.refusal.name.lower()] += 1
            if verdict.refusal.definitive:
                _skipped.add(url)
            continue
        author = verdict.author

        prompt = DEBATE_PROMPT.format(author=author, tweet_text=text[:500])
        result = run_llm(prompt, REPLY_MODEL, label="DEBATE")
        if result.returncode != 0:
            continue  # a failed call is retried next cycle
        reply = unwrap_text(result.stdout).strip()
        if not reply or reply.upper().startswith("SKIP"):
            _skipped.add(url)
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
             f"(skips: {', '.join(f'{k}={v}' for k, v in skips.items())}).")


def safe_run_debate_cycle():
    from . import health
    try:
        run_debate_cycle()
        health.record_success("debate")
    except Exception:
        log.info("[DEBATE] Error during debate cycle:")
        traceback.print_exc()
        health.record_failure("debate")
