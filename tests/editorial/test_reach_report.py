"""src/editorial/reach_report: reach accounting."""
from datetime import datetime

from src.core import config
from tests.helpers import TORONTO


def test_reach_reports_missing_coverage_without_inventing_homepage_views():
    from src.editorial.reach_report import summarize
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    posts = [dict(ts=now.isoformat(), text="A useful AI workflow", slot="08:00"),
             dict(ts=now.isoformat(), text="Another AI idea", slot="11:30")]
    tweet = dict(url=f"https://x.com/{config.BOT_HANDLE}/status/1", text=posts[0]["text"], views=250, likes=5)
    report = summarize(posts, [tweet, tweet], now)
    assert report["views"] == 250 and report["target_views"] == 500_000
    assert report["originals_observed"] == 1 and not report["coverage_complete"]
    assert report["homepage_views"] is None
