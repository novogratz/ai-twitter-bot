"""Early-bird bot: catch fresh tweets from mega accounts within minutes.

Why this matters more than any other reply path: being in the TOP 5 replies
on a viral tweet is a 10-100x impressions multiplier vs. landing as reply
#50 an hour later. The standard reply bot fires every 20 min — too slow to
consistently land top-5 on a fresh banger from sama / OpenAI / Mathieu.

Strategy:
- Every 5 min, pick a few mega accounts at random.
- Scrape their latest tweets (existing scraper).
- If any tweet is < 18 min old and Reply admission lets it through → reply NOW.
- One reply per scanned account per cycle; the chokepoint owns the dedup.
- Source-tagged "EARLYBIRD/<handle>" so the strategy agent sees it.
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

# The author Reply admission read from the status URL names the parent in
# the prompt, not the scanned handle. No FR-forced override on this job
# (pinned in the tests).
JOB = reply_pipeline.Job("early_bird", "EARLYBIRD",
                         reply_call=lambda author: reply_call(author, LanguageRule.PARENT), pause=(5, 12))

# 2026-06-07 PM (operator): "stop going to the static accounts… develop
# yourself the list of accounts you want to follow and track" — the static
# list is GONE. The scan pool now comes from account_curator.tracked_handles()
# (the bot's own earned list: authors whose posts it kept engaging, weighted
# by follower-conversion evidence), pinned with TheBTCTherapist + Graphseo,
# the only two operator-mandated keepers.
EARLY_BIRD_ACCOUNTS: list = []  # intentionally empty — see _scan_pool()


def _scan_pool() -> list:
    from ..account.account_curator import tracked_handles
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
    posted = 0

    # Apply autonomous evolution: filter pruned + double-weight reinforced accounts
    from ..core.evolution_store import filter_and_weight
    from .direct_reply import always_reply_accounts
    pool = filter_and_weight(_scan_pool())
    always_pool = filter_and_weight(always_reply_accounts())

    # Growth push: scan the always-reply accounts first, then fill with random
    # mega accounts. Early replies under big accounts are the highest upside
    # surface, so avoid pure random sampling.
    priority_picks = random.sample(always_pool, k=min(4, len(always_pool)))
    filler = [h for h in pool if h not in priority_picks]
    random_picks = random.sample(filler, k=min(3, len(filler)))
    picks = list(dict.fromkeys(priority_picks + random_picks))

    cycle = reply_pipeline.Cycle()
    for username in picks:
        if posted >= EARLY_BIRD_MAX_REPLIES_PER_CYCLE or cycle.rate_limited:
            break

        log.info(f"[EARLYBIRD] Scanning @{username} for fresh tweets...")
        # Only the top 3 tweets — anything older isn't fresh anyway.
        tweets = reply_pipeline.scrape("EARLYBIRD", f"@{username}", scrape_profile_tweets, username,
                                       max_tweets=3)
        # One reply per scanned account, then move on.
        posted += reply_pipeline.run(JOB, _fresh_candidates(username, tweets), cycle, max_shipped=1)

    if posted:
        log.info(f"[EARLYBIRD] Posted {posted} fresh reply this cycle.")
    else:
        log.info("[EARLYBIRD] No fresh tweets in window this cycle.")


def _fresh_candidates(username: str, tweets: list) -> list:
    candidates = []
    for tweet in tweets:
        url = tweet.get("url", "")
        text = tweet.get("text", "")
        if not url:
            continue
        if x_urls.is_reply_like_tweet(tweet, expected_author=username):
            log.info(f"[EARLYBIRD] Looks like a thread reply — skipping {url}")
            continue

        age = x_urls.age(url)
        if age is None or age < timedelta(0):
            continue  # no status ID / clock skew
        if age > timedelta(minutes=EARLY_BIRD_AGE_MAX_MIN):
            continue  # too late — drops down to standard reply bot territory

        # Niche gate — earlybird scans broad media accounts (BFMTV, France24,
        # unusual_whales, etc.), so fresh tweets are often off-mission
        # (aviation pricing, foreign politics, sports). The bot still produced
        # OK punchlines but it drifts the account brand and burns cap budget on
        # tweets that won't convert FR AI/crypto/bourse readers. Reuse the same
        # word-boundary regex direct_reply uses for its search lane.
        if not is_on_niche(text):
            log.info(f"[EARLYBIRD] Off-niche topic — skipping @{username}: {text[:60]}")
            continue

        log.info(f"[EARLYBIRD] FRESH ({int(age.total_seconds() // 60)}min) @{username}: {text[:80]}...")
        candidates.append(reply_pipeline.Candidate(url, text, f"EARLYBIRD/{username}"))
    return candidates


def safe_run_early_bird_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_early_bird_cycle()
        health.record_success("early_bird")
    except Exception:
        log.info("[EARLYBIRD] Error during early-bird cycle:")
        traceback.print_exc()
        health.record_failure("early_bird")
