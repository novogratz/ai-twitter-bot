"""Mega-account fast watcher — top-5-reply window on the biggest accounts.

Why: early_bird scans ~125 accounts every 5-7 min. Statistically, a
fresh tweet from sama / OpenAI / Anthropic / elonmusk lands in
early_bird's net 1 cycle later (5-7 min). That's TOO LATE — top-5
replies on those accounts get filled in <2 min when the tweet drops.

This bot polls the TOP 10 mega accounts every 90 sec specifically to
catch the FIRST 60-second window. When a fresh tweet (< 4 min old) is
detected, fires an immediate FR reply via the same prompt path as
early_bird.

Cap: 6 replies/cycle to avoid burst-following the same account when
it tweets a thread. Persisted dedup via the shared replied.json store.
"""
import os
import random
import time
import traceback
import urllib.parse
import webbrowser

from .config import _PROJECT_ROOT, BOT_HANDLE, BLOCKLIST
from .logger import log
from .twitter_client import scrape_profile_tweets, reply_to_tweet
from .replied_store import load_replied
from .reply_bot import _tweet_age_minutes, _handle_from_url, _is_reply_like_tweet
from .direct_reply import _LLM_RATE_LIMITED, _generate_single_reply, _is_on_niche
from .reply_language import looks_french
from .engagement_log import log_reply
from .humanizer import humanize

_OWN_HANDLE = BOT_HANDLE.lower()

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
    replied = load_replied()
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
            if not url or url in replied:
                continue
            url_handle = (_handle_from_url(url) or "").lower().lstrip("@")
            author = (t.get("author") or url_handle or "").lower().lstrip("@")
            if author in {b.lower() for b in BLOCKLIST}:
                continue
            # Self-reply guard — check BOTH author AND the URL handle.
            # Bug 2026-05-16: scraper sometimes labels the tweet's author
            # as the mega account being watched while the URL points to
            # OUR status (because we replied to that mega tweet). Without
            # checking url_handle, the bot was replying to its own past
            # replies in the @sama thread. Confirmed in engagement_log:
            # MEGA/sama source replying to x.com/TheAIShrink/status/...
            if author == _OWN_HANDLE or url_handle == _OWN_HANDLE:
                continue
            text = (t.get("text") or "").strip()
            if not text:
                continue
            if _is_reply_like_tweet(t, expected_author=username):
                log.info(f"[MEGA] Looks like a thread reply — skipping {url}")
                continue
            # The status ID carries the post time; an unparseable URL reads
            # as 9999 minutes and is skipped.
            if _tweet_age_minutes(url) > MAX_AGE_MIN:
                continue

            # Niche gate — skip off-topic mega tweets (sama posting about
            # his sandwich shouldn't fire a niche reply).
            if not _is_on_niche(text):
                continue

            # Generate FR reply via the shared single-reply pipeline.
            # _generate_single_reply only takes (author, tweet_text);
            # source tagging happens in log_reply later.
            reply_text = _generate_single_reply(
                author=author,
                tweet_text=text,
                lang="fr" if looks_french(text) else "en",
            )
            if reply_text is _LLM_RATE_LIMITED:
                log.info("[MEGA] LLM budget reached; stopping this cycle before posting attempts.")
                return
            if not reply_text:
                continue
            reply_text = humanize(reply_text)
            if len(reply_text) < 10 or len(reply_text) > 270:
                continue

            # ⛔ NO premark — the reply_to_tweet chokepoint marks the store
            # itself pre-post and refuses anything already in it (premark =
            # 100% silent self-skip, 2026-06-07 post-mortem).
            replied.add(url)  # in-memory only: no same-cycle retry

            try:
                if not reply_to_tweet(url, reply_text):
                    continue  # chokepoint skip — nothing posted, no phantom log
                try:
                    log_reply(url, reply_text, action_type="reply", source=f"MEGA/{username}")
                except Exception:
                    pass
                posted += 1
                log.info(f"[MEGA] Posted top-5 reply to @{username}: {reply_text[:120]!r}")
                time.sleep(random.randint(8, 14))
            except Exception:
                log.info(f"[MEGA] Reply to {url} failed:")
                traceback.print_exc()

    log.info(f"[MEGA] Cycle done: {posted} replies posted.")


def safe_run_mega_watch_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_mega_watch_cycle()
        health.record_success("mega_watch")
    except Exception:
        log.info("[MEGA] Error during mega-watch cycle:")
        traceback.print_exc()
        health.record_failure("mega_watch")
