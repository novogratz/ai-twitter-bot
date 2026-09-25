"""Cross-cutting: git ignores the live state and tracks the Operator's files.

A tracked state file is overwritten by the next `git checkout`, `reset` or
`pull` in the live checkout, and a stale committed ledger once stood ready
to reset today's ceiling (#193). The Operator's files stay tracked until
their own tickets move them (#206 for whitelist.json).
"""
import importlib
import os
import pkgutil
import subprocess
from pathlib import Path

import src

REPO = Path(__file__).resolve().parent.parent

OPERATOR_FILES = ("respect_list.json", "whitelist.json", "accounts/theaishrink/voice_fr.md",
                  "accounts/theaishrink/voice_en.md", "accounts/theaishrink/relations/bestie.md",
                  "accounts/theaishrink/relations/buddy.md", "accounts/theaishrink/relations/graphseo.md")
# Root files written outside src/, which the scan below cannot see.
WRITTEN_BY_BIN = ("mass_unfollow_results.json",)


def _declared_state_files() -> set:
    # Module attributes, not state_store._DECLARED: tests declare files too.
    modules = [importlib.import_module(m.name)
               for m in pkgutil.walk_packages(src.__path__, "src.")]
    from src.core import config, state_store

    # The conftest wall moves the ledger, replied and engagement paths under
    # the temp state_store.ROOT; the other paths keep the repo root.
    roots = {os.path.normpath(config._PROJECT_ROOT), os.path.normpath(state_store.ROOT)}
    stored = {v.name for m in modules for v in vars(m).values()
              if isinstance(v, state_store.StateFile)}
    # Files kept outside the store: any module constant holding a path at
    # the root (ACTION_LEDGER_FILE, AUDIT_FILE, LOG_FILE...).
    outside_the_store = {os.path.basename(path) for m in modules for v in vars(m).values()
                         if isinstance(v, (str, os.PathLike))
                         for path in [os.path.normpath(os.fspath(v))]
                         if os.path.isabs(path) and os.path.dirname(path) in roots}
    return stored | outside_the_store | set(WRITTEN_BY_BIN)


def _ignored(names) -> set:
    # Without --no-index, a tracked file is never reported as ignored.
    result = subprocess.run(["git", "check-ignore", "--", *names], cwd=REPO,
                            capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.split())


def test_every_declared_state_file_is_ignored_by_git():
    state = _declared_state_files() - set(OPERATOR_FILES)
    assert {"action_ledger.json", "following_count.json", "personality.json",
            "replied_tweets.json", "editorial_review.jsonl", "bot.log",
            "engagement_log.csv", "autonomous_log.md", "directives.md"} <= state
    exposed = sorted(state - _ignored(sorted(state)))
    assert not exposed, (
        "State files git tracks or does not ignore; add them to .gitignore and "
        "take them out of the index with docs/OPERATIONS.md#deploying-issue-193:\n  "
        + "\n  ".join(exposed))


def test_the_operators_files_stay_tracked():
    tracked = subprocess.run(["git", "ls-files", "--", *OPERATOR_FILES], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.split()
    assert sorted(tracked) == sorted(OPERATOR_FILES)
