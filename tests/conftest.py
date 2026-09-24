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


def pytest_configure(config):
    from src.core.logger import setup_logging

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


_UNWALLED = {}


@_pytest.fixture
def unwalled():
    """The real safari primitives, for tests that fake subprocess themselves."""
    return _UNWALLED


@_pytest.fixture(autouse=True)
def _no_safari(monkeypatch):
    import webbrowser as _wb

    def _blocked(*a, **k):
        raise AssertionError(
            "TEST TRIED TO DRIVE SAFARI — mock the primitive in src.x.safari "
            "(function-local imports bypass caller-module mocks)."
        )

    monkeypatch.setattr(_wb, "open", _blocked)
    # No try/except: an import that breaks (a moved module) must fail every
    # test, not silently drop the wall.
    # The primitives live in src.x.safari; twitter_client and scraper call
    # them through the module, so this patch reaches every src.x path.
    from src.x import safari as _safari
    for name in ("_run_applescript", "_run_js", "_paste_text"):
        _UNWALLED.setdefault(name, getattr(_safari, name))
    monkeypatch.setattr(_safari, "_run_applescript", _blocked)
    monkeypatch.setattr(_safari, "_run_js", _blocked)
    monkeypatch.setattr(_safari, "_paste_text", _blocked)

    # safari.py itself, the Safari quit and relaunch in safari_hygiene and
    # bin/mass_unfollow.py call subprocess.run(["osascript", ...]) (or `open`,
    # `pkill`) directly, past the helpers above.
    # subprocess.run/call/check_output all go through subprocess.Popen.
    import subprocess as _sp

    def _drives_safari(argv):
        argv = [str(a) for a in argv] if isinstance(argv, (list, tuple)) else str(argv).split()
        if not argv:
            return False
        program = os.path.basename(argv[0])
        return program == "osascript" or (
            program in ("open", "pkill", "killall")
            and any("Safari" in a or "WebKit" in a for a in argv[1:]))

    class _WalledPopen(_sp.Popen):
        def __init__(self, args, *a, **k):
            if _drives_safari(args):
                _blocked()
            super().__init__(args, *a, **k)

    monkeypatch.setattr(_sp, "Popen", _WalledPopen)
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
    from src.core import config as _cfg
    monkeypatch.setattr(_cfg, "ENGAGEMENT_LOG_FILE", str(tmp_path / "engagement_log.csv"))
    monkeypatch.setattr(_cfg, "HISTORY_FILE", hist)
    monkeypatch.setattr(_cfg, "REPLIED_FILE", str(tmp_path / "replied_tweets.json"))
    monkeypatch.setattr(_cfg, "ACTION_LEDGER_FILE", str(tmp_path / "action_ledger.json"))
    # from-imports bind at import time — patch every namespace that copied one.
    from src.core import engagement_log as _el
    monkeypatch.setattr(_el, "ENGAGEMENT_LOG_FILE", _cfg.ENGAGEMENT_LOG_FILE)
    from src.core import history as _hist
    monkeypatch.setattr(_hist, "HISTORY_FILE", hist)
    from src.guards import content_guard as _cg
    monkeypatch.setattr(_cg, "_HISTORY_FILE", hist)
    # personality.json: log_reply -> personality_store.record_interaction
    # writes dossiers — a test author leaked into prod 2026-07-19 (same
    # family as the 2026-06-09 fixture pollution).
    from src.core import personality_store as _ps
    monkeypatch.setattr(_ps, "PERSONALITY_FILE", str(tmp_path / "personality.json"))
    # The frozen Engager list is tracked in git: never read the live one.
    from src.account import follow_engagers_bot as _fe
    monkeypatch.setattr(_fe, "FROZEN_REPLIED_BACK_FILE", str(tmp_path / "replied_back.json"))
    yield


@_pytest.fixture(autouse=True)
def _daylight_default(monkeypatch):
    """Legacy tests run during daytime independent of the CI host's clock.

    Boundary tests replace this clock with their own explicit instants.
    """
    from src.guards import active_hours
    real_now = active_hours.now_local
    monkeypatch.setattr(active_hours, "now_local", lambda: real_now().replace(hour=12, minute=0))
    yield


@_pytest.fixture(autouse=True)
def _fresh_job_memory(monkeypatch):
    """Each reply job keeps the posts it dropped in a module-level set, the
    direct reply its query rotation cursor, and the content guard the posts
    of this run in its dedup memory, for the life of the process; every test
    starts with fresh ones."""
    import importlib
    for name in ("direct_reply", "feed_sweeper_bot", "early_bird_bot", "mega_watch_bot", "debate_bot",
                 "notify_bot"):
        monkeypatch.setattr(importlib.import_module(f"src.replies.{name}"), "_skipped", set())
    from src.replies import direct_reply as _dr
    monkeypatch.setattr(_dr, "_QUERY_ROTATION_OFFSET", [0])
    from src.guards import content_guard as _cg
    monkeypatch.setattr(_cg, "_RECENT_NORM", [])
    yield


@_pytest.fixture
def like_job(monkeypatch, tmp_path):
    """Live like_job on a scripted search page; the real walk and like_tweet run."""
    from src.account import like_bot
    from src.x import safari, twitter_client as tc
    from tests.helpers import SearchPage

    monkeypatch.setenv("DRY_RUN", "0")
    for name in ("LIKE_BOT_PER_CYCLE", "LIKE_BOT_DAILY_CAP", "LIKE_BOT_CYCLE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(like_bot, "LIKE_BOT_STATE_FILE", str(tmp_path / "like_state.json"))
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tc, "_liked_cache_path", lambda: str(tmp_path / "liked_tweets.json"))
    state = {"page": SearchPage([]), "closed": 0}
    monkeypatch.setattr(tc, "_page_posts", lambda *a: state["page"](*a))

    def close_front_tab():
        state["closed"] += 1
    monkeypatch.setattr(safari, "close_front_tab", close_front_tab)
    return state
