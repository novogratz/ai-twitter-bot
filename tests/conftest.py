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
