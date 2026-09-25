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
import traceback
from datetime import timedelta

from ..x import x_urls
from ..core.logger import log
from ..x.scraper import scrape_profile_tweets
from . import reply_pipeline
from .direct_reply import is_on_niche, reply_call
from .reply_generator import LanguageRule

# No FR-forced override on this job (pinned in the tests).
JOB = reply_pipeline.Job("mega_watch", "MEGA", reply_call=lambda author: reply_call(author, LanguageRule.PARENT),
                         pause=(8, 14), text_bounds=(10, 270))

# 2026-06-07 PM (operator): static list GONE — the ≤4-min watcher scans the
# TOP of the bot's own earned list (account_curator), pinned with
# TheBTCTherapist + Graphseo. The tightest freshness window gets the
# highest-conviction handles the curator has.
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
    candidates = []
    for t in tweets:
        url = t.get("url")
        if not url:
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if x_urls.is_reply_like_tweet(t, expected_author=username):
            log.info(f"[MEGA] Looks like a thread reply — skipping {url}")
            continue
        # The status ID carries the post time; a URL without one is skipped.
        age = x_urls.age(url)
        if age is None or age > timedelta(minutes=MAX_AGE_MIN):
            continue

        # Niche gate — skip off-topic mega tweets (sama posting about
        # his sandwich shouldn't fire a niche reply).
        if not is_on_niche(text):
            continue
        # Our own Reply in the watched thread (2026-05-16: the bot answered
        # itself under @sama) is refused by Reply admission on its URL handle.
        candidates.append(reply_pipeline.Candidate(url, text, f"MEGA/{username}"))
    return candidates


def safe_run_mega_watch_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_mega_watch_cycle()
        health.record_success("mega_watch")
    except Exception:
        log.info("[MEGA] Error during mega-watch cycle:")
        traceback.print_exc()
        health.record_failure("mega_watch")
