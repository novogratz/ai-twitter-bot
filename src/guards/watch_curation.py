"""Scoped watched actions and reviewed Replies; permanent claims remain separate."""
from datetime import datetime, timedelta
import time

from ..core import account, settings
from ..x import x_urls
from . import active_hours, repost_store

_reviews = {}
FAST_MAX_AGE_SECONDS = 60


def fast():
    return settings.get("REPLY_CURATED_MODE") and settings.get("REPLY_BROAD_DISCOVERY")


def fresh(url):
    """Late work is discarded; a fast dispatch interval is not a delivery guarantee."""
    if not fast():
        return True
    age = x_urls.age(url, active_hours.now_local())
    return age is not None and timedelta(0) <= age < timedelta(seconds=FAST_MAX_AGE_SECONDS)


def eligible(url):
    return bool(repost_store.allowed_url(url))


def independent_actions(url=""):
    """The Account's explicit all-topic permission applies only to watched actions."""
    profile = account.current()
    return bool(profile.auto_engage_all_topics and profile.watched_reposts_independent
                and (eligible(url) if url else profile.auto_engage_handles))


def actions_fresh(url):
    """Independent likes/reposts keep their watch horizon; Replies still expire at 60s."""
    if not independent_actions(url):
        return fresh(url)
    age = x_urls.age(url, active_hours.now_local())
    return age is not None and timedelta(0) <= age <= timedelta(
        hours=settings.get("PRIORITY_WATCH_MAX_AGE_HOURS"))


def refusal(url=""):
    from . import action_guard
    if url and not eligible(url):
        return "only exact configured watched authors are enabled"
    if url and not actions_fresh(url):
        return ("watched source is outside its action freshness window" if independent_actions(url)
                else "watched source missed the first-minute submission window")
    now = active_hours.now_local()
    ledger = action_guard._ledger()
    used = {x_urls.status_id(target) for action in (action_guard.WATCH_REPOST, action_guard.RETWEET)
            for target in ledger.targets(action) if eligible(target) and ledger.count(action, now.date(), target)}
    times = []
    for sid, row in repost_store.entries().items():
        if isinstance(row, dict) and eligible(row["url"]):
            at = datetime.fromisoformat(row["ts"])
            times.append(at)
            if at.astimezone(now.tzinfo).date() >= now.date():
                used.add(sid)
    if len(used) >= settings.get("CURATED_WATCH_REPOSTS_PER_DAY"):
        return "watched-author repost cap reached including unresolved submissions"
    times += [at for action in (action_guard.WATCH_REPOST, action_guard.RETWEET)
              if (at := ledger.last_write(action))]
    gap = max(settings.get("CURATED_WATCH_REPOST_MIN_SECONDS"), settings.get("PRIORITY_REPOST_MIN_SECONDS"))
    if times and (now - max(times)).total_seconds() < gap:
        spacing = "six-hour" if gap == 21600 else f"{gap}-second"
        return f"watched-author reposts require {spacing} spacing"
    return ""


def remember(page, verdict, *, provider="", model=""):
    now = time.time()
    for url, row in list(_reviews.items()):
        if now - row["at"] > 1800:
            del _reviews[url]
    if len(_reviews) >= 80:
        del _reviews[min(_reviews, key=lambda key: _reviews[key]["at"])]
    _reviews[page["url"]] = dict(text=page["text"], media_id=page.get("media_id", ""), at=now, verdict=verdict,
                                has_video=page.get("has_video", False), likes=page.get("likes"), views=page.get("views"),
                                language=page.get("language", ""), provider=provider, model=model)


def reviewed(page):
    from . import reply_selection
    row = _reviews.get(page.get("url"), {})
    verdict = row.get("verdict", {})
    topic = (account.watched_topic_allowed(page.get("text", ""), url=page.get("url", ""))
             if fast() else account.matches_niche(page.get("text", "")))
    scope = (verdict.get("in_scope") is True and verdict.get("political") is False
             and verdict.get("unsafe_or_unclear") is False) if fast() else verdict.get("ai_related") is True
    return (eligible(page.get("url", "")) and topic and fresh(page.get("url", "")) and scope
            and (not row.get("has_video") or bool(row.get("media_id")))
            and row.get("text") == page.get("text") and row.get("media_id") == page.get("media_id", "")
            and 0 <= time.time() - row.get("at", 0) <= 1800
            and all(verdict.get(k) is True for k in ("approved", "useful", "supported"))
            and type(verdict.get("quality")) in (int, float) and 8 <= verdict["quality"] <= 10
            and (not fast() or not reply_selection.basic_refusal(
                page["url"], page["text"], source_language=row.get("language", ""))))


def selected(url):
    """Disposable approved source for the fast dispatchers; each write re-reads it."""
    row = _reviews.get(url, {})
    page = dict(url=url, text=row.get("text", ""), media_id=row.get("media_id", ""),
                likes=row.get("likes"), views=row.get("views"), reply=row.get("verdict", {}).get("reply", ""),
                language=row.get("language", ""), provider=row.get("provider", ""), model=row.get("model", ""))
    return page if reviewed(page) else {}
