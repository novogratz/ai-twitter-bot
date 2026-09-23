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
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "10")
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


def test_like_caps_are_read_at_call_time(monkeypatch, tmp_path):
    from src import like_bot

    requested = _stub_like_browser(monkeypatch, tmp_path)
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "6")
    monkeypatch.setenv("LIKE_BOT_DAILY_CAP", "4")

    like_bot.run_like_cycle()

    assert sum(requested) == 4


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
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "10")
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


def test_language_check_judges_the_text_before_the_typo(monkeypatch):
    from src import content_guard, direct_reply, humanizer, twitter_client

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setenv("FR_FORCED_REPLY_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    judged, validated = [], []
    monkeypatch.setattr(direct_reply, "_looks_english", lambda text: judged.append(text) or False)
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000103"
    assert twitter_client.reply_to_tweet(url, "Le calcul est le vrai fossé, pas le modèle.") is True
    assert judged and not judged[-1].endswith("(typo)")
    assert validated[-1].endswith("(typo)")

def test_refused_typo_text_leaves_the_tweet_fresh(monkeypatch):
    from src import content_guard, humanizer, twitter_client
    from src.replied_store import load_replied

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


def test_dry_run_stops_writes_outside_the_ledger_chokepoints(monkeypatch, tmp_path):
    """like_job, notify_job, pin_job and the self-reply clicked in Safari
    whatever DRY_RUN said. conftest fails the test on webbrowser.open or
    _run_applescript; direct osascript calls are walled off here."""
    from src import like_bot, twitter_client

    def no_osascript(*a, **k):
        raise AssertionError("dry run reached osascript")

    monkeypatch.setattr(twitter_client.subprocess, "run", no_osascript)
    monkeypatch.setattr(like_bot.subprocess, "run", no_osascript)
    monkeypatch.setattr(like_bot, "LIKE_BOT_STATE_FILE", str(tmp_path / "like_state.json"))
    # reply_to_own_latest swallows every exception, so count browser opens
    # instead of relying on conftest's AssertionError.
    opened = []
    monkeypatch.setattr(twitter_client.webbrowser, "open", lambda *a, **k: opened.append(a))
    monkeypatch.setenv("DRY_RUN", "1")

    like_bot.run_like_cycle()
    twitter_client.like_own_tweet_replies()
    assert twitter_client.pin_own_tweet("https://x.com/TheAIShrink/status/2063500000000000103") is False
    assert twitter_client.reply_to_own_latest("Source: https://example.com/report") is False
    assert opened == []
    assert not (tmp_path / "like_state.json").exists()


def _live_browser(monkeypatch, failing_step=None):
    """Live (non-dry) write path with a scripted AppleScript outcome.

    failing_step: "reply_key", "paste" or "submit" makes that step fail;
    "stop_before_submit", "stop_at_submit" and "stop_after_submit" request a
    stop at that point.
    """
    from src import action_guard, twitter_client as tc
    from src.active_hours import OutsideActiveHours

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(action_guard, "can_debate_turn", lambda *a, **k: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))

    def run_applescript(script, *a, **k):
        if 'keystroke "r"' in script:
            if failing_step == "stop_before_submit":
                raise OutsideActiveHours("stop")
            return failing_step != "reply_key"
        if "keystroke return using command down" in script:
            return failing_step != "submit"
        return True

    monkeypatch.setattr(tc, "_run_applescript", run_applescript)
    def paste(text):
        if failing_step == "stop_at_submit":
            _stop_requested(monkeypatch)
        return failing_step != "paste"

    monkeypatch.setattr(tc, "_paste_text", paste)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a, **k: None)
    def close_front_tab():
        if failing_step == "stop_after_submit":
            raise OutsideActiveHours("stop")

    monkeypatch.setattr(tc, "close_front_tab", close_front_tab)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    return recorded


REPLY = "Batching is where inference margins are won or lost."


def test_reply_ships_and_records_when_every_step_runs(monkeypatch):
    from src import twitter_client as tc
    from src.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    url = "https://x.com/someone/status/2063500000000000110"

    assert tc.reply_to_tweet(url, REPLY) is True
    assert len(recorded) == 1
    assert url in load_replied()


def test_reply_failing_before_submit_records_nothing_and_leaves_tweet_fresh(monkeypatch):
    from src import twitter_client as tc
    from src.replied_store import load_replied, save_replied

    other = "https://x.com/else/status/2063500000000000119"
    save_replied({other})
    for n, step in enumerate(("reply_key", "paste")):
        for debate_turn in (False, True):
            recorded = _live_browser(monkeypatch, failing_step=step)
            url = f"https://x.com/someone/status/20635000000000001{n}{int(debate_turn)}"

            assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is False, step
            assert recorded == [], step
            assert url not in load_replied(), step
    assert other in load_replied()


def test_reply_failing_at_submit_records_nothing_but_stays_marked(monkeypatch):
    from src import twitter_client as tc
    from src.replied_store import load_replied

    for n, debate_turn in enumerate((False, True)):
        recorded = _live_browser(monkeypatch, failing_step="submit")
        url = f"https://x.com/someone/status/206350000000000013{n}"

        assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is False
        assert recorded == []
        assert url in load_replied()


def test_debate_race_loser_keeps_its_claim(monkeypatch):
    """The in-lock debate re-check refuses after the claim: that tweet stays
    taken, only earlier refusals leave it fresh."""
    from src import action_guard, twitter_client as tc
    from src.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    answers = iter([(True, ""), (False, "turn cap reached")])
    monkeypatch.setattr(action_guard, "can_debate_turn", lambda *a, **k: next(answers))
    url = "https://x.com/someone/status/2063500000000000160"

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is False
    assert recorded == []
    assert url in load_replied()

def test_stop_before_submit_leaves_tweet_fresh_after_submit_keeps_it(monkeypatch):
    import pytest
    from src import twitter_client as tc
    from src.active_hours import OutsideActiveHours
    from src.replied_store import load_replied

    _live_browser(monkeypatch, failing_step="stop_before_submit")
    before = "https://x.com/someone/status/2063500000000000140"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(before, REPLY)
    assert before not in load_replied()

    _live_browser(monkeypatch, failing_step="stop_at_submit")
    at = "https://x.com/someone/status/2063500000000000142"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(at, REPLY)
    assert at not in load_replied()

    import threading
    from src import active_hours
    monkeypatch.setattr(active_hours, "_STOP", threading.Event())
    recorded = _live_browser(monkeypatch, failing_step="stop_after_submit")
    after = "https://x.com/someone/status/2063500000000000141"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(after, REPLY)
    assert after in load_replied()
    assert len(recorded) == 1


def test_release_drops_only_the_claimed_tweet(monkeypatch):
    from src import config, replied_store

    keep, drop = "2063500000000000150", "2063500000000000151"
    with open(config.REPLIED_FILE, "w") as f:
        json.dump({"urls": [f"https://x.com/a/status/{keep}", drop]}, f)

    replied_store.release(f"https://x.com/b/status/{drop}")

    assert json.load(open(config.REPLIED_FILE)) == [f"https://x.com/a/status/{keep}"]


def test_image_post_that_fails_records_nothing(monkeypatch, tmp_path):
    from src import content_guard, twitter_client as tc

    image = tmp_path / "chart.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(content_guard, "is_duplicate", lambda *a, **k: False)
    noted = []
    monkeypatch.setattr(content_guard, "note_posted", noted.append)
    for step in ("paste", "submit"):
        recorded = _live_browser(monkeypatch, failing_step=step)
        assert tc.post_tweet("Inference is getting cheaper faster than training.",
                             image_path=str(image)) is False, step
        assert recorded == [] and noted == [], step

    recorded = _live_browser(monkeypatch)
    assert tc.post_tweet("Inference is getting cheaper faster than training.",
                         image_path=str(image)) is True
    assert len(recorded) == 1
