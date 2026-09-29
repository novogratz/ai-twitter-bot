"""Reply source: the candidates a Reply job's declaration selects among the
posts it scraped.

A job declares what it answers: the oldest post, root posts only or not,
the author a scanned profile's posts must carry in their URL, the Account's
niche or not, and the order. `select` applies it the same way for every job
and has no side effect: no log, no store, no scrape. REPLY_MAX_AGE_MINUTES
caps every declaration's oldest post, as the Reply admission refuses an
older one: a job only picks among posts it may answer. A post without a URL,
without text, or of unknown or negative age (a status ID from the future:
clock skew) is never a candidate. The job keeps its sub-sources, its budget
and its Reply call.

`pinned_accounts` gives the profiles early_bird and mega_watch scan.
"""
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from ..core import account, settings
from ..guards.reply_admission import is_blocked_account
from ..x import x_urls
from .reply_pipeline import Candidate


class Order(Enum):
    SCRAPED = "scraped"
    FRESH_AND_RISING = "fresh_and_rising"
    NEWEST = "newest"


@dataclass(frozen=True)
class Declaration:
    """What a job answers. Only `max_age` is required; every other filter
    is off until the job turns it on. Build it at call time so the settings
    it reads stay live."""
    max_age: timedelta
    root_only: bool = False
    # A handle, "@" optional; an anonymous `/i/` URL names none and passes.
    author: str = ""
    niche: bool = False
    order: Order = Order.SCRAPED


def pinned_accounts(limit: int) -> list:
    """The Account's pinned accounts, PINNED_TRACKED_HANDLES (its
    network.pinned_tracked unless .env sets it), in their order: a handle
    listed twice kept at its first place, case ignored, a Blocked account
    left out, `limit` at most."""
    pool, seen = [], set()
    for raw in settings.get("PINNED_TRACKED_HANDLES").split(","):
        handle = raw.strip().lstrip("@")
        if not handle or handle.lower() in seen or is_blocked_account(handle):
            continue
        seen.add(handle.lower())
        pool.append(handle)
    return pool[:limit]


def is_on_niche(text: str) -> bool:
    niche = account.current().niche
    return bool(niche.post.search(text) or (niche.ticker and niche.ticker.search(text)))


def freshness_sort_key(tweet):
    """Order candidates fresh-and-rising first (2026-06-07 spec: 'front-load
    to fresh, fast-rising posts (posted < ~30-60 min ago and climbing)').

    Primary: age bucket (<=60 min, <=6h, older, unknown-age last).
    Secondary within a bucket: likes-per-minute velocity, highest first.
    First-hour replies are where the algo weight and the profile-visit
    conversion live; a 60-hour-old tweet must never consume the slot a
    20-minute riser deserved.
    """
    age = x_urls.age(tweet.get("url", ""))
    if age is None:
        return (3, 0.0, float("inf"))
    minutes = age.total_seconds() / 60
    bucket = 0 if minutes <= 60 else 1 if minutes <= 360 else 2
    velocity = (tweet.get("likes") or 0) / max(minutes, 1.0)
    return (bucket, -velocity, minutes)


def _newest_first(tweet):
    age = x_urls.age(tweet.get("url") or "")
    return timedelta.max if age is None else age


def select(tweets: list, declaration: Declaration, tag: str) -> list:
    """The Candidates among `tweets` that `declaration` answers, in its
    order, each logged under `tag`."""
    if declaration.order is Order.FRESH_AND_RISING:
        tweets = sorted(tweets, key=freshness_sort_key)
    elif declaration.order is Order.NEWEST:
        tweets = sorted(tweets, key=_newest_first)
    author = declaration.author.lower().lstrip("@")
    oldest = min(declaration.max_age, timedelta(minutes=settings.get("REPLY_MAX_AGE_MINUTES")))
    candidates = []
    for tweet in tweets:
        url = tweet.get("url") or ""
        text = tweet.get("text") or ""
        if not url or not text.strip():
            continue
        if declaration.root_only and x_urls.is_reply_like_tweet(tweet):
            continue
        if author and x_urls.author(url) not in ("", author):
            continue
        if declaration.niche and not is_on_niche(text.strip()):
            continue
        age = x_urls.age(url)
        if age is None or age < timedelta(0) or age > oldest:
            continue
        candidates.append(Candidate(url, text, tag))
    return candidates
