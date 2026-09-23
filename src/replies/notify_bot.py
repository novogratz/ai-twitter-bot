"""Notify bot: likes replies on own tweets and replies back to build loyalty."""
import re
import traceback
from ..core.config import BLOCKLIST, BOT_HANDLE
from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..x.twitter_client import (
    like_own_tweet_replies,
    scrape_own_tweet_and_replies,
    reply_to_tweet_in_thread,
    post_tweet,
    visit_profile_and_like,
    is_own_post as _is_own_post,
)
from .replyback_agent import generate_replyback
from ..core.humanizer import humanize
from ..guards.reply_admission import judge_parent
import random

_OWN_HANDLE = BOT_HANDLE.lower()
# Replies this job is done with until restart: definitive Reply admission
# refusals, replies the model declined, replies answered.
_skipped: set = set()
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])")


def _influencer_handles() -> set:
    """Merge engage + reply-target lists into a single lowercase set."""
    from ..account.engage_bot import TARGET_ACCOUNTS as ENGAGE_TARGETS
    from .reply_agent import TARGET_ACCOUNTS as REPLY_TARGETS
    return {h.lower() for h in list(ENGAGE_TARGETS) + list(REPLY_TARGETS)}


def _extract_handle(user_string: str) -> str:
    """Extract @handle (lowercase, no @) from a User-Name text blob."""
    if not user_string:
        return ""
    mentions = _MENTION_RE.findall(user_string)
    if mentions:
        return mentions[-1].lower()
    handle = user_string.strip().lstrip("@").lower()
    if _HANDLE_RE.fullmatch(handle):
        return handle
    return ""


def _is_blocklisted(user_string: str, handle: str) -> bool:
    """Hardened blocklist check for the reciprocity likes; Replies go
    through Reply admission instead.

    Bug 2026-04-26: scraper sometimes returned a display name ("la pique")
    instead of the @handle ("pgm_pm"), so `handle in BLOCKLIST` missed and
    we replied to + followed back @pgm_pm — the exact bot-vs-bot loop the
    blocklist exists to prevent. Now we also scan the raw user string for
    any blocklisted token, so display-name variants are caught even if
    only the @handle is in BLOCKLIST.
    """
    if handle and handle in BLOCKLIST:
        return True
    user_lower = (user_string or "").lower()
    for blocked in BLOCKLIST:
        if blocked and blocked in user_lower:
            return True
    return False


def run_notify_cycle():
    """Visit own latest tweet, like replies, and build loyalty."""
    log.info("[NOTIFY] Checking replies on latest tweet...")
    like_own_tweet_replies()
    log.info("[NOTIFY] Done.")


def run_replyback_cycle():
    """Scrape replies on own tweets and reply back to create conversation threads.
    Threads boost both tweets in the algorithm. Influencer replies get nested
    in-thread responses (lands UNDER their reply); others get a standalone @mention.
    """
    log.info("[REPLYBACK] Scanning for replies to engage with...")

    data = scrape_own_tweet_and_replies()
    if not data or not data.get("replies"):
        log.info("[REPLYBACK] No replies found.")
        return

    own_tweet = data["own_tweet"]
    replies = data["replies"]
    influencers = _influencer_handles()
    count = 0

    # Conversation depth: when our parent tweet gets replies, the algo is
    # rewarding it. Sustained back-and-forth pumps it further and converts
    # warm engagers into followers.
    incoming = len(replies)
    if incoming >= 50:
        cycle_cap = 18
    elif incoming >= 30:
        cycle_cap = 15
    elif incoming >= 20:
        cycle_cap = 12
    elif incoming >= 10:
        cycle_cap = 9
    else:
        cycle_cap = 7
    log.info(f"[REPLYBACK] Parent has {incoming} replies — cap {cycle_cap} this cycle.")

    for reply_info in replies[:cycle_cap]:
        user = reply_info.get("user", "")
        text = reply_info.get("text", "")
        reply_url = reply_info.get("url", "")

        # IN-THREAD-ONLY rule (user directive 2026-04-27 PM, before 2-week
        # away mission): NEVER post standalone @mention tweets — they land
        # as new posts on our profile and look like spam. If we don't have
        # a reply_url to nest under, SKIP the engager. Loyalty-building is
        # only worth it when it stays inside the conversation.
        if not reply_url:
            log.info(f"[REPLYBACK] No reply_url for user={user!r} — skipping (in-thread-only rule).")
            continue
        if reply_url in _skipped:
            continue

        # Skip very short or empty replies
        if len(text) < 5:
            continue

        # Answering someone who answered us is a Debate turn. Admission
        # reads the author from the URL, never from the display name.
        verdict = judge_parent(reply_url, debate_turn=True)
        if not verdict:
            if verdict.refusal.definitive:
                _skipped.add(reply_url)
            log.info(f"[REPLYBACK] Not admitted ({verdict.refusal.value}: {verdict.reason}) - skipping.")
            continue
        handle = verdict.author

        is_influencer = handle in influencers
        log.info(
            f"[REPLYBACK] {'[INFLUENCER] ' if is_influencer else ''}"
            f"Replying to @{handle}: {text[:60]}..."
        )
        reply = generate_replyback(own_tweet, text)
        if not reply:
            continue  # failed call: replayable next cycle
        if reply.strip().upper().startswith("SKIP"):
            _skipped.add(reply_url)  # the model declined
            continue

        reply = humanize(reply)
        log.info(f"[REPLYBACK] Reply ({len(reply)} chars): {reply}")

        try:
            # All reply-backs are nested in-thread now (influencer or not).
            if not reply_to_tweet_in_thread(reply_url, reply, debate_turn=True):
                continue  # chokepoint skip — stays fresh, no phantom count
            _skipped.add(reply_url)
            count += 1
        except StateUnreadable:
            raise  # no reply can ship: stop paying for generations
        except Exception:
            log.info(f"[REPLYBACK] Failed to reply back:")
            traceback.print_exc()

    log.info(f"[REPLYBACK] Replied back to {count} people.")

    # Reciprocity loop: for non-influencer engagers, visit their profile and
    # like 1 of their tweets. Triggers a notification on their side, often
    # converts to follow-back. Cap small (max 2/cycle) to avoid spam patterns.
    _reciprocate_engagers(replies, influencers, max_visits=5)


def _reciprocate_engagers(replies: list, influencers: set, max_visits: int = 5):
    """Visit a few engagers' profiles and like their posts.

    Skip influencers (they don't need our reciprocity, and visiting them
    doesn't move our follower count). Skip blocklist + self. 85% probability
    per eligible engager so the pattern doesn't look mechanical. Hard cap =
    max_visits per cycle to stay under bot detection.

    No follow here: engager follows belong to follow_engagers_job, which
    reads the ledger's Debate turns and passes engager=True (CONTEXT.md:
    Engager).
    """
    visited = 0
    seen_handles = set()
    candidates = list(replies)
    random.shuffle(candidates)  # don't always hit the same top-of-list person

    for r in candidates:
        if visited >= max_visits:
            break
        user_str = r.get("user", "")
        handle = _extract_handle(user_str)
        if not handle or handle in seen_handles:
            continue
        seen_handles.add(handle)
        # Hardened blocklist: catches display-name variants from scraper.
        if _is_blocklisted(user_str, handle) or handle == _OWN_HANDLE:
            continue
        if handle in influencers:
            continue  # influencers already notice us via the in-thread reply
        if random.random() > 0.85:
            continue  # randomize so the pattern isn't mechanical

        log.info(f"[RECIPROCATE] Visiting @{handle} (like)...")
        try:
            visit_profile_and_like(handle, like_count=2)
            visited += 1
        except Exception:
            log.info(f"[RECIPROCATE] Failed to reciprocate @{handle}:")
            traceback.print_exc()

    if visited:
        log.info(f"[RECIPROCATE] Engaged back with {visited} engager(s).")


def safe_run_notify_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_notify_cycle()
        health.record_success("notify")
    except Exception:
        log.info("[NOTIFY] Error during notify cycle:")
        traceback.print_exc()
        health.record_failure("notify")


def safe_run_replyback_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_replyback_cycle()
        health.record_success("replyback")
    except Exception:
        log.info("[REPLYBACK] Error during replyback cycle:")
        traceback.print_exc()
        health.record_failure("replyback")

