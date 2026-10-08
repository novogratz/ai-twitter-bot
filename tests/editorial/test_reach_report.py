"""src/editorial/reach_report: reach accounting."""
import os
from datetime import datetime

import pytest

from src.core import config
from tests.helpers import TORONTO, clock, scheduled_job


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


def test_a_failed_measurement_leaves_the_safari_health_file_alone(monkeypatch, caplog):
    """Issue #236: the reach report stays out of the Safari failure counter;
    its failure is logged with its traceback."""
    from src.core import health
    from src.editorial import reach_report
    from src.x import scraper
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    monkeypatch.setattr(health, "_restart_safari", lambda: pytest.fail("Safari restarted"))

    class Journal:
        def published(self):
            return [dict(ts=now.isoformat(), text="A useful AI workflow", slot="08:00")]
    monkeypatch.setattr(reach_report, "FileJournal", Journal)

    def blank_profile(*a, **k):
        raise RuntimeError("profile never loaded")
    monkeypatch.setattr(scraper, "scrape_profile_tweets", blank_profile)
    job = scheduled_job("reach_report_job")
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        job()

    assert not os.path.exists(health.HEALTH.path)
    assert not os.path.exists(reach_report.REPORT.path)
    assert "RuntimeError: profile never loaded" in caplog.text
    assert any(r.levelname == "ERROR" for r in caplog.records)
