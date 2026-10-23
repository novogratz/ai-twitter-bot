"""What a tweet's status URL says: its author, its status ID, its age.

The scraper's `author` field is a display name; the URL is the only
reliable source for the handle (AGENTS.md: handles come from URLs). Reply
admission, the Replied store and the reply jobs read it here, so they
agree: an anonymous `/i/` URL has no author. `is_reply_like_tweet` tells
the reply jobs which scraped tweets are nested replies they should not
target.
"""
import re
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

# Snowflake epoch: ms since 2010-11-04T01:42:54.657Z.
_TWITTER_EPOCH_MS = 1288834974657
_AUTHOR_RE = re.compile(r"x\.com/([A-Za-z0-9_]{1,15})/status/\d")
_STATUS_RE = re.compile(r"/status/(\d+)")


def canonical_status_url(url: str) -> str:
    """An exact X status URL, with no foreign host, credentials or nested path."""
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlsplit(url or "")
        match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/status/(\d+)/?", parsed.path)
        if (parsed.scheme != "https" or parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
                or parsed.username or parsed.password or parsed.port or not match
                or match[1].lower() == "i"):
            return ""
        return f"https://x.com/{match[1].lower()}/status/{match[2]}"
    except (ValueError, TypeError):
        return ""


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
    posted = posted_at(url)
    return (now or datetime.now(tz=timezone.utc)) - posted if posted is not None else None


def posted_at(url: str) -> datetime | None:
    """A status ID's creation time, without consulting a clock or the browser."""
    sid = status_id(url)
    if not sid:
        return None
    try:
        return datetime.fromtimestamp(((int(sid) >> 22) + _TWITTER_EPOCH_MS) / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def is_reply_like_tweet(tweet: dict, expected_author: str = "") -> bool:
    """Return True for nested replies/thread comments we should not target,
    and, on a scanned profile, for posts whose URL names another author.
    The scraped display name is never compared to `expected_author`."""
    text = (tweet.get("text") or "").lstrip()
    if text.startswith("@") or bool(tweet.get("is_reply")) or any(
            tweet.get(key) for key in ("in_reply_to_status_id", "in_reply_to_tweet_id")):
        return True
    conversation = tweet.get("conversation_id")
    if conversation and str(conversation) != status_id(tweet.get("url") or ""):
        return True
    expected = (expected_author or "").lower().lstrip("@")
    url_handle = author(tweet.get("url") or "")
    return bool(expected and url_handle and url_handle != expected)
