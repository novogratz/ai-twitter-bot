"""Write-path defects from the architecture review (issue #101)."""
import json


def _stub_like_browser(monkeypatch, tmp_path):
    from src.account import like_bot

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
    from src.core import config
    from src.account import like_bot

    strategy = tmp_path / "live_strategy.json"
    strategy.write_text(json.dumps({"caps": {"LIKE_BOT_PER_CYCLE": 500}}))
    monkeypatch.setattr(config, "_LIVE_STRATEGY_FILE", str(strategy))
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "10")
    requested = _stub_like_browser(monkeypatch, tmp_path)

    like_bot.run_like_cycle()

    assert sum(requested) == 10


def _status_url(handle, minutes_ago):
    from datetime import datetime, timezone
    from src.replies.reply_bot import _TWITTER_EPOCH

    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - minutes_ago * 60_000
    return f"https://x.com/{handle}/status/{(ms - _TWITTER_EPOCH) << 22}"


def test_mega_watch_skips_posts_older_than_max_age(monkeypatch):
    from src.replies import mega_watch_bot as mw

    fresh = _status_url("bigai", 1)
    stale = _status_url("bigai", 30)
    monkeypatch.setattr(mw, "_watch_pool", lambda: ["bigai"])
    monkeypatch.setattr(mw, "scrape_profile_tweets", lambda *a, **k: [
        {"url": stale, "author": "bigai", "text": "GPU clusters are the new power plants"},
        {"url": fresh, "author": "bigai", "text": "GPU clusters are the new power plants"},
    ])
    monkeypatch.setattr(mw.x_urls, "is_reply_like_tweet", lambda *a, **k: False)
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
    from src.guards import active_hours

    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(active_hours, "_STOP", stop)


def test_awake_job_starts_nothing_after_stop(monkeypatch):
    from src.guards.active_hours import awake_job

    ran = []
    job = awake_job(lambda: ran.append(True))
    _stop_requested(monkeypatch)

    assert job() is None
    assert ran == []


def test_can_post_refuses_after_stop(monkeypatch):
    from src.guards import action_guard

    assert action_guard.can_post(action_guard.REPLY)[0] is True
    _stop_requested(monkeypatch)

    ok, why = action_guard.can_post(action_guard.REPLY)
    assert not ok and "stop" in why


def test_is_active_ignores_stop_for_the_scheduler_loop(monkeypatch):
    from src.guards import active_hours

    _stop_requested(monkeypatch)

    assert active_hours.is_active() is True
    assert active_hours.may_act() is False


def test_like_caps_are_read_at_call_time(monkeypatch, tmp_path):
    from src.account import like_bot

    requested = _stub_like_browser(monkeypatch, tmp_path)
    monkeypatch.setenv("LIKE_BOT_PER_CYCLE", "6")
    monkeypatch.setenv("LIKE_BOT_DAILY_CAP", "4")

    like_bot.run_like_cycle()

    assert sum(requested) == 4


def test_like_clicks_refused_after_stop(monkeypatch):
    import pytest
    from src.account import like_bot
    from src.guards.active_hours import OutsideActiveHours

    calls = []
    monkeypatch.setattr(like_bot.subprocess, "run", lambda *a, **k: calls.append(a))
    _stop_requested(monkeypatch)

    with pytest.raises(OutsideActiveHours):
        like_bot._click_likes_on_page(5)
    assert calls == []


def test_like_count_survives_a_stop_between_batches(monkeypatch, tmp_path):
    from src.account import like_bot
    from src.guards.active_hours import OutsideActiveHours
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
    from src.guards import action_guard

    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")


def test_human_typo_text_is_the_validated_text(monkeypatch):
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    validated = []
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000101"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is twitter_client.DRY_RUN_RECORDED
    assert validated and validated[-1].endswith("(typo)")


def test_language_check_judges_the_text_before_the_typo(monkeypatch):
    from src.guards import content_guard
    from src.core import reply_language
    from src.core import humanizer
    from src.x import twitter_client

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setenv("FR_FORCED_REPLY_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    judged, validated = [], []
    monkeypatch.setattr(reply_language, "looks_english", lambda text: judged.append(text) or False)
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000103"
    assert twitter_client.reply_to_tweet(url, "Le calcul est le vrai fossé, pas le modèle.") is twitter_client.DRY_RUN_RECORDED
    assert judged and not judged[-1].endswith("(typo)")
    assert validated[-1].endswith("(typo)")

def test_refused_typo_text_leaves_the_tweet_fresh(monkeypatch):
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client
    from src.guards.replied_store import load_replied

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": (not text.endswith("(typo)"), "typo refused"))

    url = "https://x.com/typofriend/status/2063500000000000102"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is False
    assert url not in load_replied()


def test_dry_run_is_read_at_call_time(monkeypatch):
    from src.guards import action_guard
    from src.core import config
    from src.x import twitter_client

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
    assert twitter_client.post_tweet("A fresh original about inference costs.") is twitter_client.DRY_RUN_RECORDED
    assert recorded == [{"dry_run": True}]


def test_dry_run_stops_writes_outside_the_ledger_chokepoints(monkeypatch, tmp_path):
    """like_job, notify_job and pin_job clicked in Safari
    whatever DRY_RUN said. conftest fails the test on webbrowser.open or
    _run_applescript; direct osascript calls are walled off here."""
    from src.account import like_bot
    from src.x import twitter_client

    def no_osascript(*a, **k):
        raise AssertionError("dry run reached osascript")

    monkeypatch.setattr(twitter_client.subprocess, "run", no_osascript)
    monkeypatch.setattr(like_bot.subprocess, "run", no_osascript)
    monkeypatch.setattr(like_bot, "LIKE_BOT_STATE_FILE", str(tmp_path / "like_state.json"))
    opened = []
    monkeypatch.setattr(twitter_client.webbrowser, "open", lambda *a, **k: opened.append(a))
    monkeypatch.setenv("DRY_RUN", "1")

    like_bot.run_like_cycle()
    twitter_client.like_own_tweet_replies()
    assert twitter_client.pin_own_tweet("https://x.com/TheAIShrink/status/2063500000000000103") is False
    assert opened == []
    assert not (tmp_path / "like_state.json").exists()


def _live_browser(monkeypatch, failing_step=None):
    """Live (non-dry) write path with a scripted AppleScript outcome.

    failing_step: "reply_key", "paste" or "submit" makes that step fail;
    "stop_before_submit", "stop_at_submit" and "stop_after_submit" request a
    stop at that point.
    """
    from src.guards import action_guard
    from src.x import twitter_client as tc
    from src.guards.active_hours import OutsideActiveHours

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
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    url = "https://x.com/someone/status/2063500000000000110"

    assert tc.reply_to_tweet(url, REPLY) is True
    assert len(recorded) == 1
    assert url in load_replied()


def test_reply_failing_before_submit_records_nothing_and_leaves_tweet_fresh(monkeypatch):
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied, save_replied

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
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    for n, debate_turn in enumerate((False, True)):
        recorded = _live_browser(monkeypatch, failing_step="submit")
        url = f"https://x.com/someone/status/206350000000000013{n}"

        assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is False
        assert recorded == []
        assert url in load_replied()


def test_debate_race_loser_leaves_the_tweet_fresh(monkeypatch):
    """Another thread takes the Engager's last turn while this one waits for
    the browser: admission, judged under the lock, refuses before the claim."""
    from src.guards import action_guard
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    lock_held = []
    monkeypatch.setattr(action_guard, "can_debate_turn",
                        lambda *a, **k: (False, "turn cap reached") if lock_held else (True, ""))

    class ContendedLock:
        def __enter__(self):
            lock_held.append(True)  # the other thread shipped the last turn meanwhile

        def __exit__(self, *exc):
            lock_held.clear()

    monkeypatch.setattr(tc, "_safari_lock", ContendedLock())
    url = "https://x.com/someone/status/2063500000000000160"

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is False
    assert recorded == []
    assert url not in load_replied()


def test_live_reply_pastes_the_validated_text(monkeypatch):
    """The text in the composer is the text admission validated, typo and
    dash cleanup included, never the raw draft."""
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client as tc

    _live_browser(monkeypatch)
    pasted, validated = [], []
    monkeypatch.setattr(tc, "_paste_text", lambda text: pasted.append(text) or True)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))
    url = "https://x.com/typofriend/status/2063500000000000165"

    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part.") is True
    assert pasted == [validated[-1]]
    assert pasted[0].endswith("(typo)") and "—" not in pasted[0]


def test_spacing_is_judged_under_the_safari_lock(monkeypatch):
    """A Reply shipped by another thread while this one waited for the
    browser: the spacing check sees it and nothing is claimed."""
    from src.guards import action_guard
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    lock_held = []
    monkeypatch.setattr(action_guard, "can_post",
                        lambda *a, **k: (False, "too soon") if lock_held else (True, ""))

    class ContendedLock:
        def __enter__(self):
            lock_held.append(True)

        def __exit__(self, *exc):
            lock_held.clear()

    monkeypatch.setattr(tc, "_safari_lock", ContendedLock())
    url = "https://x.com/someone/status/2063500000000000166"

    assert tc.reply_to_tweet(url, REPLY) is False
    assert recorded == []
    assert url not in load_replied()


def test_overnight_reply_is_refused_not_raised(monkeypatch):
    """_safari_lock raises OutsideActiveHours on entry; the chokepoint must
    refuse with False before it, like any other skip."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.guards import active_hours
    from src.core import config
    from src.x import twitter_client as tc

    _live_browser(monkeypatch)
    monkeypatch.setattr(active_hours, "now_local",
                        lambda: datetime(2026, 9, 23, 23, 0, tzinfo=ZoneInfo(config.BOT_TIMEZONE)))
    assert tc.reply_to_tweet("https://x.com/someone/status/2063500000000000167", REPLY) is False


def test_dry_run_reply_never_claims_the_tweet(monkeypatch):
    """A simulated Reply writes a dry_run ledger row only: the Replied store
    holds Replies that shipped, so going live later can still answer it."""
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = []
    _dry_run_reply_path(monkeypatch)
    from src.guards import action_guard
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    url = "https://x.com/someone/status/2063500000000000170"

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is tc.DRY_RUN_RECORDED
    assert url not in load_replied()
    assert [k for _, k in recorded] == [{"target": url, "dry_run": True},
                                        {"target": "someone", "dry_run": True}]


def test_refused_reply_never_reaches_safari(monkeypatch):
    """Blocked account, own post and author-less URLs stop at admission:
    conftest fails the test if Safari is touched."""
    from src.guards import action_guard
    from src.core import config
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(config, "BLOCKLIST", {"la pique"})
    for url in ("https://x.com/La_Pique_Off/status/2063500000000000180",
                f"https://x.com/{config.BOT_HANDLE}/status/2063500000000000181",
                "https://x.com/i/web/status/2063500000000000182"):
        assert tc.reply_to_tweet(url, REPLY) is False, url


def test_stop_before_submit_leaves_tweet_fresh_after_submit_keeps_it(monkeypatch):
    import pytest
    from src.x import twitter_client as tc
    from src.guards.active_hours import OutsideActiveHours
    from src.guards.replied_store import load_replied

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
    from src.guards import active_hours
    monkeypatch.setattr(active_hours, "_STOP", threading.Event())
    recorded = _live_browser(monkeypatch, failing_step="stop_after_submit")
    after = "https://x.com/someone/status/2063500000000000141"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(after, REPLY)
    assert after in load_replied()
    assert len(recorded) == 1


def test_release_drops_only_the_claimed_tweet(monkeypatch):
    from src.core import config
    from src.guards import replied_store

    keep, drop = "2063500000000000150", "2063500000000000151"
    with open(config.REPLIED_FILE, "w") as f:
        json.dump({"urls": [f"https://x.com/a/status/{keep}", drop]}, f)

    replied_store.release(f"https://x.com/b/status/{drop}")

    assert json.load(open(config.REPLIED_FILE)) == [f"https://x.com/a/status/{keep}"]


def test_image_post_that_fails_records_nothing(monkeypatch, tmp_path):
    from src.guards import content_guard
    from src.x import twitter_client as tc

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


def _dry_run_follow_path(monkeypatch):
    from src.guards import action_guard
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(action_guard, "can_follow", lambda *a, **k: (True, ""))
    monkeypatch.setattr(tc, "_quality_reject_recent", lambda *_: False)
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    return recorded


def test_dry_run_engage_cycle_leaves_followed_accounts_unchanged(monkeypatch, tmp_path):
    """#123: follow_account returned True on a dry run, so engage_bot stored
    handles it never followed and no later live cycle followed them."""
    from src.guards import action_guard
    from src.account import engage_bot
    from src.core import evolution_store
    from src.x import twitter_client as tc

    recorded = _dry_run_follow_path(monkeypatch)
    followed_file = tmp_path / "followed_accounts.json"
    followed_file.write_text(json.dumps(["already"]))
    monkeypatch.setattr(engage_bot, "FOLLOWED_FILE", str(followed_file))
    monkeypatch.setattr(engage_bot, "_build_pool", lambda: ["already", "newcomer", "other"])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda pool: pool)
    monkeypatch.setattr(engage_bot, "_profile_visit_allowed", lambda *_: False)
    monkeypatch.setattr(engage_bot.time, "sleep", lambda *_: None)

    engage_bot.run_engage_cycle()

    assert set(json.loads(followed_file.read_text())) == {"already"}
    assert sorted(k["target"] for a, k in recorded if a == (action_guard.FOLLOW,)) == ["newcomer", "other"]
    assert all(k["dry_run"] for _, k in recorded)
    assert not tc.DRY_RUN_RECORDED


def test_dry_run_follow_engagers_leaves_its_state_unchanged(monkeypatch, tmp_path):
    """A dry-run follow neither counts toward the day nor burns the Engager,
    and still stops the cycle at its per-cycle bound."""
    from src.account import follow_engagers_bot as fe

    recorded = _dry_run_follow_path(monkeypatch)
    state_file = tmp_path / "follow_engagers_state.json"
    monkeypatch.setattr(fe, "STATE_FILE", str(state_file))
    monkeypatch.setattr(fe, "_engager_handles", lambda: ["fan1", "fan2", "fan3"])
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_CYCLE", "2")

    fe.run_follow_engagers_cycle()

    state = json.loads(state_file.read_text())
    assert state["count_today"] == 0 and state["attempted"] == []
    assert [k["target"] for _, k in recorded] == ["fan1", "fan2"]
