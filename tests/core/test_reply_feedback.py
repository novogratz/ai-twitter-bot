import csv
from datetime import datetime, timedelta

from src.core import account, config, engagement_log, reply_feedback as feedback
from src.guards import active_hours
from src.x import x_urls
from tests.helpers import TORONTO, clock


NOW = datetime(2026, 10, 26, 12, tzinfo=TORONTO)


def url(at=NOW, handle="builder", extra=0):
    sid = ((int(at.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22) + extra
    return f"https://x.com/{handle}/status/{sid}"


def test_sample_does_not_depend_on_handle_url_suffix_or_counter():
    parent = url()
    assert feedback.sampled(parent) == feedback.sampled(parent.replace("builder", "other") + "?s=20")
    selected = sum(feedback.sampled(url(extra=i)) for i in range(1000))
    assert 150 < selected < 250


def test_only_own_urls_join_the_receipt_and_sample(monkeypatch):
    monkeypatch.setattr(feedback, "sampled", lambda _: True)
    parent, own = url(NOW - timedelta(minutes=20)), url(handle=account.current().handle)
    feedback.record_confirmed(parent, "A video workflow worth trying.", url(handle="stranger"), NOW)
    assert feedback.publication_url(parent) == ""
    assert feedback.FEEDBACK.read()[x_urls.status_id(parent)]["url"] == ""
    other = url(NOW - timedelta(minutes=21))
    feedback.record_confirmed(other, "A video workflow worth trying.", own, NOW)
    feedback.annotate(other, source="SEARCH-FRESH/video", topic="video", provider="codex", model="test")
    saved = feedback.FEEDBACK.read()[x_urls.status_id(other)]
    assert saved["url"] == own and saved["source"] == "SEARCH-FRESH/video" and saved["topic"] == "video"
    assert saved["parent_age_minutes"] == 21


def test_due_windows_skip_missing_urls_old_samples_and_back_off():
    def row(hours, **kw):
        return dict(url=url(), sent_at=(NOW - timedelta(hours=hours)).isoformat(), observations={}, **kw)
    rows = {"early": row(.5), "first": row(1.5), "day": row(25), "old": row(40),
            "wait": row(1.5, last_attempt=(NOW - timedelta(minutes=2)).isoformat()),
            "missing": {**row(1.5), "url": ""}}
    assert {(sid, window) for _, sid, window, _ in feedback.due(rows, NOW)} == {("first", "1h"), ("day", "24h")}


def test_unknown_counters_are_not_zero_or_another_posts_metrics():
    own = url(handle=account.current().handle)
    row = dict(url=own, sent_at=(NOW - timedelta(hours=1)).isoformat(), observations={})
    feedback.FEEDBACK.write({"1": row})
    feedback._save_observation("1", "1h", {"url": url(handle="other"), "likes": 50, "views": 100}, NOW)
    assert feedback.FEEDBACK.read()["1"]["observations"] == {}
    feedback._save_observation("1", "1h", {"url": own, "likes": None, "views": None}, NOW)
    assert feedback.FEEDBACK.read()["1"]["observations"] == {}
    feedback._save_observation("1", "1h", {"url": own, "likes": 0, "views": None}, NOW)
    observation = feedback.FEEDBACK.read()["1"]["observations"]["1h"]
    assert observation["likes"] == 0 and observation["views"] is None
    assert observation["likes_per_1000_views"] is None


def test_report_uses_weighted_rates_and_never_attributes_followers(settings_override):
    settings_override(REPLY_DAILY_TARGET_MIN=700, REPLY_DAILY_TARGET_MAX=1400, HOURLY_BREAK_MINUTES=10)
    base = dict(sent_at=(NOW - timedelta(hours=2)).isoformat(), parent_age_minutes=20,
                source="SEARCH-FRESH/video", topic="video", hour=10, length="brief", url=url())
    rows = {"a": dict(base, observations={"1h": {"likes": 2, "views": 100}}),
            "b": dict(base, observations={"1h": {"likes": 3, "views": 900}}),
            "c": dict(base, observations={})}
    report = feedback.summarize(rows, [{"at": NOW, "source": "search", "url": ""}],
                                [{"ts": (NOW - timedelta(hours=1)).isoformat(), "count": 100},
                                 {"ts": NOW.isoformat(), "count": 103}], NOW)
    assert report["active_hours"] == 19.5
    assert report["required_replies_per_active_hour"] == [35.9, 71.8]
    assert report["cohorts"][0]["likes_per_1000_views"] == 5
    assert report["cohorts"][0]["enough_to_compare"] is False
    assert report["observed"] == {"1h": 2, "24h": 0}
    assert report["eligible"] == {"1h": 3, "24h": 0}
    assert report["receipts_7d"] == 0
    assert report["follower_change_between_today_samples"] == 3
    assert report["followers_attributed_to_replies"] is None


def test_legacy_csv_and_multiline_replies_feed_memory_and_history():
    with open(config.ENGAGEMENT_LOG_FILE, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "type", "text", "target_url"])
        writer.writerow([NOW.isoformat(), "reply", "Specific video point.\nSecond line.", url(), "LATEST", "", "", "codex", "model", ""])
        writer.writerow([NOW.isoformat(), "like", "Not a reply", url()])
    assert engagement_log.recent_replies() == ["Specific video point.\nSecond line."]
    assert len(feedback._history(NOW)) == 1
    engagement_log.log_reply(url(extra=1), "Another specific point.")
    assert engagement_log.recent_replies()[-1] == "Another specific point."
    assert len(engagement_log.recent_replies()) == 2


def test_report_stays_bounded_and_runs_no_browser_overnight(monkeypatch):
    from src.x import reply_metrics
    clock(monkeypatch, NOW)
    rows = {str(i): dict(url=url(handle=account.current().handle, extra=i),
                        sent_at=(NOW - timedelta(hours=1)).isoformat(), observations={}) for i in range(20)}
    feedback.FEEDBACK.write(rows)
    reads = []
    monkeypatch.setattr(reply_metrics, "observe", lambda u: reads.append(u) or {"url": u, "likes": 1, "views": 10})
    report = feedback.run_reply_report()
    assert len(reads) == 12 and report["observed"]["1h"] == 12
    clock(monkeypatch, NOW.replace(hour=2))
    active_hours.awake_job(feedback.run_reply_report)()
    assert len(reads) == 12
