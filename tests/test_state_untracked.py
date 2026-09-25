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

OPERATOR_FILES = ("respect_list.json", "whitelist.json", "core_identity.md", "core_identity_en.md")


def _declared_state_files() -> set:
    # Module attributes, not state_store._DECLARED: tests declare files too.
    modules = [importlib.import_module(m.name)
               for m in pkgutil.walk_packages(src.__path__, "src.")]
    from src.core import config, evolution_store, health, logger, state_store
    from src.editorial import editorial_bot, reach_report

    outside_the_store = (config.ACTION_LEDGER_FILE, config.REPLIED_FILE,
                         config.ENGAGEMENT_LOG_FILE, editorial_bot.AUDIT_FILE,
                         reach_report.REPORT_MARKDOWN, health.AUTONOMOUS_LOG_FILE,
                         evolution_store.DIRECTIVES_FILE, logger.LOG_FILE,
                         "mass_unfollow_results.json")
    stored = {v.name for m in modules for v in vars(m).values()
              if isinstance(v, state_store.StateFile)}
    return stored | {os.path.basename(p) for p in outside_the_store}


def _ignored(names) -> set:
    # Without --no-index, a tracked file is never reported as ignored.
    result = subprocess.run(["git", "check-ignore", "--", *names], cwd=REPO,
                            capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.split())


def test_every_declared_state_file_is_ignored_by_git():
    state = _declared_state_files() - set(OPERATOR_FILES)
    assert {"action_ledger.json", "following_count.json", "personality.json",
            "replied_tweets.json", "editorial_review.jsonl"} <= state
    exposed = sorted(state - _ignored(sorted(state)))
    assert not exposed, (
        "State files git tracks or does not ignore; add them to .gitignore and "
        "take them out of the index with docs/OPERATIONS.md#deploying-issue-193:\n  "
        + "\n  ".join(exposed))


def test_the_operators_files_stay_tracked():
    tracked = subprocess.run(["git", "ls-files", "--", *OPERATOR_FILES], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.split()
    assert sorted(tracked) == sorted(OPERATOR_FILES)
