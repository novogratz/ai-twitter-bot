"""bin/carry_state.sh carries the live state across the pull of issue #193.

Each test replays docs/OPERATIONS.md#deploying-issue-193 on a throwaway
clone: its HEAD still tracks the state files, origin/main takes them out of
the index and deletes an orphan.
"""
import fcntl
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "carry_state.sh"

STATE = ("action_ledger.json", "following_count.json")
ORPHAN = "daily_state.json"
LIVE = {
    "action_ledger.json": '{"action": "reply"}\n{"action": "like"}\n',
    "following_count.json": '{"count": 812}',
    ORPHAN: '{"day": "2026-09-24"}',
}


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=_env(), check=True,
                          capture_output=True, text=True).stdout


def _carry(cwd, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, env=_env(),
                          capture_output=True, text=True, check=False)


def _sums(checkout, names):
    return {n: hashlib.sha256((checkout / n).read_bytes()).hexdigest() for n in names}


@pytest.fixture
def checkout(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / ".gitignore").write_text("bot.lock\n")
    (origin / "respect_list.json").write_text("[]")
    (origin / "action_ledger.json").write_text("[]")
    (origin / "following_count.json").write_text('{"count": 700}')
    (origin / ORPHAN).write_text("{}")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "state tracked")
    _git(origin, "rm", "-q", "--cached", *STATE)
    _git(origin, "rm", "-q", ORPHAN)
    (origin / ".gitignore").write_text("bot.lock\n" + "".join(f"{n}\n" for n in STATE))
    _git(origin, "add", ".gitignore")
    _git(origin, "commit", "-q", "-m", "state untracked")

    live = tmp_path / "live"
    _git(tmp_path, "clone", "-q", str(origin), str(live))
    _git(live, "reset", "-q", "--hard", "HEAD~1")
    for name, text in LIVE.items():
        (live / name).write_text(text)
    return live


def _put_back_committed_copies(checkout, backup):
    names = [line.split()[1] for line in (backup / "SHA256SUMS").read_text().splitlines()]
    _git(checkout, "checkout", "HEAD", "--", *names)


def test_save_pull_restore_keeps_the_live_state(checkout, tmp_path):
    before = _sums(checkout, STATE)
    backup = tmp_path / "backup"

    saved = _carry(checkout, "save", str(backup), "origin/main")
    assert saved.returncode == 0, saved.stderr
    _put_back_committed_copies(checkout, backup)
    _git(checkout, "pull", "-q", "--ff-only", "origin", "main")
    assert not any((checkout / n).exists() for n in STATE)

    restored = _carry(checkout, "restore", str(backup))
    assert restored.returncode == 0, restored.stderr
    assert "restored 2 files; 2 match the backup" in restored.stdout
    assert f"left out: {ORPHAN}" in restored.stdout
    assert _sums(checkout, STATE) == before
    assert not (checkout / ORPHAN).exists()
    assert _git(checkout, "status", "--short") == ""


def test_restore_before_the_pull_fails_and_copies_nothing(checkout, tmp_path):
    backup = tmp_path / "backup"
    assert _carry(checkout, "save", str(backup), "origin/main").returncode == 0
    _put_back_committed_copies(checkout, backup)

    restored = _carry(checkout, "restore", str(backup))

    assert restored.returncode != 0
    assert "pull not done" in restored.stderr
    assert (checkout / "action_ledger.json").read_text() == "[]"


def test_a_second_save_after_the_committed_copies_are_back_is_refused(checkout, tmp_path):
    backup = tmp_path / "backup"
    assert _carry(checkout, "save", str(backup), "origin/main").returncode == 0
    _put_back_committed_copies(checkout, backup)

    again = _carry(checkout, "save", str(backup), "origin/main")
    assert again.returncode != 0
    assert "not empty" in again.stderr

    elsewhere = _carry(checkout, "save", str(tmp_path / "other"), "origin/main")
    assert elsewhere.returncode != 0
    assert "equals its committed copy" in elsewhere.stderr
    assert not (tmp_path / "other").exists()

    forced = _carry(checkout, "save", "--force", str(tmp_path / "forced"), "origin/main")
    assert forced.returncode == 0, forced.stderr


def test_save_and_restore_refuse_while_bot_lock_is_held(checkout, tmp_path):
    backup = tmp_path / "backup"
    with open(checkout / "bot.lock", "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        saved = _carry(checkout, "save", str(backup), "origin/main")
        restored = _carry(checkout, "restore", str(backup))

    for result in (saved, restored):
        assert result.returncode != 0
        assert "bot.lock is held" in result.stderr
    assert not backup.exists()
    assert _carry(checkout, "save", str(backup), "origin/main").returncode == 0


def test_save_refuses_while_a_main_py_runs_from_the_checkout(checkout, tmp_path):
    (checkout / "main.py").write_text("import time\ntime.sleep(60)\n")
    bot = subprocess.Popen([sys.executable, "main.py"], cwd=checkout)
    try:
        saved = _carry(checkout, "save", str(tmp_path / "backup"), "origin/main")
    finally:
        bot.kill()
        bot.wait()

    assert saved.returncode != 0
    assert f"PID {bot.pid}" in saved.stderr


def test_a_restore_on_a_migrated_checkout_stops_the_start(checkout, tmp_path, monkeypatch):
    """Since #207 the state lives in state/theaishrink/: a restore puts the
    saved copies back at the root, and the start must see the one that
    differs from its copy there."""
    from src.core import state_store
    backup = tmp_path / "backup"
    assert _carry(checkout, "save", str(backup), "origin/main").returncode == 0
    _put_back_committed_copies(checkout, backup)
    _git(checkout, "pull", "-q", "--ff-only", "origin", "main")
    migrated = checkout / "state" / "theaishrink"
    migrated.mkdir(parents=True)
    (migrated / "action_ledger.json").write_text(LIVE["action_ledger.json"] + '{"action": "post"}\n')
    (migrated / "following_count.json").write_text(LIVE["following_count.json"])

    restored = _carry(checkout, "restore", str(backup))

    assert restored.returncode == 0, restored.stderr
    monkeypatch.setattr(state_store, "PROJECT_ROOT", str(checkout))
    monkeypatch.setattr(state_store, "LEGACY_DIR", str(checkout))
    with pytest.raises(state_store.Unmigrated, match=r"different bytes: action_ledger\.json\. "):
        state_store.require_migrated()
