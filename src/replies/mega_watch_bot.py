"""Bounded Latest searches for very recent posts by tracked authors.

The four-minute horizon and cycle budget remain. Author URLs, niche relevance
and shared Reply admission decide eligibility; the Voice decides the language."""
import random
from datetime import timedelta

from ..x import x_urls
from ..core.logger import log
from ..x.scraper import scrape_x_search
from . import reply_pipeline
from .direct_reply import is_on_niche, reply_call
from .reply_source import author_search_query, source_text, observed_likes
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
        tweets = reply_pipeline.scrape("MEGA", f"@{username}", scrape_x_search,
                                       author_search_query(username), tab="latest", max_tweets=4, text_limit=1200)
        posted += reply_pipeline.run(JOB, _fresh_candidates(username, tweets), cycle,
                                     max_shipped=MAX_REPLIES_PER_CYCLE - posted)

    log.info(f"[MEGA] Cycle done: {posted} replies posted.")


def _fresh_candidates(username: str, tweets: list) -> list:
    candidates = []
    for t in tweets:
        url = t.get("url")
        if (not x_urls.canonical_status_url(url)
                or x_urls.author(url) != username.lower().lstrip("@")):
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if x_urls.is_reply_like_tweet(t, expected_author=username):
            log.info(f"[MEGA] Looks like a thread reply — skipping {url}")
            continue
        # The status ID carries the post time; a URL without one is skipped.
        age = x_urls.age(url)
        if age is None or age < timedelta(0) or age > timedelta(minutes=MAX_AGE_MIN):
            continue

        # Niche gate — skip off-topic mega tweets (sama posting about
        # his sandwich shouldn't fire a niche reply).
        if not is_on_niche(text):
            continue
        # Our own Reply in the watched thread (2026-05-16: the bot answered
        # itself under @sama) is refused by Reply admission on its URL handle.
        candidates.append(reply_pipeline.Candidate(url, source_text(t).strip(), f"MEGA/{username}",
                                                   likes=observed_likes(t)))
    return candidates
