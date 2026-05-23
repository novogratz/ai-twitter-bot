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
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url
from .direct_reply import _LLM_RATE_LIMITED, _generate_single_reply, _is_on_niche
from .engagement_log import log_reply
from .humanizer import humanize

_OWN_HANDLE = BOT_HANDLE.lower()

# Top-10 mega accounts where being among the first 5 replies pays off
# disproportionately. Curated tight — adding a noisy account just dilutes
# the cycle's 90-sec window.
MEGA_ACCOUNTS = [
    "sama", "OpenAI", "AnthropicAI", "elonmusk",
    "MistralAI", "arthurmensch",
    "lesechos", "BFMBourse", "LeJournalDuCoin",
    "naval",
    # AI researchers — user mandate 2026-05-23. Fresh tweets from these
    # accounts are gold for early-reply algo amplification.
    "karpathy", "ylecun", "fchollet", "AndrewYNg", "demishassabis",
    "ID_AA_Carmack", "lilianweng", "drfeifei", "jeremyphoward", "gwern",
]

MAX_AGE_MIN = 4
MAX_REPLIES_PER_CYCLE = 2


def run_mega_watch_cycle():
    """Pick 5 mega accounts at random, reply to any fresh tweet."""
    replied = load_replied()
    posted = 0

    sample = random.sample(MEGA_ACCOUNTS, k=min(5, len(MEGA_ACCOUNTS)))
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
            # MEGA/sama source replying to x.com/cryptoiadecode/status/...
            if author == _OWN_HANDLE or url_handle == _OWN_HANDLE:
                continue
            text = (t.get("text") or "").strip()
            if not text:
                continue
            # Mega-account replies usually have NO age in the scrape;
            # fall back to "if it's not in our replied set, treat as
            # fresh enough for these handles".
            try:
                age_min = _tweet_age_minutes(t)
            except Exception:
                age_min = 0
            if age_min and age_min > MAX_AGE_MIN:
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
            )
            if reply_text is _LLM_RATE_LIMITED:
                log.info("[MEGA] LLM budget reached; stopping this cycle before posting attempts.")
                return
            if not reply_text:
                continue
            reply_text = humanize(reply_text)
            if len(reply_text) < 10 or len(reply_text) > 270:
                continue

            # Lock URL in BEFORE posting.
            replied.add(url)
            save_replied(replied)

            try:
                reply_to_tweet(url, reply_text)
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
