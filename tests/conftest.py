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
    """The real safari primitives, for tests that fake subprocess themselves,
    and the real `state_store.root` under "state_root"."""
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
    for name in ("_run_applescript", "_run_js", "_paste_text", "open_url"):
        _UNWALLED.setdefault(name, getattr(_safari, name))
        monkeypatch.setattr(_safari, name, _blocked)

    # safari.py itself and the Safari quit and relaunch in safari_hygiene
    # call subprocess.run(["osascript", ...]) (or `open`, `pkill`) directly,
    # past the helpers above.
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
# Every state file resolves through state_store.root(), the StateFiles and
# the StatePaths (ledger, Replied store, engagement log...) alike: moving it
# moves them all, personality.json and the frozen replied_back.json included
# (both leaked or read live before, 2026-07-19 and #100). The project root,
# where the state lived before #207, becomes an empty folder too.
# ---------------------------------------------------------------------------
@_pytest.fixture(autouse=True)
def _no_prod_state(monkeypatch, tmp_path, tmp_path_factory):
    from src.core import state_store as _store
    _UNWALLED.setdefault("state_root", _store.root)
    monkeypatch.setattr(_store, "root", lambda: str(tmp_path))
    monkeypatch.setattr(_store, "LEGACY_DIR", str(tmp_path_factory.mktemp("legacy_root")))
    # A migrated install (#206): the follow policy refuses while the
    # promoted handles' file is missing.
    (tmp_path / "whitelist_discovered.json").write_text("[]")
    # The Operator files live in the versioned Account folder: every test
    # reads a copy of it, which `operator_folder` names.
    import shutil as _shutil
    from src.core import account as _account, settings as _settings
    _UNWALLED.setdefault("accounts_dir", _account.ACCOUNTS_DIR)
    name = _settings.get("BOT_ACCOUNT")
    accounts = tmp_path_factory.mktemp("accounts")
    _shutil.copytree(os.path.join(_settings.PROJECT_ROOT, _UNWALLED["accounts_dir"], name),
                     accounts / name)
    monkeypatch.setattr(_account, "ACCOUNTS_DIR", str(accounts))
    yield


@_pytest.fixture
def operator_folder():
    """The test's copy of the Account folder, where the Operator files are
    read (a pathlib.Path)."""
    from pathlib import Path
    from src.core import account
    return Path(account.current().folder)


@_pytest.fixture
def respected(operator_folder):
    """`respected("handle", ...)`: add Respected accounts to the test's copy
    of the respect list."""
    import json
    path = operator_folder / "respect_list.json"

    def add(*handles):
        doc = json.loads(path.read_text())
        doc["handles"].update({h: {"reason": "test"} for h in handles})
        path.write_text(json.dumps(doc))
    return add


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
def _cli_installed(monkeypatch):
    """Tests run the same whichever model CLIs the host has installed: every
    CLI looks installed. A test of a missing CLI patches `which` itself."""
    import shutil as _shutil
    real = _shutil.which
    model_clis = {"claude", "codex", "gemini", "opencode", "ollama"}
    monkeypatch.setattr(_shutil, "which",
                        lambda name, *a, **k: f"/usr/local/bin/{name}" if name in model_clis
                        else real(name, *a, **k))


@_pytest.fixture(autouse=True)
def _fresh_job_memory(monkeypatch):
    """The Reply pipeline keeps the posts each job set aside, the direct
    reply its query rotation cursor, and the content guard the posts of this
    run in its dedup memory, for the life of the process; every test starts
    with fresh ones."""
    from src.replies import reply_pipeline as _pipeline
    monkeypatch.setattr(_pipeline, "_skipped", {})
    from src.replies import direct_reply as _dr
    monkeypatch.setattr(_dr, "_QUERY_ROTATION_OFFSET", [0])
    from src.guards import content_guard as _cg
    monkeypatch.setattr(_cg, "_RECENT_NORM", [])
    yield


@_pytest.fixture(autouse=True)
def _fresh_editorial_memory(monkeypatch):
    """The Startup post window opened by main() and the trending posts
    cached for a Slot's retries live for the life of the process; every test
    starts with neither."""
    from src.editorial import editorial_bot as _eb, trending as _tr
    monkeypatch.setattr(_eb, "_startup_opened_at", None)
    monkeypatch.setattr(_tr, "_trend_cache", {})
    yield


@_pytest.fixture
def settings_override():
    """`settings_override(NAME=value, ...)`: the one way a test changes a
    setting of src/core/settings.py. Every value comes back after the test."""
    from src.core import settings
    with settings.overriding() as override:
        yield override


@_pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """config serves its settings through a module `__getattr__`. Undoing
    `monkeypatch.setattr(config, NAME, ...)` sets back the value it read, as a
    global that hides that `__getattr__` for good: once every fixture is torn
    down, drop it, so the next test reads the settings again."""
    yield
    from src.core import config
    for name in config._READ_AT_ACCESS:
        vars(config).pop(name, None)


@_pytest.fixture
def providers(monkeypatch, settings_override):
    """A fake adapter for every provider behind the real `run_llm`, each
    failing until a test gives it answers, every CLI installed, the
    ladder's settings at their defaults but an explicit codex fallback.
    `settings` lets a rank set its own."""
    from types import SimpleNamespace
    from src.core import llm_client as llm
    from tests.helpers import FakeAdapter

    calls = []
    fakes = {name: FakeAdapter(name, calls) for name in ("ollama", "codex", "gemini", "claude", "opencode")}
    monkeypatch.setattr(llm, "ADAPTERS", fakes)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    settings_override(AI_CLI="ollama", LLM_FALLBACK_CLI="codex", LLM_FALLBACK_MODEL="",
                      LLM_DISABLE_FALLBACK=False, CODEX_FALLBACK_MODEL="gpt-5.4-mini")
    return SimpleNamespace(calls=calls, monkeypatch=monkeypatch, settings=settings_override, **fakes)


@_pytest.fixture
def memory_ledger(monkeypatch):
    """An in-memory action ledger in place of the file, for tests that read it."""
    from src.guards import action_guard, ledger
    memory = ledger.MemoryLedger()
    monkeypatch.setattr(action_guard, "LEDGER", memory)
    return memory


@_pytest.fixture
def like_job(monkeypatch, memory_ledger, settings_override):
    """Live like_job on a scripted search page, its caps at their declared
    defaults; the real walk and like_tweet run."""
    from src.core import settings
    from src.x import safari, twitter_client as tc
    from tests.helpers import SearchPage

    monkeypatch.setenv("DRY_RUN", "0")
    settings_override(**{name: settings.DECLARED[name].default
                         for name in ("LIKE_BOT_PER_CYCLE", "LIKE_BOT_DAILY_CAP", "LIKE_BOT_CYCLE_SECONDS")})
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: None)
    monkeypatch.setattr(safari, "_scroll_page", lambda: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    state = {"page": SearchPage([]), "closed": 0, "ledger": memory_ledger}
    monkeypatch.setattr(tc, "_page_posts", lambda *a: state["page"](*a))

    def close_front_tab():
        state["closed"] += 1
    monkeypatch.setattr(safari, "close_front_tab", close_front_tab)
    return state
