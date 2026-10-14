"""src/x/x_urls: author, status ID and age read from a status URL."""
from datetime import datetime, timedelta, timezone

from src.x import x_urls
from tests.helpers import url


def test_author_comes_from_the_url_handle():
    assert x_urls.author("https://x.com/SomeOne/status/1?s=20") == "someone"
    assert x_urls.author("https://x.com/i/web/status/1") == ""
    assert x_urls.author("https://x.com/someone") == ""
    assert x_urls.author("") == ""


def test_status_id_and_snowflake_age():
    posted = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    sid = (int(posted.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22
    link = url("someone", sid)
    assert x_urls.status_id(link) == str(sid)
    assert x_urls.age(link, now=posted + timedelta(minutes=5)) == timedelta(minutes=5)
    assert x_urls.age("https://x.com/someone") is None


def test_reply_like_tweet_is_a_nested_reply_or_someone_elses_post():
    assert x_urls.is_reply_like_tweet({"url": url("someone"), "text": "@a hi"})
    assert x_urls.is_reply_like_tweet({"url": url("someone"), "text": "hi", "is_reply": True})
    assert not x_urls.is_reply_like_tweet({"url": url("someone"), "text": "hi"})
    own = {"url": url("SomeOne"), "text": "hi", "author": "someone"}
    assert not x_urls.is_reply_like_tweet(own, expected_author="@someone")
    assert x_urls.is_reply_like_tweet(own, expected_author="other")


def test_reply_like_tweet_ignores_the_display_name():
    """Issue #162: the scraped `author` is a display name. "Sam Altman" on
    @sama's own post is still @sama's post; a one-word name matching the
    scanned handle does not make someone else's post ours."""
    sama = {"url": url("sama"), "text": "hi", "author": "Sam Altman"}
    assert not x_urls.is_reply_like_tweet(sama, expected_author="sama")
    reposted = {"url": url("someone"), "text": "hi", "author": "sama"}
    assert x_urls.is_reply_like_tweet(reposted, expected_author="sama")


def test_author_supports_historical_hosts_without_matching_lookalike_urls():
    for host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        assert x_urls.author(f"https://{host}/OldHandle/status/123?s=20") == "oldhandle"
    for url in ("https://notx.com/OldHandle/status/123", "https://example.com/x.com/OldHandle/status/123",
                "https://x.com.evil.test/OldHandle/status/123", "https://example.com/?next=https://x.com/OldHandle/status/123"):
        assert x_urls.author(url) == ""
