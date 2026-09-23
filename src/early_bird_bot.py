"""Early-bird bot: catch fresh tweets from mega accounts within minutes.

Why this matters more than any other reply path: being in the TOP 5 replies
on a viral tweet is a 10-100x impressions multiplier vs. landing as reply
#50 an hour later. The standard reply bot fires every 20 min — too slow to
consistently land top-5 on a fresh banger from sama / OpenAI / Mathieu.

Strategy:
- Every 5 min, pick a few mega accounts at random.
- Scrape their latest tweets (existing scraper).
- If any tweet is < 12 min old AND we haven't replied yet → reply NOW.
- Hard cap 1 reply per cycle. Lock-before-post URL dedup. Same dead-tweet
  filter as direct_reply (won't reply to tweets with 0 engagement YET — but
  the threshold is loose because fresh tweets often have 0 likes).
- Source-tagged "EARLYBIRD/<handle>" so the strategy agent sees it.
"""
import random
import time
import traceback
from .config import BLOCKLIST, BOT_HANDLE
from .logger import log
from .twitter_client import scrape_profile_tweets, reply_to_tweet
from .replied_store import load_replied
from .reply_bot import _tweet_age_minutes, _handle_from_url, _is_reply_like_tweet
from .direct_reply import _LLM_RATE_LIMITED, _generate_single_reply, _is_on_niche, _looks_french
from .engagement_log import log_reply
from .humanizer import humanize

_OWN_HANDLE = BOT_HANDLE.lower()

# 2026-06-07 PM (operator): "stop going to the static accounts… develop
# yourself the list of accounts you want to follow and track" — the static
# list is GONE. The scan pool now comes from account_curator.tracked_handles()
# (the bot's own earned list: authors whose posts it kept engaging, weighted
# by follower-conversion evidence), pinned with TheBTCTherapist + Graphseo,
# the only two operator-mandated keepers.
EARLY_BIRD_ACCOUNTS: list = []  # intentionally empty — see _scan_pool()


def _scan_pool() -> list:
    from .account_curator import tracked_handles
    return tracked_handles(limit=30)

# A tweet is "early-bird eligible" if it's at most this many minutes old.
# Goal: land in top ~5 replies. Sweet spot is ~5-15 min depending on the
# account's audience size. 12 is a balance.
EARLY_BIRD_AGE_MAX_MIN = 18
# 2 -> 4 (2026-05-06 PM growth push). Top-5-reply on a viral tweet is
# the single highest impressions multiplier we have (10-100x), and we
# only fire 4-5x per hour, so capping at 2 was leaving slots on the table.
EARLY_BIRD_MAX_REPLIES_PER_CYCLE = 15


def run_early_bird_cycle():
    """One scan: pick a few mega accounts, reply to ANY fresh tweet found."""
    replied = load_replied()
    posted = 0

    # Apply autonomous evolution: filter pruned + double-weight reinforced accounts
    from .evolution_store import filter_and_weight
    from .direct_reply import ALWAYS_REPLY_ACCOUNTS
    pool = filter_and_weight(_scan_pool())
    always_pool = filter_and_weight(ALWAYS_REPLY_ACCOUNTS)

    # Growth push: scan the always-reply accounts first, then fill with random
    # mega accounts. Early replies under big accounts are the highest upside
    # surface, so avoid pure random sampling.
    priority_picks = random.sample(always_pool, k=min(4, len(always_pool)))
    filler = [h for h in pool if h not in priority_picks]
    random_picks = random.sample(filler, k=min(3, len(filler)))
    picks = list(dict.fromkeys(priority_picks + random_picks))

    for username in picks:
        if posted >= EARLY_BIRD_MAX_REPLIES_PER_CYCLE:
            break

        log.info(f"[EARLYBIRD] Scanning @{username} for fresh tweets...")
        try:
            # Only the top 3 tweets — anything older isn't fresh anyway.
            tweets = scrape_profile_tweets(username, max_tweets=3)
        except Exception:
            log.info(f"[EARLYBIRD] Scrape failed for @{username}:")
            traceback.print_exc()
            continue

        if not tweets:
            continue

        for tweet in tweets:
            url = tweet.get("url", "")
            text = tweet.get("text", "")
            if not url or url in replied:
                continue
            if _is_reply_like_tweet(tweet, expected_author=username):
                log.info(f"[EARLYBIRD] Looks like a thread reply — skipping {url}")
                continue

            # Block self + blocklisted
            url_handle = _handle_from_url(url)
            if url_handle in BLOCKLIST or url_handle == _OWN_HANDLE:
                continue
            if username.lower() in BLOCKLIST or username.lower() == _OWN_HANDLE:
                continue

            age = _tweet_age_minutes(url)
            if age > EARLY_BIRD_AGE_MAX_MIN:
                continue  # too late — drops down to standard reply bot territory
            if age < 0 or age > 9000:
                continue  # parse failure / clock skew

            # Niche gate — earlybird scans broad media accounts (BFMTV, France24,
            # unusual_whales, etc.), so fresh tweets are often off-mission
            # (aviation pricing, foreign politics, sports). The bot still produced
            # OK punchlines but it drifts the account brand and burns cap budget on
            # tweets that won't convert FR AI/crypto/bourse readers. Reuse the same
            # word-boundary regex direct_reply uses for FOLLOWING/FEED.
            if not _is_on_niche(text):
                log.info(f"[EARLYBIRD] Off-niche topic — skipping @{username}: {text[:60]}")
                continue

            log.info(f"[EARLYBIRD] FRESH ({age}min) @{username}: {text[:80]}...")
            reply = _generate_single_reply(
                username,
                text,
                lang="fr" if _looks_french(text) else "en",
            )
            if reply is _LLM_RATE_LIMITED:
                log.info("[EARLYBIRD] LLM budget reached; stopping this cycle before posting attempts.")
                return
            if not reply:
                log.info(f"[EARLYBIRD] Generation returned SKIP for @{username}.")
                # Don't add to replied — we want to retry next cycle if we generate
                # a better take then. The 5-min cadence will catch it again.
                continue

            from .pattern_tags import extract_pattern as _extract_pattern
            reply, _pattern_id = _extract_pattern(reply)
            reply = humanize(reply)
            log.info(f"[EARLYBIRD] Reply ({len(reply)} chars): {reply}")

            # ⛔ NO premark — the reply_to_tweet chokepoint marks the store
            # itself pre-post and refuses anything already in it (premark =
            # 100% silent self-skip, 2026-06-07 post-mortem).
            replied.add(url)  # in-memory only: no same-cycle retry

            try:
                if not reply_to_tweet(url, reply):
                    continue  # chokepoint skip — nothing posted, no phantom log
                try:
                    log_reply(url, reply, action_type="reply", source=f"EARLYBIRD/{username}", pattern_id=_pattern_id or "")
                except Exception:
                    pass
                posted += 1
                time.sleep(random.randint(5, 12))
                break  # one reply per scanned account = move on
            except Exception:
                log.info(f"[EARLYBIRD] Post failed for {url}:")
                traceback.print_exc()

    if posted:
        log.info(f"[EARLYBIRD] Posted {posted} fresh reply this cycle.")
    else:
        log.info("[EARLYBIRD] No fresh tweets in window this cycle.")


def safe_run_early_bird_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_early_bird_cycle()
        health.record_success("early_bird")
    except Exception:
        log.info("[EARLYBIRD] Error during early-bird cycle:")
        traceback.print_exc()
        health.record_failure("early_bird")
