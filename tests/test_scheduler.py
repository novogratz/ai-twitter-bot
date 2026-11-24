"""Cross-cutting: the jobs `main.build_scheduler()` registers."""
import inspect

import pytest


def test_reply_only_still_registers_the_reply_engine():
    from main import build_scheduler
    scheduler = build_scheduler(reply_only=True)
    assert scheduler.get_job("direct_reply_job") is not None
    assert scheduler.get_job("replyback_job") is None
    assert scheduler.get_job("editorial_job") is None


@pytest.mark.parametrize("reply_only", [False, True])
def test_conversation_jobs_cannot_be_enabled_by_environment(settings_override, reply_only):
    from main import build_scheduler
    settings_override(ENABLE_DEBATES=True, ENABLE_REPLY_SEARCH=True)
    jobs = {job.id for job in build_scheduler(reply_only=reply_only).get_jobs()}
    assert not jobs & {"debate_job", "replyback_job", "babysit_job"}
    assert {"direct_reply_job", "feed_sweep_job", "early_bird_job", "mega_watch_job", "reply_job"} <= jobs


def test_scheduler_build_runs_no_editorial_cycle(monkeypatch):
    """Building the scheduler publishes nothing: the Startup post goes
    through the editorial job, inside its window and the daily ceiling."""
    import main
    def forbidden(*a, **k):
        raise AssertionError("Building the scheduler must not execute an editorial cycle")
    monkeypatch.setattr(main, "run_editorial_cycle", forbidden)
    scheduler = main.build_scheduler()
    assert inspect.unwrap(scheduler.get_job("editorial_job").func) is forbidden
    assert scheduler.get_job("priority_quote_job") is None
    assert scheduler.get_job("self_repost_job") is None
    assert not any("thread" in j.id for j in scheduler.get_jobs())


@pytest.mark.parametrize("flags, opened", [(["--reply-only"], False), ([], True), (["--post-only"], True)])
def test_only_a_run_with_the_editorial_job_opens_a_startup_post(monkeypatch, flags, opened):
    import sys
    import main

    class Started(Exception):
        pass

    class Scheduler:
        def start(self, paused):
            raise Started
    calls = []
    monkeypatch.setattr(sys, "argv", ["main.py", *flags])
    monkeypatch.setattr(main, "_acquire_singleton_lock", lambda: None)
    monkeypatch.setattr(main, "build_scheduler", lambda **k: Scheduler())
    monkeypatch.setattr(main, "open_startup_window", lambda: calls.append(True))
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)
    with pytest.raises(Started):
        main.main()
    assert calls == ([True] if opened else [])


@pytest.mark.parametrize("flags, requested", [([], True), (["--post-only"], True),
                                             (["--reply-only"], False), (["--dry-run"], False),
                                             (["--startup-publications"], True),
                                             (["--startup-publications", "--reply-only"], False),
                                             (["--startup-publications", "--dry-run"], False)])
def test_video_boot_is_requested_only_by_live_video_scheduler(monkeypatch, settings_override, flags, requested):
    import sys
    import main
    from src.video import workers

    class Started(Exception):
        pass

    class Scheduler:
        def start(self, paused):
            raise Started
        def get_jobs(self):
            return []

    calls = []
    settings_override(VIDEO_ENABLED=True)
    monkeypatch.setattr(sys, "argv", ["main.py", *flags])
    monkeypatch.setattr(main, "_acquire_singleton_lock", lambda: None)
    monkeypatch.setattr(main, "build_scheduler", lambda **k: Scheduler())
    monkeypatch.setattr(main, "_request_startup_video", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)
    monkeypatch.setattr(workers, "Supervisor", object)
    if "--dry-run" in flags:
        main.main()
    else:
        with pytest.raises(Started):
            main.main()
    assert calls == ([{"retry_expired": "--startup-publications" in flags}] if requested else [])


def test_the_start_reports_an_unknown_llm_provider(monkeypatch, settings_override, capsys, caplog):
    """Issue #189: a provider name no adapter carries fails every call it
    routes; the start says so, in the log and in the dry run."""
    import json
    import sys
    import main

    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    settings_override(AI_CLI="olama", LLM_FALLBACK_CLI="")
    main.main()
    assert json.loads(capsys.readouterr().out)["unknown_llm_providers"] == ["AI_CLI='olama'"]
    assert "Unknown provider AI_CLI='olama'" in caplog.text


def test_the_start_reports_an_explicit_fallback_it_ignores(monkeypatch, settings_override, capsys, caplog):
    """Review of #189: LLM_FALLBACK_CLI=claude gave no fallback and said
    nothing."""
    import json
    import sys
    import main

    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    settings_override(AI_CLI="ollama", PROFILE_LLM_PROVIDER="", REPLY_LLM_PROVIDER="",
                      LLM_FALLBACK_CLI="claude", LLM_DISABLE_FALLBACK=False)
    main.main()
    note = "LLM_FALLBACK_CLI='claude' behind AI_CLI='ollama': claude is never a fallback"
    assert json.loads(capsys.readouterr().out)["ignored_llm_fallbacks"] == [note]
    assert f"Fallback ignored: {note}" in caplog.text


REPLY_JOBS = [
    ("direct_reply_job", "src.replies.direct_reply", "run_direct_reply_cycle", "direct_reply"),
    ("feed_sweep_job", "src.replies.feed_sweeper_bot", "run_feed_sweep_cycle", "feed_sweep"),
    ("early_bird_job", "src.replies.early_bird_bot", "run_early_bird_cycle", "early_bird"),
    ("replyback_job", "src.replies.notify_bot", "run_replyback_cycle", "replyback"),
    ("debate_job", "src.replies.debate_bot", "run_debate_cycle", "debate"),
    ("mega_watch_job", "src.replies.mega_watch_bot", "run_mega_watch_cycle", "mega_watch"),
    ("babysit_job", "src.replies.first_hour_babysitter", "run_babysit_cycle", "babysitter"),
    ("notify_job", "src.replies.notify_bot", "run_notify_cycle", "notify"),
    ("reply_job", "src.replies.reply_bot", "run_reply_cycle", "reply"),
]


@pytest.mark.parametrize("job_id, module, run, label", REPLY_JOBS, ids=[j[0] for j in REPLY_JOBS])
def test_each_reply_job_counts_toward_safari_health_under_its_label(
        monkeypatch, settings_override, caplog, job_id, module, run, label, conversation_account):
    """Issue #237: the scheduler wraps each Reply job's `run_*`; its failure
    is logged at ERROR with the traceback and counted under the health label
    its `safe_run_*` used, `babysitter` included."""
    import importlib
    from src.core import health
    from tests.helpers import scheduled_job

    def fails():
        raise RuntimeError("page never loaded")
    monkeypatch.setattr(importlib.import_module(module), run, fails)
    monkeypatch.setattr(health, "_restart_safari", lambda: pytest.fail("Safari restarted"))
    settings_override(ENABLE_REPLY_SEARCH=True)

    scheduled_job(job_id)()

    assert health.HEALTH.read()["consecutive_failures"] == 1
    assert f"[HEALTH] {label} FAILED — consecutive = 1." in caplog.messages
    [error] = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error.getMessage() == f"[{label}] Cycle failed."
    assert "RuntimeError: page never loaded" in caplog.text


def test_invited_mode_registers_only_help_even_with_other_features_enabled(settings_override, promotion_account):
    import main
    from src.video import config
    settings_override(REPLY_INVITED_ONLY=True, REPLY_REVIEW_ONLY=False, VIDEO_ENABLED=True, VIDEO_LIVE=True,
                      NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True, MEME_REPOST_ENABLED=True, ENABLE_REPLY_SEARCH=True)
    jobs = main.build_scheduler(startup_publications=True).get_jobs()
    assert [job.id for job in jobs] == ["invited_help_job"]
    assert jobs[0].trigger.interval.total_seconds() == 180
    assert not config.live()
    assert not main.build_scheduler(post_only=True).get_jobs()


def test_invited_start_cannot_start_profile_publishers(monkeypatch, settings_override):
    import sys
    import main
    from src.video import workers
    settings_override(REPLY_INVITED_ONLY=True, REPLY_REVIEW_ONLY=False, VIDEO_ENABLED=True, NEWS_ENABLED=True)
    class Started(Exception):
        pass
    class Scheduler:
        def start(self, paused):
            raise Started
    def forbidden(*a, **k):
        pytest.fail("invited-only startup reached a profile publisher")
    monkeypatch.setattr(sys, "argv", ["main.py", "--startup-publications"])
    monkeypatch.setattr(main, "_acquire_singleton_lock", lambda: None)
    monkeypatch.setattr(main, "build_scheduler", lambda **k: Scheduler())
    monkeypatch.setattr(main, "open_startup_window", forbidden)
    monkeypatch.setattr(main, "_request_startup_video", forbidden)
    monkeypatch.setattr(main, "_request_startup_news", forbidden)
    monkeypatch.setattr(workers, "Supervisor", forbidden)
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)
    with pytest.raises(Started):
        main.main()


def test_video_scheduler_runs_beside_restricted_replies_only_when_opted_in(settings_override, promotion_account):
    """2026-11-23: curated Replies silently removed the video job; the Operator asked for videos again."""
    import main
    from src.video import config
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True, REPLY_REVIEW_ONLY=False,
                      VIDEO_ENABLED=True, VIDEO_LIVE=True, DRY_RUN=False, NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True)
    before = [job.id for job in main.build_scheduler().get_jobs()]
    assert "video_health_job" not in before and not config.scheduled() and not config.live()
    settings_override(VIDEO_WITH_REPLIES=True)
    jobs = {job.id: job for job in main.build_scheduler().get_jobs()}
    assert set(jobs) == set(before) | {"video_health_job"}  # no editorial, news or startup job comes with it
    assert jobs["video_health_job"].executor == "video" and config.scheduled() and config.live()
    settings_override(VIDEO_LIVE=False)
    assert config.scheduled() and not config.live()
    settings_override(VIDEO_LIVE=True, REPLY_REVIEW_ONLY=True)
    assert not config.scheduled() and not config.live()
    assert "video_health_job" not in [job.id for job in main.build_scheduler().get_jobs()]


def test_restricted_start_supervises_video_workers_only_when_opted_in(monkeypatch, settings_override):
    import sys
    import main
    from src.video import workers
    settings_override(REPLY_INVITED_ONLY=True, REPLY_REVIEW_ONLY=False, VIDEO_ENABLED=True, VIDEO_LIVE=True,
                      VIDEO_WITH_REPLIES=True, NEWS_ENABLED=True)
    class Started(Exception):
        pass
    class Scheduler:
        def start(self, paused):
            raise Started
    started = []
    def forbidden(*a, **k):
        pytest.fail("restricted startup reached another profile publisher")
    monkeypatch.setattr(sys, "argv", ["main.py", "--startup-publications"])
    monkeypatch.setattr(main, "_acquire_singleton_lock", lambda: None)
    monkeypatch.setattr(main, "build_scheduler", lambda **k: Scheduler())
    monkeypatch.setattr(main, "open_startup_window", forbidden)
    monkeypatch.setattr(main, "_request_startup_news", forbidden)
    monkeypatch.setattr(main, "_request_startup_video", lambda **k: started.append("request"))
    monkeypatch.setattr(workers, "Supervisor", lambda: started.append("supervisor") or object())
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)
    with pytest.raises(Started):
        main.main()
    assert started == ["supervisor", "request"]


def test_broad_watched_work_uses_fast_independent_workers(settings_override, watched_account):
    """Polling does not wait for ordinary discovery, selection or Reply generation."""
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_REVIEW_ONLY=False, PRIORITY_WATCH_INTERVAL_SECONDS=5,
                      PRIORITY_WATCH_DISPATCH_SECONDS=2)
    scheduler = main.build_scheduler()
    for name, interval, executor in (
        ("priority_watch_job", 5, "watch"),
        ("priority_actions_job", 2, "watch_actions"),
        ("curated_repost_job", 2, "quotes"),
        ("priority_reply_job", 2, "watch_reply"),
    ):
        job = scheduler.get_job(name)
        assert job.trigger.interval.total_seconds() == interval
        assert job.executor == executor
        assert job.next_run_time is not None
    assert scheduler._job_defaults["max_instances"] == 1
    assert scheduler._job_defaults["coalesce"] is True
    assert main.build_scheduler(reply_only=True).get_job("priority_watch_job") is None


def test_automatic_broad_mode_runs_reply_workers_without_using_the_manual_inbox(
        settings_override, watched_account, monkeypatch):
    import main
    from src.replies import review, direct_reply, feed_sweeper_bot
    def forbidden(*args, **kwargs):
        pytest.fail("automatic scheduler must not drain or prepare the manual inbox")
    monkeypatch.setattr(review, "prepare", forbidden)
    monkeypatch.setattr(review, "discover_and_prepare", forbidden)
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_REVIEW_ONLY=False, REPLY_MANUAL_ORDINARY=False, REPLY_MANUAL_DISCOVERY=False,
                      MAX_REPLIES_PER_DAY=1500, REPLY_DAILY_TARGET_MIN=1500, REPLY_DAILY_TARGET_MAX=1500,
                      MIN_SECONDS_BETWEEN_REPLIES=8, REPLY_JITTER_SECONDS=4,
                      REPLY_WORKLOAD_BOOST_START_DATE="")
    scheduler = main.build_scheduler()
    jobs = {job.id for job in scheduler.get_jobs()}
    assert jobs == {"direct_reply_job", "feed_sweep_job", "opt_out_mentions_job",
                    "priority_watch_job", "priority_actions_job", "curated_repost_job", "priority_reply_job"}
    assert inspect.unwrap(scheduler.get_job("direct_reply_job").func) is direct_reply.run_direct_reply_cycle
    assert inspect.unwrap(scheduler.get_job("feed_sweep_job").func) is feed_sweeper_bot.run_feed_sweep_cycle
    assert scheduler.get_job("direct_reply_job").next_run_time is not None
    assert scheduler.get_job("feed_sweep_job").next_run_time is not None
    assert not jobs & {"reply_draft_job", "debate_job", "replyback_job", "editorial_job", "video_health_job"}


@pytest.mark.parametrize("for_you_first,direct_minutes,feed_minutes", [
    (True, 30, 1), (True, 15, 4), (False, 30, 8),
])
def test_for_you_runs_first_and_secondary_search_waits_its_interval(
        settings_override, watched_account, for_you_first, direct_minutes, feed_minutes):
    from datetime import datetime, timedelta, timezone
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_REVIEW_ONLY=False, REPLY_MANUAL_ORDINARY=False, REPLY_MANUAL_DISCOVERY=False,
                      REPLY_FOR_YOU_FIRST=for_you_first, DIRECT_REPLY_INTERVAL_MINUTES=direct_minutes,
                      FEED_SWEEP_INTERVAL_MINUTES=feed_minutes, PRIORITY_WATCH_INTERVAL_SECONDS=5,
                      PRIORITY_WATCH_DISPATCH_SECONDS=2)
    before = datetime.now(timezone.utc)
    scheduler = main.build_scheduler()
    after = datetime.now(timezone.utc)
    expected = {
        "feed_sweep_job": (feed_minutes * 60, 2 if for_you_first else 10),
        "direct_reply_job": (direct_minutes * 60, direct_minutes * 60) if for_you_first else (120, 2),
        "opt_out_mentions_job": (600, 1),
        "priority_watch_job": (5, 1), "priority_actions_job": (2, 2),
        "curated_repost_job": (2, 2), "priority_reply_job": (2, 2),
    }
    assert {job.id for job in scheduler.get_jobs()} == set(expected)
    for job_id, (interval, first) in expected.items():
        job = scheduler.get_job(job_id)
        assert job.trigger.interval.total_seconds() == interval
        assert before + timedelta(seconds=first) <= job.next_run_time <= after + timedelta(seconds=first)
    if for_you_first:
        assert scheduler.get_job("feed_sweep_job").next_run_time < scheduler.get_job("direct_reply_job").next_run_time
    else:
        assert scheduler.get_job("direct_reply_job").next_run_time < scheduler.get_job("feed_sweep_job").next_run_time


@pytest.mark.parametrize("post_only,reply_only", [(True, False), (False, True)])
def test_for_you_priority_preserves_cli_mode_boundaries(settings_override, watched_account, post_only, reply_only):
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_FOR_YOU_FIRST=True, REPLY_REVIEW_ONLY=False,
                      REPLY_MANUAL_ORDINARY=False, REPLY_MANUAL_DISCOVERY=False)
    jobs = {job.id for job in main.build_scheduler(post_only=post_only, reply_only=reply_only).get_jobs()}
    assert jobs == (set() if post_only else {"direct_reply_job", "feed_sweep_job", "opt_out_mentions_job"})


def test_for_you_flag_does_not_change_the_nonbroad_legacy_scheduler(settings_override):
    from datetime import datetime, timedelta, timezone
    import main
    settings_override(REPLY_INVITED_ONLY=False, REPLY_CURATED_MODE=False, REPLY_BROAD_DISCOVERY=False,
                      REPLY_FOR_YOU_FIRST=True, DIRECT_REPLY_INTERVAL_MINUTES=30, FEED_SWEEP_INTERVAL_MINUTES=8)
    before = datetime.now(timezone.utc)
    scheduler = main.build_scheduler(reply_only=True)
    after = datetime.now(timezone.utc)
    for name, interval, first in (("direct_reply_job", 120, 2), ("feed_sweep_job", 480, 10)):
        job = scheduler.get_job(name)
        assert job.trigger.interval.total_seconds() == interval
        assert before + timedelta(seconds=first) <= job.next_run_time <= after + timedelta(seconds=first)


@pytest.mark.parametrize("large_priority", [False, True])
@pytest.mark.parametrize("configured_age,reported_age", [(60, 60), (7200, 60), (30, 30)])
def test_for_you_startup_reports_actual_discovery_freshness_and_author_preference(
        monkeypatch, settings_override, caplog, large_priority, configured_age, reported_age):
    import sys
    import threading
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_FOR_YOU_FIRST=True, REPLY_REVIEW_ONLY=False,
                      REPLY_MANUAL_ORDINARY=False, REPLY_MANUAL_DISCOVERY=False,
                      DIRECT_REPLY_INTERVAL_MINUTES=30, FEED_SWEEP_INTERVAL_MINUTES=1,
                      FEED_FOLLOWING_EVERY_CYCLES=20, DIRECT_REPLY_MAX_AGE_MINUTES=configured_age,
                      REPLY_PRIORITIZE_LARGE_ACCOUNTS=large_priority)
    class Scheduler:
        def start(self, paused):
            assert paused is True
        def shutdown(self, wait):
            assert wait is False
    stopped = threading.Event()
    stopped.set()
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(main, "build_scheduler", lambda **kwargs: Scheduler())
    monkeypatch.setattr(main, "_acquire_singleton_lock", lambda: None)
    monkeypatch.setattr(main.state_store, "require_migrated", lambda: None)
    monkeypatch.setattr(main.state_store, "ensure_root", lambda: None)
    monkeypatch.setattr(main.threading, "Event", lambda: stopped)
    monkeypatch.setattr(main.signal, "signal", lambda *args: None)
    main.main()
    [banner] = [message for message in caplog.messages if message.startswith("Bot started:")]
    assert "For You first every 1 minute" in banner
    assert "Following every 20 cycles after For You replies" in banner
    assert "secondary Latest searches every 30 minutes, starting after that interval" in banner
    assert f"sources at most {reported_age} minutes old" in banner
    assert "major-author preference=False" in banner
    assert "larger-account priority" not in banner


@pytest.mark.parametrize("for_you_first", [False, True])
def test_for_you_dry_run_describes_the_same_discovery_without_running_jobs(
        monkeypatch, settings_override, capsys, watched_account, for_you_first):
    import json
    import sys
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_FOR_YOU_FIRST=for_you_first, REPLY_REVIEW_ONLY=False,
                      REPLY_MANUAL_ORDINARY=False, REPLY_MANUAL_DISCOVERY=False,
                      DIRECT_REPLY_INTERVAL_MINUTES=30, FEED_SWEEP_INTERVAL_MINUTES=1,
                      FEED_FOLLOWING_EVERY_CYCLES=20, DIRECT_REPLY_MAX_AGE_MINUTES=60,
                      REPLY_PRIORITIZE_LARGE_ACCOUNTS=True)
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    main.main()
    report = json.loads(capsys.readouterr().out)
    if for_you_first:
        assert "For You first every 1 minute" in report["discovery"]
        assert "sources at most 60 minutes old" in report["discovery"]
    else:
        assert "Top and Latest searches plus both Home feeds" in report["discovery"]
    assert report["large_account_priority"] is not for_you_first
    assert {"feed_sweep_job", "direct_reply_job", "opt_out_mentions_job"} <= set(report["jobs"])


def test_inspected_curated_mode_retains_bounded_slow_repost_selector(settings_override, watched_account):
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=False,
                      REPLY_REVIEW_ONLY=False)
    scheduler = main.build_scheduler()
    assert scheduler.get_job("curated_repost_job").trigger.interval.total_seconds() == 1800
    assert scheduler.get_job("priority_reply_job") is None


@pytest.mark.parametrize("manual_ordinary", [False, True])
@pytest.mark.parametrize("for_you_first", [False, True])
def test_manual_discovery_has_four_read_only_sessions_and_no_ordinary_auto_jobs(
        settings_override, watched_account, monkeypatch, manual_ordinary, for_you_first):
    import main
    from src.replies import review
    def forbidden():
        pytest.fail("building schedule must not discover or generate")
    monkeypatch.setattr(review, "discover_and_prepare", forbidden, raising=False)
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True,
                      REPLY_REVIEW_ONLY=not manual_ordinary, REPLY_MANUAL_ORDINARY=manual_ordinary,
                      REPLY_MANUAL_DISCOVERY=True, REPLY_FOR_YOU_FIRST=for_you_first)
    scheduler = main.build_scheduler()
    jobs = {job.id for job in scheduler.get_jobs()}
    job = scheduler.get_job("reply_draft_job")
    assert job.executor == "drafts"
    assert inspect.unwrap(job.func) is forbidden
    assert str(job.trigger.timezone) == "America/Toronto"
    assert str(job.trigger.fields[5]) == "5,10,15,20"
    assert str(job.trigger.fields[6]) == "0"
    assert not {"direct_reply_job", "feed_sweep_job", "editorial_job", "invited_help_job"} & jobs
    if manual_ordinary:
        assert {"priority_watch_job", "priority_reply_job", "curated_repost_job", "opt_out_mentions_job"} <= jobs
    else:
        assert jobs == {"reply_draft_job"}
    assert main.build_scheduler(post_only=True).get_job("reply_draft_job") is None


def test_manual_discovery_start_cannot_boot_profile_publishers(monkeypatch, settings_override):
    import sys
    import main
    from src.video import workers
    settings_override(REPLY_REVIEW_ONLY=True, REPLY_MANUAL_DISCOVERY=True, REPLY_INVITED_ONLY=False,
                      REPLY_CURATED_MODE=False, VIDEO_ENABLED=True, NEWS_ENABLED=True)
    class Started(Exception):
        pass
    class Scheduler:
        def start(self, paused):
            raise Started
    def forbidden(*a, **k):
        pytest.fail("manual discovery reached a profile publisher")
    monkeypatch.setattr(sys, "argv", ["main.py", "--startup-publications"])
    monkeypatch.setattr(main, "_acquire_singleton_lock", lambda: None)
    monkeypatch.setattr(main, "build_scheduler", lambda **k: Scheduler())
    monkeypatch.setattr(main, "open_startup_window", forbidden)
    monkeypatch.setattr(main, "_request_startup_video", forbidden)
    monkeypatch.setattr(main, "_request_startup_news", forbidden)
    monkeypatch.setattr(workers, "Supervisor", forbidden)
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)
    with pytest.raises(Started):
        main.main()
