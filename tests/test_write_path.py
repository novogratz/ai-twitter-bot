"""Write-path defects from the architecture review (issue #101)."""
import json


def _stub_like_browser(monkeypatch, tmp_path):
    from src import like_bot

    monkeypatch.setattr(like_bot, "LIKE_BOT_STATE_FILE", str(tmp_path / "like_state.json"))
    monkeypatch.setattr(like_bot.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(like_bot, "_scroll_page", lambda: None)
    monkeypatch.setattr(like_bot, "close_front_tab", lambda: None)
    monkeypatch.setattr(like_bot.time, "sleep", lambda *_: None)
    requested = []

    def click(n):
        requested.append(n)
        return n

    monkeypatch.setattr(like_bot, "_click_likes_on_page", click)
    return requested


def test_live_strategy_cannot_raise_likes_per_cycle(monkeypatch, tmp_path):
    from src import config, like_bot

    strategy = tmp_path / "live_strategy.json"
    strategy.write_text(json.dumps({"caps": {"LIKE_BOT_PER_CYCLE": 500}}))
    monkeypatch.setattr(config, "_LIVE_STRATEGY_FILE", str(strategy))
    monkeypatch.setattr(like_bot, "LIKES_PER_CYCLE", 10)
    requested = _stub_like_browser(monkeypatch, tmp_path)

    like_bot.run_like_cycle()

    assert sum(requested) == 10


def _status_url(handle, minutes_ago):
    from datetime import datetime, timezone
    from src.reply_bot import _TWITTER_EPOCH

    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - minutes_ago * 60_000
    return f"https://x.com/{handle}/status/{(ms - _TWITTER_EPOCH) << 22}"


def test_mega_watch_skips_posts_older_than_max_age(monkeypatch):
    from src import mega_watch_bot as mw

    fresh = _status_url("bigai", 1)
    stale = _status_url("bigai", 30)
    monkeypatch.setattr(mw, "_watch_pool", lambda: ["bigai"])
    monkeypatch.setattr(mw, "load_replied", lambda: set())
    monkeypatch.setattr(mw, "scrape_profile_tweets", lambda *a, **k: [
        {"url": stale, "author": "bigai", "text": "GPU clusters are the new power plants"},
        {"url": fresh, "author": "bigai", "text": "GPU clusters are the new power plants"},
    ])
    monkeypatch.setattr(mw, "_is_reply_like_tweet", lambda *a, **k: False)
    monkeypatch.setattr(mw, "_is_on_niche", lambda text: True)
    monkeypatch.setattr(mw, "_generate_single_reply",
                        lambda **k: "Power is the real bottleneck for these clusters.")
    monkeypatch.setattr(mw, "humanize", lambda text: text)
    monkeypatch.setattr(mw, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(mw.time, "sleep", lambda *_: None)
    replied_to = []
    monkeypatch.setattr(mw, "reply_to_tweet", lambda url, text: replied_to.append(url) or True)

    mw.run_mega_watch_cycle()

    assert replied_to == [fresh]


def _stop_requested(monkeypatch):
    import threading
    from src import active_hours

    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(active_hours, "_STOP", stop)


def test_awake_job_starts_nothing_after_stop(monkeypatch):
    from src.active_hours import awake_job

    ran = []
    job = awake_job(lambda: ran.append(True))
    _stop_requested(monkeypatch)

    assert job() is None
    assert ran == []


def test_can_post_refuses_after_stop(monkeypatch):
    from src import action_guard

    assert action_guard.can_post(action_guard.REPLY)[0] is True
    _stop_requested(monkeypatch)

    ok, why = action_guard.can_post(action_guard.REPLY)
    assert not ok and "stop" in why


def test_is_active_ignores_stop_for_the_scheduler_loop(monkeypatch):
    from src import active_hours

    _stop_requested(monkeypatch)

    assert active_hours.is_active() is True
    assert active_hours.may_act() is False


def test_like_clicks_refused_after_stop(monkeypatch):
    import pytest
    from src import like_bot
    from src.active_hours import OutsideActiveHours

    calls = []
    monkeypatch.setattr(like_bot.subprocess, "run", lambda *a, **k: calls.append(a))
    _stop_requested(monkeypatch)

    with pytest.raises(OutsideActiveHours):
        like_bot._click_likes_on_page(5)
    assert calls == []


def test_like_count_survives_a_stop_between_batches(monkeypatch, tmp_path):
    from src import like_bot
    from src.active_hours import OutsideActiveHours
    import pytest

    _stub_like_browser(monkeypatch, tmp_path)
    monkeypatch.setattr(like_bot, "LIKES_PER_CYCLE", 10)
    batches = iter([5, OutsideActiveHours("stop")])

    def click(n):
        outcome = next(batches)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(like_bot, "_click_likes_on_page", click)

    with pytest.raises(OutsideActiveHours):
        like_bot.run_like_cycle()
    assert like_bot._load_daily_state()["count"] == 5


def _dry_run_reply_path(monkeypatch):
    from src import action_guard

    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")


def test_human_typo_text_is_the_validated_text(monkeypatch):
    from src import content_guard, humanizer, twitter_client

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    validated = []
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000101"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is True
    assert validated and validated[-1].endswith("(typo)")


def test_refused_typo_text_leaves_the_tweet_fresh(monkeypatch):
    from src import content_guard, humanizer, twitter_client
    from src.reply_bot import load_replied

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": (not text.endswith("(typo)"), "typo refused"))

    url = "https://x.com/typofriend/status/2063500000000000102"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is False
    assert url not in load_replied()


def test_dry_run_is_read_at_call_time(monkeypatch):
    from src import action_guard, config, twitter_client

    assert not hasattr(config, "DRY_RUN"), "a frozen module constant must not come back"
    monkeypatch.setenv("DRY_RUN", "0")
    assert config.dry_run() is False
    monkeypatch.setenv("DRY_RUN", "1")
    assert config.dry_run() is True

    # Set after every module is imported: the chokepoint must still see it
    # and never reach Safari (conftest fails the test if it does).
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(k))
    assert twitter_client.post_tweet("A fresh original about inference costs.") is True
    assert recorded == [{"dry_run": True}]
