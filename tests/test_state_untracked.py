"""Cross-cutting: git ignores the live state and tracks the Operator's files.

A tracked state file is overwritten by the next `git checkout`, `reset` or
`pull` in the live checkout, and a stale committed ledger once stood ready
to reset today's ceiling (#193). The state lives under state/<BOT_ACCOUNT>/
since #207, the process files (bot.log...) at the root. The Operator's files
stay tracked, in the Account folder (#203, #206).
"""
import importlib
import os
import pkgutil
import subprocess
from pathlib import Path

import src

REPO = Path(__file__).resolve().parent.parent

OPERATOR_FILES = ("accounts/theaishrink/respect_list.json", "accounts/theaishrink/whitelist.json",
                  "accounts/theaishrink/following_baseline.json",
                  "accounts/theaishrink/voice_fr.md", "accounts/theaishrink/voice_en.md")
# State files written outside src/, which the scan below cannot see.
WRITTEN_BY_BIN = ("mass_unfollow_results.json",)
# State files declared after #207: they never lived at the root, so
# bin/migrate_state.py has nothing of theirs to move.
BORN_AFTER_207 = frozenset()


def _modules():
    return [importlib.import_module(m.name) for m in pkgutil.walk_packages(src.__path__, "src.")]


def _account_state_files() -> set:
    """The names under state/<BOT_ACCOUNT>/: every StateFile and StatePath.
    Module attributes, not state_store._DECLARED: tests declare files too."""
    from src.core import state_store
    return {v.name for m in _modules() for v in vars(m).values()
            if isinstance(v, (state_store.StateFile, state_store.StatePath))} | set(WRITTEN_BY_BIN)


def _process_files() -> set:
    """Files kept at the project root: any module constant holding a path
    there (bot.log, autonomous_log.md)."""
    from src.core import config
    root = os.path.normpath(config._PROJECT_ROOT)
    return {os.path.basename(path) for m in _modules() for v in vars(m).values()
            if isinstance(v, str)
            for path in [os.path.normpath(v)]
            if os.path.isabs(path) and os.path.dirname(path) == root}


def _ignored(names) -> set:
    # Without --no-index, a tracked file is never reported as ignored.
    result = subprocess.run(["git", "check-ignore", "--", *names], cwd=REPO,
                            capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.split())


def _exposed(paths) -> list:
    return sorted(set(paths) - _ignored(sorted(paths)))


def test_every_state_file_is_ignored_by_git():
    state = _account_state_files()
    assert {"action_ledger.json", "following_count.json", "personality.json",
            "replied_tweets.json", "editorial_review.jsonl", "engagement_log.csv",
            "directives.md", "whitelist_discovered.json"} <= state
    exposed = _exposed({f"state/theaishrink/{name}" for name in state}
                       | {"state/another_account/action_ledger.json"})
    assert not exposed, ("State files git tracks or does not ignore; state/ must stay in "
                         ".gitignore:\n  " + "\n  ".join(exposed))


def test_the_process_files_at_the_root_are_ignored_by_git():
    process = _process_files()
    assert {"bot.log", "autonomous_log.md"} <= process
    assert not _exposed(process | {"bot.lock"})


def test_the_state_left_at_the_root_stays_ignored():
    """A checkout not migrated yet (#207) keeps its state at the root, and
    bin/carry_state.sh restore puts files back there: git must ignore them,
    or a pull could overwrite them."""
    from src.core import state_store
    assert not _exposed(set(state_store.LEGACY_FILES))


def test_the_migration_moves_every_state_file_of_207():
    from src.core import state_store
    missing = sorted(_account_state_files() - BORN_AFTER_207 - set(state_store.LEGACY_FILES))
    assert not missing, f"state files bin/migrate_state.py would leave at the root: {missing}"


def test_the_operators_files_stay_tracked():
    tracked = subprocess.run(["git", "ls-files", "--", *OPERATOR_FILES], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.split()
    assert sorted(tracked) == sorted(OPERATOR_FILES)
