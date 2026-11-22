"""Discover own originals and dispatch durable one-hour / high-view reposts."""
from ..core import account, config, work_priority
from ..core.logger import log
from ..guards import active_hours, self_repost_store
from ..x import scraper, twitter_client, x_urls


def run_self_repost_discovery():
    if not account.current().self_reposts_enabled or config.dry_run():
        return
    active_hours.require_active()
    self_repost_store.activate()
    # Recent own originals supply one-hour timers. Top also rediscovers older hits.
    handle = account.current().handle
    query = f"from:{handle} -filter:replies -filter:retweets"
    for tab in ("live", "top"):
        tweets = scraper.scrape_x_search(query, max_tweets=40, tab=tab, text_limit=1200, scroll_passes=3)
        for tweet in tweets:
            url = x_urls.canonical_status_url(tweet.get("url", ""))
            if url and x_urls.author(url) == handle.lower() and not x_urls.is_reply_like_tweet(tweet):
                self_repost_store.observe(url, tweet.get("views"))
    log.info("[SELF-REPOST] %d own originals tracked", len(self_repost_store.read()["posts"]))


def run_self_repost_cycle():
    if not account.current().self_reposts_enabled or config.dry_run():
        return
    active_hours.require_active()
    self_repost_store.activate()
    now = active_hours.now_local().timestamp()
    rows = [row for row in self_repost_store.read()["posts"].values() if self_repost_store.due(row, now)]
    # Due one-hour work first, then the most overdue high-view refresh.
    rows.sort(key=lambda r: (r["initial_done"], r["next_due"], -(r["views"] or 0)))
    for row in rows[:1]:
        with work_priority.scope(work_priority.REPLY):
            result = twitter_client.repost_own_post(row["url"])
        log.info("[SELF-REPOST] %s: %s", row["url"], result.value)
