"""Best-effort git auto-push for autonomous agent state files.

User directive 2026-05-06: when an agent autonomously updates its
strategy / personality / dossiers, it should also commit + push that
state to git so the changes are visible in the repo + recoverable.

This module exposes ONE function, `auto_push`, which:
  - Stages a specific list of files.
  - Commits with a caller-supplied message (if anything changed).
  - Pushes to origin/<current_branch>.
  - Swallows every error (timeouts, auth issues, hooks) so the bot
    never crashes because git is unhappy.

Notes:
  - We never run `git add -A`. Agents pass exact paths so we can never
    accidentally commit secrets or local debug files.
  - We never use `--no-verify` (let pre-commit hooks run normally).
  - Pushes to the current branch; the autonomous mandate explicitly
    permits this (CLAUDE.md project_autonomous_mandate memory).
"""
import os
import subprocess
import traceback
from typing import Iterable

from .config import _PROJECT_ROOT
from .logger import log


def _run_git(args, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", _PROJECT_ROOT, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _current_branch() -> str:
    try:
        r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
        if r.returncode == 0:
            return r.stdout.strip() or "main"
    except Exception:
        pass
    return "main"


def auto_push(file_paths: Iterable[str], commit_message: str) -> bool:
    """Stage `file_paths`, commit if anything changed, push.

    Returns True iff a commit + push both succeeded. False otherwise
    (including the no-changes case). Never raises.
    """
    try:
        # Resolve to absolute paths and keep only those that exist.
        abs_paths = []
        for p in file_paths:
            if not p:
                continue
            ap = p if os.path.isabs(p) else os.path.join(_PROJECT_ROOT, p)
            if os.path.exists(ap):
                abs_paths.append(ap)
        if not abs_paths:
            return False

        # Are any of these dirty?
        st = _run_git(["status", "--porcelain", "--", *abs_paths], timeout=10)
        if st.returncode != 0:
            log.info(f"[GIT] status check failed: {st.stderr[:200]}")
            return False
        if not st.stdout.strip():
            return False  # nothing to commit

        # Stage exact paths only.
        add = _run_git(["add", "--", *abs_paths], timeout=10)
        if add.returncode != 0:
            log.info(f"[GIT] add failed: {add.stderr[:200]}")
            return False

        # Commit.
        commit = _run_git(["commit", "-m", commit_message], timeout=20)
        if commit.returncode != 0:
            # Pre-commit hook may have rejected the commit. Log and bail
            # without pushing — we don't override hooks autonomously.
            err = (commit.stderr or commit.stdout or "")[:300]
            log.info(f"[GIT] commit rejected: {err}")
            return False

        # Push.
        branch = _current_branch()
        push = _run_git(["push", "origin", branch], timeout=60)
        if push.returncode != 0:
            err = (push.stderr or push.stdout or "")[:300]
            log.info(f"[GIT] push failed ({branch}): {err}")
            return False

        log.info(f"[GIT] auto-pushed: {commit_message.splitlines()[0][:90]}")
        return True
    except Exception:
        log.info("[GIT] auto_push exception:")
        traceback.print_exc()
        return False
