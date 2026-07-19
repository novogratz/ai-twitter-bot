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


# ---------------------------------------------------------------------------
# Production state-file wall (2026-06-09). Same family as _no_safari: a guard
# test (test_bot_cycle_no_unbound_tweet_when_news_capped) mocked post_tweet
# but bot.py's post-ship bookkeeping (save_tweet + log_hotake) still wrote
# the REAL tweet_history.json and engagement_log.csv. Its fixture text
# ("AI capex is the new rent...") accumulated 21 phantom engagement rows and
# 6 phantom history entries over two days — and a self-eval session then
# "diagnosed" a live repetition bug from its own test pollution.
# Every test gets per-test tmp copies of the measurement/state stores; a test
# that needs a specific path still patches it itself (monkeypatch runs after).
# ---------------------------------------------------------------------------
@_pytest.fixture(autouse=True)
def _no_prod_state(monkeypatch, tmp_path):
    hist = str(tmp_path / "tweet_history.json")
    from src import config as _cfg
    monkeypatch.setattr(_cfg, "ENGAGEMENT_LOG_FILE", str(tmp_path / "engagement_log.csv"))
    monkeypatch.setattr(_cfg, "HISTORY_FILE", hist)
    monkeypatch.setattr(_cfg, "REPLIED_FILE", str(tmp_path / "replied_tweets.json"))
    monkeypatch.setattr(_cfg, "ACTION_LEDGER_FILE", str(tmp_path / "action_ledger.json"))
    # from-imports bind at import time — patch every namespace that copied one.
    from src import engagement_log as _el
    monkeypatch.setattr(_el, "ENGAGEMENT_LOG_FILE", _cfg.ENGAGEMENT_LOG_FILE)
    from src import history as _hist
    monkeypatch.setattr(_hist, "HISTORY_FILE", hist)
    from src import content_guard as _cg
    monkeypatch.setattr(_cg, "_HISTORY_FILE", hist)
    from src import reply_bot as _rb
    monkeypatch.setattr(_rb, "REPLIED_FILE", _cfg.REPLIED_FILE)
    # personality.json: log_reply -> personality_store.record_interaction
    # writes dossiers — a test author leaked into prod 2026-07-19 (same
    # family as the 2026-06-09 fixture pollution).
    from src import personality_store as _ps
    monkeypatch.setattr(_ps, "PERSONALITY_FILE", str(tmp_path / "personality.json"))
    yield
