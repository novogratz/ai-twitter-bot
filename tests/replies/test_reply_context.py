"""Current article grounding and varied reply style, without live network calls."""
from datetime import datetime

from src.replies import reply_generator as rg
from src.editorial import editorial_bot
from tests.helpers import TORONTO, clock


def test_current_sources_refresh_hourly_and_never_reuse_expired_facts(monkeypatch, unwalled):
    now = datetime(2026, 10, 8, 9, tzinfo=TORONTO)
    clock(monkeypatch, now)
    monkeypatch.setattr(rg, "_context_cache", {})
    calls = []
    sources = [dict(publisher="Trusted lab", published_at=now.isoformat(),
                    title="New model", url="https://openai.com/news/model", body="Verified model facts")]
    def collect(journal, *, now, news_only):
        calls.append((now, news_only))
        return sources
    monkeypatch.setattr(editorial_bot, "collect_sources", collect)
    context = unwalled["reply_context"]
    assert "Verified model facts" in context()
    assert "Verified model facts" in context()
    assert len(calls) == 1 and calls[0][1] is True
    sources.clear()
    clock(monkeypatch, now.replace(hour=14))
    assert "No verified current news" in context()
    assert "Verified model facts" not in context()
    assert len(calls) == 2


def test_context_fetch_starts_nothing_in_a_pause(monkeypatch, unwalled):
    import pytest
    from src.guards.active_hours import OutsideActiveHours
    clock(monkeypatch, datetime(2026, 10, 8, 12, tzinfo=TORONTO))
    monkeypatch.setattr(editorial_bot, "collect_sources", lambda *a, **k: pytest.fail("network during pause"))
    with pytest.raises(OutsideActiveHours):
        unwalled["reply_context"]()


def test_recent_shipped_replies_are_style_examples_not_facts(monkeypatch, tmp_path):
    import csv
    from src.core import config
    path = tmp_path / "engagement.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "type", "text"])
        writer.writerow(["t", "original", "Original text"])
        for n in range(12):
            writer.writerow(["t", "reply", f"Reply number {n}"])
    monkeypatch.setattr(config, "ENGAGEMENT_LOG_FILE", path)
    style = rg._recent_style()
    assert "Reply number 0\n" not in style
    assert "Reply number 2" in style and "Reply number 11" in style
    assert "Original text" not in style
    assert "style only" in style
