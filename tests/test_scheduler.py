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
