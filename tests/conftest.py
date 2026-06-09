"""Test-session isolation.

The guard tests exercise real bot modules whose logger writes to the LIVE
bot.log. Before this fixture, every pytest run sprayed fixture garbage into
production logs — fake "[ENGINE_HEALTH] ⚠️ ALERT: reply collapsed" ERROR
lines, "Topic A / @elonmusk 9000 likes" hot-quote fixtures — which (a) made
the bot look broken during operator log reads (2026-06-07: "bot feels
broken or blocked"), and (b) once launched a REAL emergency Claude session
before the self-heal kill-switch read env at call time.

Redirect the bot logger to a per-session temp file before any test imports
fire a log line.
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Belt: make absolutely sure no test can spawn the self-heal subprocess.
os.environ.setdefault("ENABLE_SELF_HEAL", "0")


def pytest_configure(config):
    from src.logger import setup_logging

    logger = setup_logging()
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    tmp = tempfile.NamedTemporaryFile(
        mode="a", prefix="bot-test-", suffix=".log", delete=False)
    handler = logging.StreamHandler(tmp)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info(f"[TEST] bot logger redirected to {tmp.name} for this pytest session.")


# ---------------------------------------------------------------------------
# Safari/AppleScript hard wall (2026-06-07). A guard test mocked
# direct_reply.reply_to_tweet — but the VIP scan imports reply_to_tweet
# FUNCTION-LOCALLY from twitter_client, bypassing the mock. The test drove
# the REAL Safari session (concurrently with the live bot) and posted real
# replies to @TheBTCTherapist. Tests must never be able to reach the
# browser: any unmocked Safari primitive now fails the test loudly.
# A test that legitimately needs these patches them itself (monkeypatch
# runs after this autouse fixture).
# ---------------------------------------------------------------------------
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _no_safari(monkeypatch):
    import webbrowser as _wb

    def _blocked(*a, **k):
        raise AssertionError(
            "TEST TRIED TO DRIVE SAFARI — mock at the twitter_client level "
            "(function-local imports bypass caller-module mocks)."
        )

    monkeypatch.setattr(_wb, "open", _blocked)
    try:
        from src import twitter_client as _tc
        monkeypatch.setattr(_tc, "_run_applescript", _blocked)
        monkeypatch.setattr(_tc, "_paste_text", _blocked)
    except Exception:
        pass
    yield
