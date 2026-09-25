"""What a tweet's status URL says: its author, its status ID, its age.

The scraper's `author` field is a display name; the URL is the only
reliable source for the handle (AGENTS.md: handles come from URLs). Reply
admission, the Replied store and the reply jobs read it here, so they
agree: an anonymous `/i/` URL has no author. Legacy modules still parse
URLs through `reply_bot`. `is_reply_like_tweet` tells the reply jobs which
scraped tweets are nested replies they should not target.
"""
import re
from datetime import datetime, timedelta, timezone

# Snowflake epoch: ms since 2010-11-04T01:42:54.657Z.
_TWITTER_EPOCH_MS = 1288834974657
_AUTHOR_RE = re.compile(r"x\.com/([A-Za-z0-9_]{1,15})/status/\d")
_STATUS_RE = re.compile(r"/status/(\d+)")


def author(url: str) -> str:
    """Lowercase author handle, or "" when the URL names none (`/i/`)."""
    m = _AUTHOR_RE.search(url or "")
    if not m or m.group(1).lower() == "i":
        return ""
    return m.group(1).lower()


def status_id(url: str) -> str:
    """The tweet's status ID, or "" when the URL carries none."""
    m = _STATUS_RE.search(url or "")
    return m.group(1) if m else ""


def age(url: str, now: datetime | None = None) -> timedelta | None:
    """Time since the tweet was posted, read from its snowflake ID; None
    when the URL carries no status ID."""
    sid = status_id(url)
    if not sid:
        return None
    posted = datetime.fromtimestamp(((int(sid) >> 22) + _TWITTER_EPOCH_MS) / 1000, tz=timezone.utc)
    return (now or datetime.now(tz=timezone.utc)) - posted


def is_reply_like_tweet(tweet: dict, expected_author: str = "") -> bool:
    """Return True for nested replies/thread comments we should not target,
    and, on a scanned profile, for posts whose URL names another author.
    The scraped display name is never compared to `expected_author`."""
    text = (tweet.get("text") or "").lstrip()
    if text.startswith("@") or bool(tweet.get("is_reply")):
        return True
    expected = (expected_author or "").lower().lstrip("@")
    url_handle = author(tweet.get("url") or "")
    return bool(expected and url_handle and url_handle != expected)
