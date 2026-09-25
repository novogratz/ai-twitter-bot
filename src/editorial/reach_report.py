"""Observed reach of editorial originals, with a visible 500k-view target."""
from datetime import timedelta
from pathlib import Path

from ..core import account, config
from ..guards.active_hours import now_local, require_active
from .editorial_bot import _read_state, _stamp
from ..core.logger import log
from ..core.state_store import DISPOSABLE, StateFile, StatePath

# Disposable: rebuilt from the profile every hour.
REPORT = StateFile("editorial_reach.json", {}, DISPOSABLE)
REPORT_MARKDOWN = StatePath("editorial_reach.md")
TARGET_VIEWS = 500_000


def summarize(published, scraped, now=None):
    now = now or now_local()
    originals = [p for p in published if (stamp := _stamp(p.get("ts", "")))
                 and now - timedelta(days=7) <= stamp <= now]
    observed = []
    for post in originals:
        prefix = " ".join(post["text"].split())[:100]
        matches = [t for t in scraped
                   if not t.get("is_reply")
                   and f"x.com/{config.BOT_HANDLE.lower()}/status/" in (t.get("url") or "").lower()
                   and " ".join((t.get("text") or "").split()).startswith(prefix)]
        if matches:
            tweet = max(matches, key=lambda t: int(t.get("views") or 0))
            observed.append(dict(text=post["text"], slot=post["slot"], url=tweet["url"],
                                 views=int(tweet.get("views") or 0), likes=int(tweet.get("likes") or 0)))
    return dict(as_of=now.isoformat(), target_views=TARGET_VIEWS,
                metric="Observed lifetime views of originals published in the last 7 days",
                views=sum(p["views"] for p in observed),
                originals_published=len(originals), originals_observed=len(observed),
                coverage_complete=len(observed) == len(originals),
                # X's public counters do not reveal home-timeline attribution.
                homepage_views=None,
                top_posts=sorted(observed, key=lambda p: p["views"], reverse=True)[:5])


def safe_run_reach_report():
    try:
        require_active()
        from ..x.scraper import scrape_profile_tweets
        published = _read_state().get("published", [])
        tweets = scrape_profile_tweets(config.BOT_HANDLE, max_tweets=60) if published else []
        report = summarize(published, tweets)
        REPORT.write(report)
        Path(REPORT_MARKDOWN).write_text(
            f"# {account.current().domain} original-post reach\n\nUpdated: {report['as_of']}\n\n"
            f"**{report['views']:,} observed views / {TARGET_VIEWS:,} target**\n\n"
            f"{report['metric']}. Coverage: {report['originals_observed']} of "
            f"{report['originals_published']} originals. Missing posts are unknown.\n\n"
            "These are post-view counters, not unique people or home-timeline analytics. "
            "The target is aspirational and does not raise the publishing cap.\n\n"
            + "\n".join(f"- {p['views']:,} views, {p['likes']} likes — [{p['text']}]({p['url']})"
                        for p in report["top_posts"])
        )
        log.info("[REACH] %s/%s observed original-post views; coverage %s/%s.",
                 report["views"], TARGET_VIEWS, report["originals_observed"], report["originals_published"])
        return report
    except Exception as exc:
        log.info("[REACH] Measurement unavailable: %s", exc)
        return None
