"""Notify bot: likes replies on own tweets and replies back to build loyalty."""
import json
import os
import re
import traceback
from .config import _PROJECT_ROOT, BLOCKLIST, BOT_HANDLE
from .logger import log
from .twitter_client import (
    like_own_tweet_replies,
    retweet_own_latest,
    scrape_own_tweet_and_replies,
    reply_to_tweet_in_thread,
    post_tweet,
    visit_profile_and_like,
    follow_account,
)
from .replyback_agent import generate_replyback
from .humanizer import humanize
import random

REPLIED_BACK_FILE = os.path.join(_PROJECT_ROOT, "replied_back.json")
_OWN_HANDLE = BOT_HANDLE.lower()
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])")


def _influencer_handles() -> set:
    """Merge engage + reply-target lists into a single lowercase set."""
    from .engage_bot import TARGET_ACCOUNTS as ENGAGE_TARGETS
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
    """Hardened blocklist check.

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


def _load_replied_back() -> set:
    if os.path.exists(REPLIED_BACK_FILE):
        try:
            with open(REPLIED_BACK_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_replied_back(replied: set):
    with open(REPLIED_BACK_FILE, "w") as f:
        json.dump(list(replied)[-500:], f, indent=2)


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
    replied_back = _load_replied_back()
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
        handle = _extract_handle(user)
        if not handle:
            log.info(f"[REPLYBACK] No usable handle in user={user!r} - skipping.")
            continue

        # Skip blocklisted handles (e.g., @pgm_pm). Hardened to catch
        # display-name variants ("la pique") that the scraper sometimes
        # hands us instead of the @handle.
        if _is_blocklisted(user, handle):
            log.info(f"[REPLYBACK] Blocklisted user={user!r} handle={handle!r} - skipping.")
            continue

        # Skip our own replies (never reply to ourselves)
        if handle == _OWN_HANDLE or _OWN_HANDLE in user.lower():
            log.info(f"[REPLYBACK] Own reply — skipping.")
            continue

        # Skip very short or empty replies
        if len(text) < 5:
            continue

        # Dedup key: prefer reply URL (stable, unique); fall back to text snippet
        dedup_key = reply_url or f"text:{text[:50]}"
        if dedup_key in replied_back:
            continue

        is_influencer = handle in influencers
        log.info(
            f"[REPLYBACK] {'[INFLUENCER] ' if is_influencer else ''}"
            f"Replying to @{handle}: {text[:60]}..."
        )
        reply = generate_replyback(own_tweet, text)
        if not reply:
            continue

        reply = humanize(reply)
        log.info(f"[REPLYBACK] Reply ({len(reply)} chars): {reply}")

        # IN-THREAD-ONLY rule (user directive 2026-04-27 PM, before 2-week
        # away mission): NEVER post standalone @mention tweets — they land
        # as new posts on our profile and look like spam. If we don't have
        # a reply_url to nest under, SKIP the engager. Loyalty-building is
        # only worth it when it stays inside the conversation.
        if not reply_url:
            log.info(f"[REPLYBACK] No reply_url for @{handle} — skipping (in-thread-only rule).")
            continue

        try:
            # All reply-backs are nested in-thread now (influencer or not).
            reply_to_tweet_in_thread(reply_url, reply)
            replied_back.add(dedup_key)
            count += 1
        except Exception:
            log.info(f"[REPLYBACK] Failed to reply back:")
            traceback.print_exc()

    _save_replied_back(replied_back)
    log.info(f"[REPLYBACK] Replied back to {count} people.")

    # Reciprocity loop: for non-influencer engagers, visit their profile and
    # like 1 of their tweets. Triggers a notification on their side, often
    # converts to follow-back. Cap small (max 2/cycle) to avoid spam patterns.
    _reciprocate_engagers(replies, influencers, max_visits=5)


def _reciprocate_engagers(replies: list, influencers: set, max_visits: int = 5):
    """Visit a few engagers' profiles and reciprocate (like + follow-back).

    Skip influencers (they don't need our reciprocity, and visiting them
    doesn't move our follower count). Skip blocklist + self. 60% probability
    per eligible engager so the pattern doesn't look mechanical (was 50%).

    Follow-back loop: someone bothered to reply to us — that's the strongest
    follow-back signal there is. Visiting + liking + following = max chance
    they follow back. Hard cap = max_visits per cycle to stay under bot
    detection. Persisted via engage_bot's followed_accounts.json.
    """
    from .engage_bot import _load_followed, _save_followed
    followed = _load_followed()

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

        log.info(f"[RECIPROCATE] Visiting @{handle} (like + follow-back)...")
        try:
            visit_profile_and_like(handle, like_count=2)
            # Follow-back if not already following — they just engaged with us,
            # this is the highest-conversion follow we can make.
            if handle not in followed:
                try:
                    if follow_account(handle):
                        followed.add(handle)
                        log.info(f"[RECIPROCATE] Followed back @{handle}.")
                    # If JS-click didn't fire, leave it out so we retry next reciprocity pass.
                except Exception:
                    log.info(f"[RECIPROCATE] Follow @{handle} failed:")
                    traceback.print_exc()
            visited += 1
        except Exception:
            log.info(f"[RECIPROCATE] Failed to reciprocate @{handle}:")
            traceback.print_exc()

    if visited:
        _save_followed(followed)
        log.info(f"[RECIPROCATE] Engaged back with {visited} engager(s).")


_BOOST_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "boost_history.json")


def _load_boost_history() -> set:
    if os.path.exists(_BOOST_HISTORY_FILE):
        try:
            with open(_BOOST_HISTORY_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_boost_history(s: set):
    with open(_BOOST_HISTORY_FILE, "w") as f:
        # Cap at 500 — far above any realistic 90-day window.
        json.dump(list(s)[-500:], f)


def run_boost_cycle():
    """Smart boost (2026-05-06): pick our highest-engagement recent post and
    retweet THAT, not just the latest. The latest may be stale or low-signal;
    the cheapest distribution lever should ride our actual viral content.

    Falls back to retweet_own_latest() if scraping fails (so we never miss a
    cycle if X's profile DOM hiccups).
    """
    from .twitter_client import scrape_profile_tweets, retweet_post

    history = _load_boost_history()
    log.info("[BOOST] Scraping own profile to pick best recent post...")
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=12)
    except Exception:
        log.info("[BOOST] Scrape failed — falling back to retweet_own_latest:")
        traceback.print_exc()
        retweet_own_latest()
        log.info("[BOOST] Fallback done.")
        return

    if not tweets:
        log.info("[BOOST] No tweets scraped — falling back to retweet_own_latest.")
        retweet_own_latest()
        log.info("[BOOST] Fallback done.")
        return

    # Filter: must be ours, must have a URL, must not have been boosted before.
    own = []
    bot_lc = BOT_HANDLE.lower()
    for t in tweets:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != bot_lc:
            continue
        url = t.get("url") or ""
        if not url or url in history:
            continue
        own.append({
            "url": url,
            "likes": int(t.get("likes") or 0),
            "replies": int(t.get("replies") or 0),
            "text": (t.get("text") or "").strip(),
        })

    if not own:
        log.info("[BOOST] All recent posts already boosted — using retweet_own_latest.")
        retweet_own_latest()
        log.info("[BOOST] Latest re-boosted as fallback.")
        return

    # Smart boost timing 2026-05-08: prefer the FRESHEST post (top-of-list
    # in scrape order) rather than the highest-likes one. Algo push window
    # is the first 30-60 min after publish — that's when self-RT lifts the
    # most. The historical winners we already boosted; the new one we
    # haven't. Highest-likes fallback if the freshest is identical.
    fresh_top = own[0]  # scraper returns newest-first
    if fresh_top["likes"] >= 1 or len(own) == 1:
        best = fresh_top
        log.info(
            f"[BOOST] Boosting FRESHEST post (algo window): "
            f"{fresh_top['likes']} likes / {fresh_top['replies']} replies — "
            f"{fresh_top['text'][:120]!r}"
        )
    else:
        # Freshest has 0 engagement signal — fall back to highest-likes
        # in the visible window (still better than retweet_own_latest).
        best = max(own, key=lambda c: (c["likes"], c["replies"]))
    history.add(best["url"])
    _save_boost_history(history)
    try:
        retweet_post(best["url"])
        log.info(f"[BOOST] Boosted: {best['url']}")
    except Exception:
        log.info("[BOOST] Boost failed:")
        traceback.print_exc()


def safe_run_notify_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_notify_cycle()
        health.record_success("notify")
    except Exception:
        log.info("[NOTIFY] Error during notify cycle:")
        traceback.print_exc()
        health.record_failure("notify")


def safe_run_replyback_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_replyback_cycle()
        health.record_success("replyback")
    except Exception:
        log.info("[REPLYBACK] Error during replyback cycle:")
        traceback.print_exc()
        health.record_failure("replyback")


def safe_run_boost_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_boost_cycle()
        health.record_success("boost")
    except Exception:
        log.info("[BOOST] Error during boost cycle:")
        traceback.print_exc()
        health.record_failure("boost")
