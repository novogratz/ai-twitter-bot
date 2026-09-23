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
