"""Cross-cutting: the jobs `main.build_scheduler()` registers."""
import inspect

import pytest


def test_reply_only_still_registers_the_reply_engine():
    from main import build_scheduler
    scheduler = build_scheduler(reply_only=True)
    assert scheduler.get_job("direct_reply_job") is not None
    assert scheduler.get_job("replyback_job") is not None
    assert scheduler.get_job("editorial_job") is None


def test_scheduler_build_runs_no_editorial_cycle(monkeypatch):
    """Building the scheduler publishes nothing: the Startup post goes
    through the editorial job, inside its window and the daily ceiling."""
    import main
    def forbidden(*a, **k):
        raise AssertionError("Building the scheduler must not execute an editorial cycle")
    monkeypatch.setattr(main, "run_editorial_cycle", forbidden)
    scheduler = main.build_scheduler()
    assert inspect.unwrap(scheduler.get_job("editorial_job").func) is forbidden
    assert not any("quote" in j.id or "boost" in j.id or "thread" in j.id for j in scheduler.get_jobs())


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
ACCOUNT_JOBS = [
    ("engage_job", "src.account.engage_bot", "run_engage_cycle", "engage"),
    ("followback_job", "src.account.followback_bot", "run_followback_cycle", "followback"),
    ("follow_engagers_job", "src.account.follow_engagers_bot", "run_follow_engagers_cycle",
     "follow_engagers"),
    ("like_job", "src.account.like_bot", "run_like_cycle", "like"),
    ("pin_job", "src.account.pin_bot", "run_pin_cycle", "pin"),
    ("follower_tracker_job", "src.account.follower_tracker_bot", "run_follower_tracker_cycle",
     "follower_tracker"),
]
WATCHED_JOBS = REPLY_JOBS + ACCOUNT_JOBS


@pytest.mark.parametrize("job_id, module, run, label", WATCHED_JOBS, ids=[j[0] for j in WATCHED_JOBS])
def test_each_watched_job_counts_toward_safari_health_under_its_label(
        monkeypatch, settings_override, caplog, job_id, module, run, label):
    """Issues #237 and #238: the scheduler wraps each Reply and account
    job's `run_*`; its failure is logged at ERROR with the traceback and
    counted under the health label its `safe_run_*` used, `babysitter`
    included."""
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


@pytest.mark.parametrize("job_id, module, run, label", ACCOUNT_JOBS, ids=[j[0] for j in ACCOUNT_JOBS])
def test_each_account_job_resets_the_failure_counter_on_success(
        monkeypatch, caplog, job_id, module, run, label):
    import importlib
    from src.core import health
    from tests.helpers import scheduled_job

    health.HEALTH.write({"consecutive_failures": 2})
    monkeypatch.setattr(importlib.import_module(module), run, lambda: None)

    scheduled_job(job_id)()

    assert health.HEALTH.read()["consecutive_failures"] == 0
    assert f"[HEALTH] {label} OK — resetting failure counter (was 2)." in caplog.messages


@pytest.mark.parametrize("restarted, failures", [(True, 0), (False, 2)])
def test_the_session_refresh_counts_as_a_success_only_after_a_restart(monkeypatch, restarted,
                                                                      failures):
    """Issue #238: a restart refused on its cooldown, or one that failed,
    is the preventive tick working as designed, neither a Safari success
    nor a failure."""
    from src.core import health
    from src.x import safari_hygiene
    from tests.helpers import scheduled_job

    health.HEALTH.write({"consecutive_failures": 2})
    monkeypatch.setattr(safari_hygiene, "restart_safari", lambda reason="": restarted)

    scheduled_job("session_refresh_job")()

    assert health.HEALTH.read()["consecutive_failures"] == failures


def test_a_failed_session_refresh_is_logged_and_not_a_safari_failure(monkeypatch, caplog):
    """Issue #238: the refresh is the Safari restart itself; its own error
    is logged with its traceback, outside the failure counter."""
    from src.core import health
    from src.x import safari_hygiene
    from tests.helpers import scheduled_job

    def fails(reason=""):
        raise OSError("disk full")
    health.HEALTH.write({"consecutive_failures": 2})
    monkeypatch.setattr(safari_hygiene, "restart_safari", fails)
    monkeypatch.setattr(health, "_restart_safari", lambda: pytest.fail("Safari restarted"))

    scheduled_job("session_refresh_job")()

    assert health.HEALTH.read()["consecutive_failures"] == 2
    [error] = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error.getMessage() == "[hygiene] Cycle failed."
    assert "OSError: disk full" in caplog.text
