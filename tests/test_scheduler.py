"""Cross-cutting: the jobs `main.build_scheduler()` registers."""
import pytest


def test_reply_only_still_registers_the_reply_engine():
    from main import build_scheduler
    scheduler = build_scheduler(reply_only=True)
    assert scheduler.get_job("direct_reply_job") is not None
    assert scheduler.get_job("replyback_job") is not None
    assert scheduler.get_job("editorial_job") is None


@pytest.mark.usefixtures("isolate_dedup")
def test_scheduler_build_has_no_startup_publishing(monkeypatch):
    import main
    def forbidden(*a, **k):
        raise AssertionError("Startup must not execute an editorial cycle")
    monkeypatch.setattr(main, "safe_run_editorial_cycle", forbidden)
    scheduler = main.build_scheduler()
    assert scheduler.get_job("editorial_job") is not None
    assert not any("quote" in j.id or "boost" in j.id or "thread" in j.id for j in scheduler.get_jobs())
