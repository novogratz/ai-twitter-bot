"""Retained mentions scan; Reply admission refuses every Debate turn.

The Operator's one-Reply-per-conversation policy applies before generation
and at the write. This module cannot authorize a follow-up.
"""
from collections import Counter
from datetime import timedelta

from ..x import x_urls
from ..core import settings
from ..core.llm_client import Surface
from ..core.logger import log
from . import reply_pipeline
from .reply_generator import ReplyCall


DEBATE_PROMPT = """Current publication policy refuses conversation follow-ups.
Do not draft or continue this conversation. Return exactly SKIP.

Response from @{author}: "{tweet_text}"
"""


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
