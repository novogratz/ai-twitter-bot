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

Contracts honored in the Reply pipeline: Reply admission judges each
mention, Debate turn cap included, before the model call; the
reply_to_tweet chokepoint judges it again with the text — NO caller-side
premark; log only on a confirmed ship; Safari work only inside the client
primitives.
"""
import os
import traceback
from collections import Counter
from datetime import timedelta

from ..x import x_urls
from ..core.config import REPLY_MODEL
from ..core.logger import log
from . import reply_pipeline
from .reply_generator import Voice


DEBATE_PROMPT = """Someone just responded to something you said. This is a DEBATE — your favorite sport. You are
on a roll, and your job is to keep the rally going:

THEIR MESSAGE (from @{author}):
"{tweet_text}"

HOW TO DEBATE (all four, every time):
1. STAY WARM. Never rattled, never hostile, never condescending.
   Unshockable, amused, generous. The reader should see you enjoying this.
2. LAND ONE FACT. One exact number, named mechanism, or specific release that settles or
   advances the point.
3. CONCEDE WITH CHARM when they're right ("fair, that part's true — but here's the piece
   that changes it"). Being persuadable makes the win land harder when you hold your ground.
4. KEEP THE RALLY GOING. End on a short pointed question or a claim they'll want to answer.
   A debate that dies in one exchange is a missed audience.

RULES:
- MATCH THEIR LANGUAGE (EN reply to EN, FR to FR). Default EN if unsure.
- 80-220 chars. No em dashes, no hashtags, no emojis needed.
- Never insult them, their intelligence, or their work. Debate the CLAIM.
- If their message is pure abuse, spam, a bot, or has nothing to engage with → output SKIP.
- If it's simple praise/agreement with no debatable content → a warm one-line thank-you
  with a small bonus insight is fine (that converts followers too).

Output ONLY the reply text, or exactly SKIP."""

# dossier=False: whether the author's dossier joins it is the Operator's call.
VOICE = Voice(DEBATE_PROMPT, REPLY_MODEL, "DEBATE", dossier=False, text_limit=500)
JOB = reply_pipeline.Job("debate", "DEBATE", voice=lambda _author: VOICE, debate_turn=True, pause=(3, 3))


def _debates_enabled() -> bool:
    """Read at call time (side-effect-env rule)."""
    return os.environ.get("ENABLE_DEBATES", "1") == "1"


def run_debate_cycle():
    if not _debates_enabled():
        log.info("[DEBATE] Disabled (ENABLE_DEBATES=0). Skipping.")
        return

    max_per_cycle = int(os.environ.get("DEBATE_MAX_PER_CYCLE", "3"))
    max_age_hours = float(os.environ.get("DEBATE_MAX_AGE_HOURS", "24"))

    from ..x.scraper import scrape_mentions
    mentions = scrape_mentions(max_tweets=20)
    if not mentions:
        log.info("[DEBATE] No mentions scraped this cycle.")
        return

    skips = Counter()

    # Freshest first — a debate is won in the first minutes.
    mentions.sort(key=lambda t: x_urls.age(t.get("url") or "") or timedelta.max)

    candidates = []
    for t in mentions:
        url = t.get("url") or ""
        if not url:
            continue
        age = x_urls.age(url)
        if age is None or age > timedelta(hours=max_age_hours):
            skips["old"] += 1
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        candidates.append(reply_pipeline.Candidate(url, text, f"DEBATE/{x_urls.author(url)}"))

    cycle = reply_pipeline.Cycle()
    posted = reply_pipeline.run(JOB, candidates, cycle, max_shipped=max_per_cycle)
    skips.update(cycle.refusals)
    log.info(f"[DEBATE] Cycle done: {posted} debate replies posted "
             f"(skips: {', '.join(f'{k}={v}' for k, v in skips.items())}).")


def safe_run_debate_cycle():
    from ..core import health
    try:
        run_debate_cycle()
        health.record_success("debate")
    except Exception:
        log.info("[DEBATE] Error during debate cycle:")
        traceback.print_exc()
        health.record_failure("debate")
