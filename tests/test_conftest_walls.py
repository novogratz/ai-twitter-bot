"""Cross-cutting: the conftest walls keep every test off Safari and off the
production state files."""
import ast
import os
from pathlib import Path

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
    from src.core import engagement_log as el, history as hist, state_store

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for where in (state_store.root(), state_store.LEGACY_DIR):
        assert not os.path.abspath(where).startswith(repo + os.sep) \
            and os.path.abspath(where) != repo, f"state in the repo during tests: {where}"
    for mod, attr in ((cfg, "ENGAGEMENT_LOG_FILE"), (cfg, "ACTION_LEDGER_FILE"),
                      (cfg, "REPLIED_FILE")):
        path = os.fspath(getattr(mod, attr))
        assert not os.path.abspath(path).startswith(repo + os.sep), \
            f"{mod.__name__}.{attr} points INSIDE the repo during tests: {path}"

    # A write through the normal API must land in tmp, not the repo.
    el.log_reply("", "TEST-FIXTURE wall probe zz")
    hist.save_tweet("TEST-FIXTURE wall probe zz")
    state = os.path.join(repo, "state")
    accounts = sorted(os.listdir(state)) if os.path.isdir(state) else []
    for folder in [repo, *(os.path.join(state, name) for name in accounts)]:
        for name in ("engagement_log.csv", "tweet_history.json"):
            real = os.path.join(folder, name)
            if os.path.exists(real):
                assert "wall probe zz" not in open(real).read(), \
                    f"test write leaked into the production {real}"


def test_tests_cannot_spawn_osascript(monkeypatch):
    """Past the `_run_applescript` and `_run_js` walls, safari_hygiene still
    quits Safari with subprocess.run(["osascript", ...]) and relaunches it
    with `open` and `pkill`: the conftest wall refuses those processes too."""
    import subprocess

    def _leak(*a, **k):
        raise RuntimeError("the conftest wall let a Safari process through")
    monkeypatch.setattr(subprocess, "_fork_exec", _leak, raising=False)
    monkeypatch.setattr(os, "posix_spawn", _leak)

    for argv in (["osascript", "-e", "return 1"], ["open", "-a", "Safari"],
                 ["pkill", "-x", "Safari"], "osascript -e 'return 1'"):
        with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
            subprocess.run(argv, shell=isinstance(argv, str))


WALLED = {"_run_applescript", "_run_js", "_paste_text", "open_url"}
# Not walled, but tests patch them on src.x.safari: a module that binds one
# by name keeps the real object, and its tests had to patch it there too.
BY_MODULE = {"_safari_lock", "_scroll_page", "close_front_tab"}
SAFARI = "src/x/safari.py"
# The one direct osascript call that stays: safari_hygiene quits Safari
# itself, because the Safari being quit may be wedged, and
# its own timeout guarantees the pkill that follows runs, where
# `_run_applescript` bounds a run only when its caller asks.
OWN_OSASCRIPT = {"src/x/safari_hygiene.py"}


def _docstrings(tree):
    """The first statement of a module, class or function, when a string."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                found.add(first.value)
    return found


def browser_path_problems(root, path):
    """Every way `path` reaches Safari past the conftest walls."""
    rel = path.relative_to(root).as_posix()
    tree = ast.parse(path.read_text())
    docstrings = _docstrings(tree)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "webbrowser":
                    problems.append(f"{rel}:{node.lineno}: opens pages past safari.open_url")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.name in WALLED or alias.name in BY_MODULE or node.module == "webbrowser"
                        or (node.module == "subprocess" and alias.name == "Popen")):
                    problems.append(f"{rel}:{node.lineno}: imports {alias.name}")
        elif isinstance(node, ast.FunctionDef) and node.name in WALLED and rel != SAFARI:
            problems.append(f"{rel}:{node.lineno}: defines {node.name}")
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and rel != SAFARI and node not in docstrings):
            words = node.value.split()
            if "do javascript" in node.value.lower():
                problems.append(f"{rel}:{node.lineno}: runs do JavaScript past safari._run_js")
            if words and os.path.basename(words[0]) == "osascript" and rel not in OWN_OSASCRIPT:
                problems.append(f"{rel}:{node.lineno}: spawns osascript")
    return problems


def test_every_browser_path_goes_through_the_conftest_walls():
    """conftest walls `_run_applescript`, `_run_js`, `_paste_text` and
    `open_url` off in src.x.safari, which defines them, and `webbrowser.open`
    and `subprocess.Popen` on their modules. A module that binds one by name
    (`from .safari import _run_applescript`, `from subprocess import Popen`)
    keeps the real object past the wall, so twitter_client, scraper and the
    jobs reach them through their module (#118). They reach `_safari_lock`,
    `_scroll_page` and `close_front_tab` through it too, so a test patches
    them on src.x.safari alone (#252). Page JavaScript runs only through
    `safari._run_js`, and only safari.py and the files in
    OWN_OSASCRIPT spawn `osascript` (#144). Pages open only through
    `safari.open_url`: `webbrowser` follows the default browser, and a page
    opened in Firefox left `_run_js` reading Safari's front tab."""
    from src.x import safari

    for name in WALLED:
        with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
            getattr(safari, name)("return 1")

    root = Path(__file__).resolve().parent.parent
    assert Path(safari.__file__) == root / SAFARI
    paths = sorted([root / "main.py", *(root / "src").rglob("*.py"), *(root / "bin").glob("*.py")])
    problems = [p for path in paths for p in browser_path_problems(root, path)]
    assert not problems, "Browser primitive bound past the conftest walls:\n  " + "\n  ".join(problems)


# --- the detector itself, on synthetic files --------------------------------

def _problems(tmp_path, rel, text):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return browser_path_problems(tmp_path, target)


def test_osascript_is_matched_by_program_name(tmp_path):
    problems = _problems(tmp_path, "src/job.py", (
        "import subprocess\n"
        "subprocess.run(['/usr/bin/osascript', '-e', 'return 1'])\n"
        "subprocess.run('osascript\\t-e x', shell=True)\n"
        "NAME = 'osascript'\n"
        "LABEL = 'osascripts are slow'\n"
        "EMPTY = ''\n"
    ))
    assert sorted(problems) == ["src/job.py:2: spawns osascript", "src/job.py:3: spawns osascript",
                                "src/job.py:4: spawns osascript"]


def test_do_javascript_is_matched_in_any_case(tmp_path):
    problems = _problems(tmp_path, "src/job.py", (
        "A = 'tell application \"Safari\" to do JavaScript js'\n"
        "B = 'DO JAVASCRIPT js in current tab'\n"
        "C = 'do javascript js'\n"
        "D = 'do not run JavaScript'\n"
    ))
    assert sorted(problems) == [f"src/job.py:{n}: runs do JavaScript past safari._run_js"
                                for n in (1, 2, 3)]


def test_webbrowser_is_matched_in_every_import_form(tmp_path):
    problems = _problems(tmp_path, "src/job.py", (
        "import webbrowser\n"
        "import os, webbrowser as wb\n"
        "from webbrowser import open\n"
        "from .safari import open_url\n"
        "import webbrowser_helpers\n"
    ))
    assert sorted(problems) == ["src/job.py:1: opens pages past safari.open_url",
                                "src/job.py:2: opens pages past safari.open_url",
                                "src/job.py:3: imports open",
                                "src/job.py:4: imports open_url"]


def test_safari_primitives_are_matched_when_imported_by_name(tmp_path):
    problems = _problems(tmp_path, "src/job.py", (
        "from ..x.safari import _safari_lock, close_front_tab\n"
        "from .safari import _scroll_page\n"
        "from . import safari\n"
        "from .safari import restart_safari\n"
    ))
    assert sorted(problems) == ["src/job.py:1: imports _safari_lock",
                                "src/job.py:1: imports close_front_tab",
                                "src/job.py:2: imports _scroll_page"]


def test_docstrings_are_not_browser_paths(tmp_path):
    problems = _problems(tmp_path, "src/job.py", (
        '"""osascript runs do JavaScript: a module docstring."""\n'
        "class Job:\n"
        '    """osascript, do JavaScript: a class docstring."""\n'
        "    def run(self):\n"
        '        """osascript, do JavaScript: a method docstring."""\n'
        "        'osascript -e x'\n"
        "async def later():\n"
        '    """osascript: an async function docstring."""\n'
    ))
    assert problems == ["src/job.py:6: spawns osascript"]


def test_safari_and_the_listed_exceptions_may_spawn_osascript(tmp_path):
    body = "A = ['osascript', '-e', 'do JavaScript js']\n"
    assert _problems(tmp_path, SAFARI, body) == []
    assert _problems(tmp_path, "src/x/safari_hygiene.py", body) == [
        "src/x/safari_hygiene.py:1: runs do JavaScript past safari._run_js"]
    assert sorted(_problems(tmp_path, "bin/mass_unfollow.py", body)) == [
        "bin/mass_unfollow.py:1: runs do JavaScript past safari._run_js",
        "bin/mass_unfollow.py:1: spawns osascript"]
