from datetime import datetime, timezone
import json

import pytest

from src.news import publisher, startup
from src.news.store import Store


@pytest.fixture
def news_startup(tmp_path, settings_override):
    settings_override(NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True, DRY_RUN=False)
    return Store(tmp_path / "news.sqlite3")


def test_unfinished_startup_survives_restarts_without_new_delivery(news_startup):
    first = startup.request(news_startup, "boot-a", 1000)
    assert startup.request(news_startup, "boot-b", 2000) == first
    assert first["state"] == "pending"
    assert not news_startup.rows("SELECT * FROM outbox")


@pytest.mark.parametrize("setting", ["NEWS_ENABLED", "NEWS_AUTO_PUBLISH", "DRY_RUN"])
def test_disabled_or_dry_start_cannot_record_publication_intent(news_startup, settings_override, setting):
    settings_override(**{setting: setting == "DRY_RUN"})
    assert startup.request(news_startup, "boot", 1000) is None
    assert news_startup.meta(startup.KEY) is None


def test_only_confirmed_receipt_fulfills_startup(news_startup):
    startup.request(news_startup, "boot-a", 1000)
    news_startup.execute("INSERT INTO outbox(id,story,payload,state) VALUES('story','story','{}','pending')")
    publisher.confirmed(news_startup, "story", "https://x.com/owner/status/123", 1010)
    assert news_startup.meta(startup.KEY)["state"] == "pending"
    news_startup.execute("UPDATE outbox SET state='submitting'")
    publisher.confirmed(news_startup, "story", "https://x.com/owner/status/123", 1010)
    saved = news_startup.meta(startup.KEY)
    assert saved["state"] == "posted" and saved["outbox_id"] == "story"
    assert news_startup.meta(startup.KEY + ":boot-a") == saved
    assert startup.request(news_startup, "boot-a", 1020) == saved
    assert startup.request(news_startup, "boot-b", 1030)["state"] == "pending"
    assert news_startup.meta(startup.KEY + ":boot-a") == saved


def test_startup_tries_existing_outbox_before_hourly_discovery(settings_override):
    from main import build_scheduler
    settings_override(NEWS_ENABLED=True, VIDEO_ENABLED=True)
    scheduler = build_scheduler(startup_publications=True)
    delivery, discovery = scheduler.get_job("news_delivery_job"), scheduler.get_job("news_job")
    assert delivery.next_run_time < discovery.next_run_time
    assert delivery.executor == discovery.executor == "news"
    assert delivery.trigger.interval.total_seconds() == 60
    assert scheduler.get_job("video_health_job").next_run_time < discovery.next_run_time
    assert not build_scheduler(reply_only=True, startup_publications=True).get_job("news_delivery_job")


def test_waiting_startup_main_keeps_worker_free_for_delivery(news_startup):
    from types import SimpleNamespace
    from src.news import pipeline
    from src.video.security import Deferred

    class DeferredDelivery:
        def send(self, ident, payload):
            raise Deferred("protected video window")

    class NoResearch:
        def __getattr__(self, name):
            raise AssertionError("Startup must retry the approved main story before researching")

    startup.request(news_startup, "boot", 1000)
    news_startup.execute("""INSERT INTO outbox(id,story,payload,state,due,expires)
        VALUES('story','story','{"role":"main"}','pending',1000,2000)""")
    result = pipeline.run(SimpleNamespace(delivery_attempts=3), store=news_startup,
                          delivery=DeferredDelivery(), http=NoResearch(), model=NoResearch(),
                          now=1010, import_history=False)
    assert result == []
    row = news_startup.rows("SELECT state,attempts,due FROM outbox")[0]
    assert row == {"state": "pending", "attempts": 0, "due": 1070}
    assert news_startup.rows("SELECT status,finished FROM runs")[0] == {
        "status": "startup_delivery_wait", "finished": 1010}
    assert news_startup.meta("last_complete") is None
