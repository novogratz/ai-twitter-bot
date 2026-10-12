"""Frequently collect priority profiles into the shared Reply pool.

Scans accept standalone topic posts throughout the pool's 24-hour window
(operator 2026-10-12). The shared selector decides which earn a Reply.
"""
import random

from ..core.logger import log
from ..core.topic_evidence import MAX_AGE
from ..x.scraper import scrape_profile_tweets
from . import reply_pipeline, reply_source
from .direct_reply import reply_call
from .reply_generator import LanguageRule

# No FR-forced override on this job (pinned in the tests).
JOB = reply_pipeline.Job("mega_watch", "MEGA", reply_call=lambda author: reply_call(author, LanguageRule.PARENT),
                         pause=(8, 14), text_bounds=(10, 270))

# 2026-06-07 PM (operator): static list GONE.

# Scan the top of the bot's earned list (account_curator), with the
# Account's network.pinned_tracked always first.
MEGA_ACCOUNTS: list = []  # intentionally empty — see _watch_pool()


def _watch_pool() -> list:
    from ..account.account_curator import tracked_handles
    return tracked_handles(limit=12)

MAX_REPLIES_PER_CYCLE = 2


def run_mega_watch_cycle():
    """Pick five watched accounts and queue eligible fresh posts for selection."""
    posted = 0

    from ..x.scraper import _profile_visit_allowed
    pool = [h for h in _watch_pool() if _profile_visit_allowed(h)]
    sample = pool[:1] + random.sample(pool[1:], k=min(4, max(0, len(pool) - 1)))
    log.info(f"[MEGA] Polling: {sample}")

    cycle = reply_pipeline.Cycle()
    for username in sample:
        if posted >= MAX_REPLIES_PER_CYCLE or cycle.rate_limited:
            break
        tweets = reply_pipeline.scrape("MEGA", f"@{username}", scrape_profile_tweets, username, max_tweets=4)
        posted += reply_pipeline.run(JOB, _fresh_candidates(username, tweets), cycle,
                                     max_shipped=MAX_REPLIES_PER_CYCLE - posted)

    log.info("[MEGA] Scan completed; eligible posts saved for Reply selection.")


def _fresh_candidates(username: str, tweets: list) -> list:
    declaration = reply_source.Declaration(max_age=MAX_AGE, root_only=True,
                                           author=username, niche=True)
    return reply_source.select(tweets, declaration, f"MEGA/{username}")
