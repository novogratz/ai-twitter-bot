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
import time
import traceback
from datetime import timedelta

from .x import x_urls
from .core.logger import log
from .x.twitter_client import scrape_profile_tweets, reply_to_tweet
from .reply_admission import judge_parent
from .direct_reply import _LLM_RATE_LIMITED, _generate_single_reply, _is_on_niche
from .reply_language import looks_french
from .core.engagement_log import log_reply
from .core.humanizer import humanize
from .core.state_errors import StateUnreadable

# Posts this job is done with until restart: definitive Reply admission
# refusals, posts the model declined, posts answered.
_skipped: set = set()

# 2026-06-07 PM (operator): static list GONE — the ≤4-min watcher scans the
# TOP of the bot's own earned list (account_curator), pinned with
# TheBTCTherapist + Graphseo. The tightest freshness window gets the
# highest-conviction handles the curator has.
MEGA_ACCOUNTS: list = []  # intentionally empty — see _watch_pool()


def _watch_pool() -> list:
    from .account_curator import tracked_handles
    return tracked_handles(limit=12)

MAX_AGE_MIN = 4
MAX_REPLIES_PER_CYCLE = 2


def run_mega_watch_cycle():
    """Pick 5 mega accounts at random, reply to any fresh tweet."""
    posted = 0

    pool = _watch_pool()
    sample = random.sample(pool, k=min(5, len(pool)))
    log.info(f"[MEGA] Polling: {sample}")

    for username in sample:
        if posted >= MAX_REPLIES_PER_CYCLE:
            break
        try:
            tweets = scrape_profile_tweets(username, max_tweets=4)
        except Exception:
            log.info(f"[MEGA] Scrape failed for @{username}:")
            traceback.print_exc()
            continue

        for t in tweets or []:
            if posted >= MAX_REPLIES_PER_CYCLE:
                break
            url = t.get("url")
            if not url or url in _skipped:
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
            if not _is_on_niche(text):
                continue

            # Our own Reply in the watched thread (2026-05-16: the bot answered
            # itself under @sama) is refused here by its URL handle.
            verdict = judge_parent(url)
            if not verdict:
                if verdict.refusal.definitive:
                    _skipped.add(url)
                continue

            # Source tagging happens in log_reply later.
            reply_text = _generate_single_reply(
                author=verdict.author,
                tweet_text=text,
                lang="fr" if looks_french(text) else "en",
            )
            if reply_text is _LLM_RATE_LIMITED:
                log.info("[MEGA] LLM budget reached; stopping this cycle before posting attempts.")
                return
            if reply_text is None:
                continue  # failed call: replayable next cycle
            if not reply_text:
                _skipped.add(url)  # the model declined
                continue
            reply_text = humanize(reply_text)
            if len(reply_text) < 10 or len(reply_text) > 270:
                continue

            # ⛔ NO premark — the reply_to_tweet chokepoint marks the store
            # itself pre-post and refuses anything already in it (premark =
            # 100% silent self-skip, 2026-06-07 post-mortem).
            try:
                if not reply_to_tweet(url, reply_text):
                    continue  # chokepoint skip — nothing posted, no phantom log
                _skipped.add(url)
                try:
                    log_reply(url, reply_text, action_type="reply", source=f"MEGA/{username}")
                except Exception:
                    pass
                posted += 1
                log.info(f"[MEGA] Posted top-5 reply to @{username}: {reply_text[:120]!r}")
                time.sleep(random.randint(8, 14))
            except StateUnreadable:
                raise
            except Exception:
                log.info(f"[MEGA] Reply to {url} failed:")
                traceback.print_exc()

    log.info(f"[MEGA] Cycle done: {posted} replies posted.")


def safe_run_mega_watch_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from .core import health
    try:
        run_mega_watch_cycle()
        health.record_success("mega_watch")
    except Exception:
        log.info("[MEGA] Error during mega-watch cycle:")
        traceback.print_exc()
        health.record_failure("mega_watch")
