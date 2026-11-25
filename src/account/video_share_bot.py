"""Find viral AI videos on X, review them, and post them with a short take in the Operator's windows."""
import time
from datetime import timedelta

from ..core import account, config, settings
from ..core.logger import log
from ..guards import active_hours, video_share_store as store
from ..video import repost_review
from ..video.security import AccessError
from ..x import scraper, twitter_client, x_urls

_candidates = {}  # url -> scraped row; disposable
_declined = {}    # url -> monotonic time
_approved = []    # reviewed and waiting for its turn: (url, take, media_id, source_text, at)
_cursor = 0
_next_search = 0.0


def _discover():
    """One Top search per turn across the Account's queries; leads only."""
    global _cursor, _next_search
    queries = account.current().video_share_queries
    if not queries or time.monotonic() < _next_search:
        return
    _next_search = time.monotonic() + 300
    query = queries[_cursor % len(queries)]
    _cursor += 1
    floor = settings.get("VIDEO_SHARE_MIN_LIKES")
    # Top results reach back for days; the date keeps them inside the share age.
    since = (active_hours.now_local() - timedelta(hours=settings.get("VIDEO_SHARE_MAX_AGE_HOURS"))).date().isoformat()
    for tweet in scraper.scrape_x_search(f"{query} since:{since}", max_tweets=20, tab="top", text_limit=600):
        url = x_urls.canonical_status_url(tweet.get("url", ""))
        if (url and tweet.get("has_video") and not tweet.get("is_reply") and (tweet.get("likes") or 0) >= floor
                and store.eligible(url) and not store.contains(url) and url not in _declined):
            _candidates[url] = {**tweet, "url": url}
    log.info("[VIDEO-SHARE] %r: %d lead(s) waiting", query, len(_candidates))


def _next():
    for url in list(_candidates):
        if not store.eligible(url) or store.contains(url) or url in _declined:
            del _candidates[url]
    return max(_candidates.values(), key=lambda row: (row.get("likes") or 0, row.get("views") or 0), default=None)


def _review(candidate):
    url = candidate["url"]
    del _candidates[url]
    _declined[url] = time.monotonic()  # reviewed once, whatever the answer
    page = twitter_client.read_share_post(url)
    likes = page.get("likes") if page else None
    if (not page or page.get("has_video") is not True or not str(page.get("media_id", "")).isdigit()
            or x_urls.is_reply_like_tweet(page) or type(likes) is not int or likes < settings.get("VIDEO_SHARE_MIN_LIKES")
            or store.contains(url, page["media_id"])):
        return
    try:
        evidence = repost_review.inspect(page, share=True)
    except (AccessError, ValueError, TimeoutError) as exc:
        log.info("[VIDEO-SHARE] inspection failed for %s: %s", url, exc)
        return
    if not evidence:
        return
    verdict = evidence["verdict"]
    take = " ".join(str(verdict.get("take", "")).split())
    approved = (repost_review.valid(evidence, url, page["text"], page["media_id"]) and verdict.get("brand_fit") is True
                and repost_review.take_ok(take))
    log.info("[VIDEO-SHARE] %s: %s %r (%s)", "approved" if approved else "declined", url, take, str(verdict.get("reason", ""))[:160])
    if approved:
        _approved.append((url, take, page["media_id"], page["text"], time.monotonic()))


def run_video_share_cycle():
    if not settings.get("VIDEO_SHARE_ENABLED") or config.dry_run():
        return
    active_hours.require_active()
    now = time.monotonic()
    for url, at in list(_declined.items()):
        if now - at > 172800:
            del _declined[url]
    _approved[:] = [row for row in _approved if now - row[4] <= 10800 and store.eligible(row[0])
                    and not store.contains(row[0], row[2])]
    if _approved and not store.refusal():
        url, take, media_id, text, _ = _approved.pop(0)
        outcome = twitter_client.post_video_share(url, take, media_id, text)
        log.info("[VIDEO-SHARE] %s: %s %r", outcome.value, url, take)
        return
    # Prepare from half an hour before a window; keep at most three reviewed clips waiting.
    if store.refusal(preparing=True) or len(_approved) >= 3:
        return
    _discover()
    if candidate := _next():
        _review(candidate)
