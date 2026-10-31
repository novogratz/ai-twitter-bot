"""Bounded, disposable handoff from page readers to the watched-author jobs."""
import threading

from . import account, settings
from ..x import x_urls

_lock = threading.Lock()
_tweets = {}


def offer(tweets):
    handles = account.current().auto_engage_handles
    if not handles:
        return
    with _lock:
        for tweet in tweets:
            url = x_urls.canonical_status_url(tweet.get("url", ""))
            if (url and x_urls.author(url) in handles
                    and not x_urls.is_reply_like_tweet(tweet)):
                _tweets[url] = {**tweet, "url": url}
        keep = sorted(_tweets, key=lambda u: int(x_urls.status_id(u)), reverse=True)
        for url in keep[settings.get("PRIORITY_WATCH_QUEUE_LIMIT"):]:
            del _tweets[url]


def take():
    with _lock:
        tweets = list(_tweets.values())
        _tweets.clear()
        return tweets
