"""Cross-cutting: the conftest walls keep every test off Safari and off the
production state files."""
import os

import pytest


def test_tests_cannot_write_production_state(tmp_path):
    """2026-06-09: a guard test mocked post_tweet but bot.py's bookkeeping
    (save_tweet + log_hotake) wrote its fixture text into the REAL
    tweet_history.json + engagement_log.csv — 21 phantom engagement rows and
    6 phantom history entries over two days, which a later self-eval
    misdiagnosed as a live repetition bug. The conftest _no_prod_state wall
    must redirect every measurement/state store to per-test tmp files."""
    import os
    from src.core import config as cfg
    from src.core import engagement_log as el, history as hist
    from src.guards import content_guard as cg

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for mod, attr in ((el, "ENGAGEMENT_LOG_FILE"), (hist, "HISTORY_FILE"),
                      (cg, "_HISTORY_FILE"), (cfg, "ACTION_LEDGER_FILE"),
                      (cfg, "REPLIED_FILE")):
        path = getattr(mod, attr)
        assert not os.path.abspath(path).startswith(repo + os.sep), \
            f"{mod.__name__}.{attr} points INSIDE the repo during tests: {path}"

    # A write through the normal API must land in tmp, not the repo.
    el.log_post("TEST-FIXTURE wall probe zz")
    hist.save_tweet("TEST-FIXTURE wall probe zz")
    real_log = os.path.join(repo, "engagement_log.csv")
    if os.path.exists(real_log):
        assert "wall probe zz" not in open(real_log).read(), \
            "test write leaked into the production engagement_log.csv"
    real_hist = os.path.join(repo, "tweet_history.json")
    if os.path.exists(real_hist):
        assert "wall probe zz" not in open(real_hist).read(), \
            "test write leaked into the production tweet_history.json"


def test_tests_cannot_spawn_osascript(monkeypatch):
    """twitter_client, scraper, safari_hygiene and several jobs call osascript through
    subprocess.run directly, past the _run_applescript wall: the conftest
    wall refuses those processes too."""
    import subprocess

    def _leak(*a, **k):
        raise RuntimeError("the conftest wall let a Safari process through")
    monkeypatch.setattr(subprocess, "_fork_exec", _leak, raising=False)
    monkeypatch.setattr(os, "posix_spawn", _leak)

    for argv in (["osascript", "-e", "return 1"], ["open", "-a", "Safari"],
                 ["pkill", "-x", "Safari"], "osascript -e 'return 1'"):
        with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
            subprocess.run(argv, shell=isinstance(argv, str))


def test_every_browser_path_goes_through_the_conftest_walls():
    """conftest walls `_run_applescript`, `_run_js` and `_paste_text` off in
    src.x.safari, which defines them, and `webbrowser.open` and
    `subprocess.Popen` on their modules. A module that binds one by name
    (`from .safari import _run_applescript`, `from subprocess import Popen`)
    keeps the real object past the wall, so twitter_client, scraper and the
    jobs reach them through their module (#118)."""
    import ast
    from pathlib import Path
    from src.x import safari

    walled = {"_run_applescript", "_run_js", "_paste_text"}
    for name in walled:
        with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
            getattr(safari, name)("return 1")

    root = Path(__file__).resolve().parent.parent
    problems = []
    for path in sorted([root / "main.py", *(root / "src").rglob("*.py"), *(root / "bin").glob("*.py")]):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if (alias.name in walled or node.module == "webbrowser"
                            or (node.module == "subprocess" and alias.name == "Popen")):
                        problems.append(f"{path.relative_to(root)}:{node.lineno}: imports {alias.name}")
            elif (isinstance(node, ast.FunctionDef) and node.name in walled
                  and path != Path(safari.__file__)):
                problems.append(f"{path.relative_to(root)}:{node.lineno}: defines {node.name}")
    assert not problems, "Browser primitive bound past the conftest walls:\n  " + "\n  ".join(problems)
