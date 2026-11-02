"""Early-bird Replies to fresh standalone posts by discovered authors.

Bounded Latest author searches preserve the profile allowlist. The existing
18-minute horizon, per-author budget, niche policy and shared Reply admission
apply; early discovery is no promise of impressions."""
import random
from datetime import timedelta
from ..x import x_urls
from ..core.logger import log
from ..x.scraper import scrape_x_search
from . import reply_pipeline
from .direct_reply import is_on_niche, reply_call
from .reply_generator import LanguageRule
from .reply_source import author_search_query, source_text, observed_likes

# The author Reply admission read from the status URL names the parent in
# the prompt, not the scanned handle. No FR-forced override on this job
# (pinned in the tests).
JOB = reply_pipeline.Job("early_bird", "EARLYBIRD",
                         reply_call=lambda author: reply_call(author, LanguageRule.PARENT), pause=(5, 12))

# 2026-06-07 PM (operator): "stop going to the static accounts… develop
# yourself the list of accounts you want to follow and track" — the static
# list is GONE.

# The scan pool comes from account_curator.tracked_handles(): the bot's own
# earned list (authors whose posts it kept engaging, weighted by
# follower-conversion evidence), with the Account's network.pinned_tracked
# always first.
EARLY_BIRD_ACCOUNTS: list = []  # intentionally empty — see _scan_pool()


def _scan_pool() -> list:
    from ..account.account_curator import tracked_handles
    return tracked_handles(limit=30)

# Freshness and cycle budgets stay independent of popularity.
EARLY_BIRD_AGE_MAX_MIN = 18
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
        tweets = reply_pipeline.scrape("EARLYBIRD", f"@{username}", scrape_x_search,
                                       author_search_query(username), tab="latest", max_tweets=3, text_limit=1200)
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
        if (not x_urls.canonical_status_url(url)
                or x_urls.author(url) != username.lower().lstrip("@")):
            continue
        if x_urls.is_reply_like_tweet(tweet, expected_author=username):
            log.info(f"[EARLYBIRD] Looks like a thread reply — skipping {url}")
            continue

        age = x_urls.age(url)
        if age is None or age < timedelta(0):
            continue  # no status ID / clock skew
        if age > timedelta(minutes=EARLY_BIRD_AGE_MAX_MIN):
            continue  # too late — drops down to standard reply bot territory

        # Every discovered author remains subject to the Account niche.
        if not is_on_niche(text):
            log.info(f"[EARLYBIRD] Off-niche topic — skipping @{username}: {text[:60]}")
            continue

        log.info(f"[EARLYBIRD] FRESH ({int(age.total_seconds() // 60)}min) @{username}: {text[:80]}...")
        candidates.append(reply_pipeline.Candidate(url, source_text(tweet), f"EARLYBIRD/{username}",
                                                   likes=observed_likes(tweet)))
    return candidates
