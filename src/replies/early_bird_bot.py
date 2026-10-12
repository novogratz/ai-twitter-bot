"""Collect watched profiles' standalone topic posts for the shared Reply pool.

Frequent scans discover new posts quickly, but accept the pool's full 24-hour
window (operator 2026-10-12). Selection, drafting and publishing stay in the
shared selector. Discoveries retain the EARLYBIRD/<handle> source tag.
"""
from ..core.logger import log
from ..core.topic_evidence import MAX_AGE
from ..x.scraper import scrape_profile_tweets
from . import reply_pipeline, reply_source
from .direct_reply import reply_call
from .reply_generator import LanguageRule

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

# 2 -> 4 (2026-05-06 PM growth push). Top-5-reply on a viral tweet is
# the single highest impressions multiplier we have (10-100x), and we
# only fire 4-5x per hour, so capping at 2 was leaving slots on the table.
EARLY_BIRD_MAX_REPLIES_PER_CYCLE = 15
_SCAN_OFFSET = 0


def run_early_bird_cycle():
    """One scan: save discoveries and queue eligible fresh posts for selection."""
    global _SCAN_OFFSET
    posted = 0

    # Apply autonomous evolution: filter pruned + double-weight reinforced accounts
    from ..core.evolution_store import filter_and_weight
    from .direct_reply import always_reply_accounts
    from ..x.scraper import _profile_visit_allowed
    pool = [h for h in filter_and_weight(_scan_pool()) if _profile_visit_allowed(h)]
    always_pool = list(dict.fromkeys(h for h in filter_and_weight(always_reply_accounts()) if _profile_visit_allowed(h)))

    # Bounded rotation covers quieter builders without revisiting the same
    # priority profile in every collector (operator 2026-10-12).
    ordered = list(dict.fromkeys(always_pool + pool))
    picks = [ordered[(_SCAN_OFFSET + i) % len(ordered)] for i in range(min(2, len(ordered)))]
    _SCAN_OFFSET = (_SCAN_OFFSET + len(picks)) % max(1, len(ordered))

    cycle = reply_pipeline.Cycle()
    for username in picks:
        if posted >= EARLY_BIRD_MAX_REPLIES_PER_CYCLE or cycle.rate_limited:
            break

        log.info(f"[EARLYBIRD] Scanning @{username} for fresh tweets...")
        # Sample the latest posts; age eligibility uses the full pool window.
        tweets = reply_pipeline.scrape("EARLYBIRD", f"@{username}", scrape_profile_tweets, username,
                                       max_tweets=3)
        # One reply per scanned account, then move on.
        posted += reply_pipeline.run(JOB, _fresh_candidates(username, tweets), cycle, max_shipped=1)

    if posted:
        log.info(f"[EARLYBIRD] Posted {posted} fresh reply this cycle.")
    else:
        log.info("[EARLYBIRD] Scan completed; eligible posts saved for Reply selection.")


def _fresh_candidates(username: str, tweets: list) -> list:
    declaration = reply_source.Declaration(max_age=MAX_AGE, root_only=True,
                                           author=username, niche=True)
    return reply_source.select(tweets, declaration, f"EARLYBIRD/{username}")
