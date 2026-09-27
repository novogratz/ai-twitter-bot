"""Mega-account fast watcher — top-5-reply window on the biggest accounts.

Why: early_bird scans ~125 accounts every 5-7 min. Statistically, a
fresh tweet from sama / OpenAI / Anthropic / elonmusk lands in
early_bird's net 1 cycle later (5-7 min). That's TOO LATE — top-5
replies on those accounts get filled in <2 min when the tweet drops.

This bot polls the TOP 10 mega accounts every 90 sec specifically to
catch the FIRST 60-second window. When a fresh tweet (< 4 min old) is
detected, fires an immediate FR reply via the same prompt path as
early_bird.

Cap: MAX_REPLIES_PER_CYCLE, to avoid burst-following the same account
when it tweets a thread. Reply admission judges each post before generation.
"""
import random
from datetime import timedelta

from ..core.logger import log
from ..x.scraper import scrape_profile_tweets
from . import reply_pipeline, reply_source
from .direct_reply import reply_call
from .reply_generator import LanguageRule

# No FR-forced override on this job (pinned in the tests).
JOB = reply_pipeline.Job("mega_watch", "MEGA", reply_call=lambda author: reply_call(author, LanguageRule.PARENT),
                         pause=(8, 14), text_bounds=(10, 270))

# 2026-06-07 PM (operator): static list GONE.

# The ≤4-min watcher scans the TOP of the bot's own earned list
# (account_curator), with the Account's network.pinned_tracked always first.
# The tightest freshness window gets the highest-conviction handles the
# curator has.
MEGA_ACCOUNTS: list = []  # intentionally empty — see _watch_pool()


def _watch_pool() -> list:
    from ..account.account_curator import tracked_handles
    return tracked_handles(limit=12)

MAX_AGE_MIN = 4
MAX_REPLIES_PER_CYCLE = 2


def run_mega_watch_cycle():
    """Pick 5 mega accounts at random, reply to any fresh tweet."""
    posted = 0

    pool = _watch_pool()
    sample = random.sample(pool, k=min(5, len(pool)))
    log.info(f"[MEGA] Polling: {sample}")

    cycle = reply_pipeline.Cycle()
    for username in sample:
        if posted >= MAX_REPLIES_PER_CYCLE or cycle.rate_limited:
            break
        tweets = reply_pipeline.scrape("MEGA", f"@{username}", scrape_profile_tweets, username, max_tweets=4)
        posted += reply_pipeline.run(JOB, _fresh_candidates(username, tweets), cycle,
                                     max_shipped=MAX_REPLIES_PER_CYCLE - posted)

    log.info(f"[MEGA] Cycle done: {posted} replies posted.")


def _fresh_candidates(username: str, tweets: list) -> list:
    # Niche gate: sama posting about his sandwich shouldn't fire a niche
    # reply. Our own Reply in the watched thread (2026-05-16: the bot
    # answered itself under @sama) is refused by Reply admission on its URL
    # handle.
    declaration = reply_source.Declaration(max_age=timedelta(minutes=MAX_AGE_MIN),
                                           root_only=True, author=username, niche=True)
    return reply_source.select(tweets, declaration, f"MEGA/{username}")
