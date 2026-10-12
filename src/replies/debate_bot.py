"""Legacy conversation job, disabled by the current one-Reply-per-post policy.

The module remains wired for compatibility and tests; scheduled discovery uses
standalone posts and the shared Reply pool. The Reply pipeline and write guards
reject conversation turns even if this function is invoked directly.
"""
from collections import Counter
from datetime import timedelta

from ..x import x_urls
from ..core import settings
from ..core.llm_client import Surface
from ..core.logger import log
from . import reply_pipeline
from .reply_generator import ReplyCall


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


def reply_call() -> ReplyCall:
    # dossier=False: whether the author's dossier joins it is the Operator's call.
    return ReplyCall(DEBATE_PROMPT, Surface.REPLY_ON_AI_CLI, "DEBATE", dossier=False, text_limit=500)


JOB = reply_pipeline.Job("debate", "DEBATE", reply_call=lambda _author: reply_call(), debate_turn=True,
                         pause=(3, 3))


def _debates_enabled() -> bool:
    """Read at call time (side-effect-env rule)."""
    return settings.get("ENABLE_DEBATES")


def run_debate_cycle():
    if not _debates_enabled():
        log.info("[DEBATE] Disabled (ENABLE_DEBATES=0). Skipping.")
        return

    max_per_cycle = settings.get("DEBATE_MAX_PER_CYCLE")
    max_age_hours = settings.get("DEBATE_MAX_AGE_HOURS")

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
