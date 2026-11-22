"""Review funny AI videos from existing discoveries without holding Reply work."""
from ..core import config, settings
from ..core.logger import log
from ..guards import active_hours, meme_repost_store as store
from ..video.security import AccessError
from ..x import twitter_client
from ..video import repost_review as video_repost_review


def run_meme_repost_cycle():
    if not settings.get("MEME_REPOST_ENABLED") or config.dry_run():
        return
    active_hours.require_active()
    if store.refusal():
        return
    ready = next((r for r in store.entries().values() if store.approved(r["url"])
                  and not store.refusal(r["url"])), None)
    if ready:
        twitter_client.repost_meme(ready["url"])
        return
    candidate = store.next_candidate()
    if not candidate:
        return
    url = candidate["url"]
    page = twitter_client.read_meme_post(url)
    if not page:
        store.defer(url)
        return
    if not store.qualifies(page):
        store.review(url, page.get("text", ""), False, "not an eligible standalone AI video")
        return
    try:
        evidence = video_repost_review.inspect(page)
    except (AccessError, ValueError, TimeoutError) as exc:
        store.defer(url)
        log.info("[VIDEO-REPOST] inspection deferred for %s: %s", url, exc)
        return
    if not evidence:
        return
    verdict = evidence["verdict"]
    approved = video_repost_review.valid(evidence, url, page["text"], page.get("media_id"))
    store.review(url, page["text"], approved, str(verdict.get("reason", "")),
                 humor_score=verdict.get("humor_score", 0), video_evidence=evidence)
    log.info("[VIDEO-REPOST] %s: %s (%s)", "approved" if approved else "declined", url, verdict.get("reason", ""))
    if approved:
        twitter_client.repost_meme(url)
