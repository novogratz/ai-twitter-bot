"""Issue #207: the state moves from the project root to state/theaishrink/.

The root state is theaishrink's, the only Account before #207, whichever
Account BOT_ACCOUNT names. bin/migrate_state.py moves each file without
recreating it, on fixtures shaped like the live files; main.py and the
scripts that write state refuse to start while a state file waits at the
root and its new place is empty or holds other bytes.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

from src.core import state_store

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "migrate_state.py"

# Bytes as the live files hold them, none rewritten by a JSON round trip: a
# ledger whose last row lacks its newline, key order and spacing of their
# own, a non-UTF-8 byte.
LIVE = {
    "action_ledger.json": b'{"ts": "2026-09-25T09:00:00-04:00", "action": "post"}\n'
                          b'{"ts": "2026-09-25T09:30:00-04:00", "action": "reply", "target": "x"}',
    "replied_tweets.json": b'[\n  "2063500000000000001"\n]',
    "following_count.json": b'{"updated": "2026-09-24T07:55:17", "count": 812}',
    "whitelist_discovered.json": b'["unusual_whales","Polymarket"]\n',
    "personality.json": '{"micode": {"notes": ["très drôle"]}}'.encode(),
    "engagement_log.csv": b"timestamp,type,text\n2026-09-25T09:00:00,reply,\"hi, there\"\n",
    "editorial_review.jsonl": b'{"slot": "07:15", "approved": false}\n',
    "editorial_reach.md": b"# AI original-post reach\n",
    "directives.md": b"legacy \xff directives\n",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def script(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("migrate_state_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    return mod


@pytest.fixture
def checkout(monkeypatch, tmp_path, unwalled):
    """A checkout before #207: the state at the project root, state/ absent."""
    project = tmp_path / "project"
    project.mkdir()
    for name, data in LIVE.items():
        (project / name).write_bytes(data)
    os.chmod(project / "action_ledger.json", 0o600)
    target = project / "state" / "theaishrink"
    monkeypatch.setattr(state_store, "PROJECT_ROOT", str(project))
    monkeypatch.setattr(state_store, "LEGACY_DIR", str(project))
    monkeypatch.setattr(state_store, "root", unwalled["state_root"])
    assert state_store.root() == str(target)
    return project, target


@pytest.fixture
def other_account(operator_folder, settings_override):
    """BOT_ACCOUNT=autre, a second Account under accounts/."""
    shutil.copytree(operator_folder, operator_folder.parent / "autre")
    settings_override(BOT_ACCOUNT="autre")
    assert state_store.root().endswith(os.path.join("state", "autre"))
    return "autre"


def test_each_file_moves_byte_for_byte_and_none_is_recreated(script, checkout):
    project, target = checkout
    before = {name: (_sha(project / name), (project / name).stat()) for name in LIVE}

    report = script.migrate()

    assert sorted(os.listdir(target)) == sorted(LIVE), "only the root files, no default created"
    for name, (digest, stat) in before.items():
        assert not (project / name).exists()
        moved = target / name
        assert _sha(moved) == digest
        assert moved.read_bytes() == LIVE[name]
        # The same inode: the file itself moved, it was not written anew.
        assert moved.stat().st_ino == stat.st_ino
        assert moved.stat().st_mtime_ns == stat.st_mtime_ns
    assert (target / "action_ledger.json").stat().st_mode & 0o777 == 0o600
    assert report[0] == ("the root state is theaishrink's, the only Account before issue #207: "
                         "it goes to state/theaishrink/, whatever BOT_ACCOUNT names")
    assert report[-1] == f"moved {len(LIVE)} files, 0 already there; the root holds no state file"
    assert state_store.unmigrated() == []


def test_a_second_run_does_nothing(script, checkout):
    project, target = checkout
    script.migrate()
    stats = {name: (target / name).stat() for name in LIVE}

    assert script.migrate() == [
        "nothing to move: no state file left at the project root, the state is in "
        "state/theaishrink/"]

    for name, stat in stats.items():
        now = (target / name).stat()
        assert (now.st_ino, now.st_mtime_ns, now.st_size) == (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    assert not any((project / name).exists() for name in LIVE)


def test_a_destination_that_differs_refuses_before_any_move(script, checkout):
    project, target = checkout
    target.mkdir(parents=True)
    (target / "replied_tweets.json").write_text("[]")

    with pytest.raises(script.Refused, match="replied_tweets.json exists and differs"):
        script.migrate()

    assert all((project / name).read_bytes() == data for name, data in LIVE.items())
    assert os.listdir(target) == ["replied_tweets.json"]
    assert (target / "replied_tweets.json").read_text() == "[]"


def test_an_identical_destination_only_loses_its_root_copy(script, checkout):
    """A run cut between the link and the unlink: the next one finishes."""
    project, target = checkout
    target.mkdir(parents=True)
    (target / "action_ledger.json").write_bytes(LIVE["action_ledger.json"])

    report = script.migrate()

    assert any(line.startswith("action_ledger.json: already in state/theaishrink/, identical")
               for line in report)
    assert not (project / "action_ledger.json").exists()
    assert (target / "action_ledger.json").read_bytes() == LIVE["action_ledger.json"]
    assert report[-1] == f"moved {len(LIVE) - 1} files, 1 already there; the root holds no state file"


def test_a_root_entry_that_is_no_regular_file_refuses(script, checkout, tmp_path):
    project, target = checkout
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}")
    (project / "pin_history.json").symlink_to(elsewhere)

    with pytest.raises(script.Refused, match="pin_history.json at the project root is not a regular file"):
        script.migrate()
    assert not target.exists()


def test_it_refuses_while_the_bot_holds_its_lock(script, checkout, tmp_path, monkeypatch, capsys):
    project, target = checkout
    monkeypatch.setattr(sys, "argv", ["migrate_state.py"])
    with open(tmp_path / "bot.lock", "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as exit_:
            script.main()
    assert exit_.value.code == 1
    assert "bot.lock is held" in capsys.readouterr().err
    assert all((project / name).exists() for name in LIVE)
    assert not target.exists()


def test_main_reports_each_move(script, checkout, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["migrate_state.py"])
    script.main()
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("action_ledger.json: moved to state/theaishrink/, sha256 ") for line in out)


def test_another_account_moves_the_root_state_to_theaishrink(script, checkout, other_account,
                                                             monkeypatch, capsys):
    """The root state is theaishrink's: run with BOT_ACCOUNT=autre, the move
    must not hand theaishrink's ledger to autre."""
    project, target = checkout
    monkeypatch.setattr(sys, "argv", ["migrate_state.py"])

    script.main()

    out = capsys.readouterr().out
    assert "it goes to state/theaishrink/, whatever BOT_ACCOUNT names" in out
    assert sorted(os.listdir(target)) == sorted(LIVE)
    assert not (project / "state" / "autre").exists()


def test_the_respect_list_is_not_reinstalled(script, checkout, operator_folder):
    """The respect list was recreated with its defaults at import before
    #206: moving the state must neither bring a default back nor touch the
    Operator's file, missing or old."""
    project, target = checkout
    (project / "respect_list.json").write_text('{"handles": {"old": {}}}')
    (operator_folder / "respect_list.json").unlink()

    script.migrate()
    from src.core import personality_store  # noqa: F401  (imported at start by main.py)
    from src.guards import respect_list  # noqa: F401

    assert not (operator_folder / "respect_list.json").exists()
    assert not (target / "respect_list.json").exists()
    assert (project / "respect_list.json").read_text() == '{"handles": {"old": {}}}'


# --- the start refuses while a state file waits at the root ---------------------


class _Started(Exception):
    pass


@pytest.fixture
def start(monkeypatch):
    """main.main() with `flags`, stopped at the scheduler's start."""
    import main

    def lock():
        raise _Started

    monkeypatch.setattr(main, "_acquire_singleton_lock", lock)

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        main.main()
    return run


@pytest.mark.parametrize("flags", [(), ("--dry-run",), ("--reply-only",)])
def test_a_state_file_left_at_the_root_stops_the_start(checkout, start, flags, capsys, caplog):
    project, target = checkout
    target.mkdir(parents=True)
    (target / "personality.json").write_bytes(LIVE["personality.json"])

    with pytest.raises(SystemExit) as exit_:
        start(*flags)

    message = str(exit_.value.code)
    assert message.startswith("Refusing to start: state files still at the project root")
    assert "action_ledger.json" in message and "personality.json" not in message
    assert "bin/migrate_state.py" in message
    assert "[STATE] Refusing to start" in caplog.text
    assert capsys.readouterr().out == ""
    assert os.listdir(target) == ["personality.json"], "nothing created before the refusal"


def test_the_start_goes_on_once_migrated(script, checkout, start, capsys):
    script.migrate()
    start("--dry-run")
    assert json.loads(capsys.readouterr().out)["jobs"]
    with pytest.raises(_Started):
        start()


def test_another_account_does_not_start_beside_the_unmigrated_root(checkout, other_account,
                                                                   start):
    project, target = checkout
    (project / "state" / "autre").mkdir(parents=True)
    for name, data in LIVE.items():
        (project / "state" / "autre" / name).write_bytes(data)

    with pytest.raises(SystemExit) as exit_:
        start("--dry-run")

    message = str(exit_.value.code)
    assert message.startswith("Refusing to start: state files still at the project root, "
                              "missing from state/theaishrink/")
    assert "action_ledger.json" in message and "bin/migrate_state.py" in message
    assert not target.exists()


def test_theaishrink_starts_on_its_ledger_after_a_move_run_as_another_account(
        script, checkout, other_account, start, capsys, settings_override):
    project, target = checkout
    script.migrate()

    settings_override(BOT_ACCOUNT="theaishrink")
    start("--dry-run")

    assert json.loads(capsys.readouterr().out)["jobs"]
    from src.core import config
    assert os.fspath(config.ACTION_LEDGER_FILE) == str(target / "action_ledger.json")
    assert (target / "action_ledger.json").read_bytes() == LIVE["action_ledger.json"]
    from src.guards import action_guard
    assert action_guard._ledger().count(action_guard.POST, date(2026, 9, 25)) == 1
    assert action_guard._ledger().count(action_guard.REPLY, date(2026, 9, 25)) == 1


@pytest.mark.parametrize("flags", [("--dry-run",), ()])
def test_a_file_in_both_places_with_other_bytes_stops_the_start(checkout, start, flags, caplog):
    """A partial rollback, or carry_state.sh restore on a migrated checkout:
    the root copy may hold today's rows."""
    project, target = checkout
    target.mkdir(parents=True)
    for name, data in LIVE.items():
        (target / name).write_bytes(data)
    (project / "action_ledger.json").write_bytes(
        LIVE["action_ledger.json"] + b'\n{"ts": "2026-09-25T10:00:00-04:00", "action": "post"}\n')

    with pytest.raises(SystemExit) as exit_:
        start(*flags)

    message = str(exit_.value.code)
    assert message.startswith("Refusing to start: state files both at the project root and in "
                              "state/theaishrink/, with different bytes: action_ledger.json.")
    assert "move the other outside the checkout" in message
    assert "docs/OPERATIONS.md#deploying-issue-207" in message
    assert "missing from" not in message
    assert "[STATE] Refusing to start" in caplog.text


def test_a_file_in_both_places_with_the_same_bytes_only_warns(checkout, start, capsys, caplog):
    project, target = checkout
    target.mkdir(parents=True)
    for name, data in LIVE.items():
        (target / name).write_bytes(data)

    start("--dry-run")

    assert json.loads(capsys.readouterr().out)["jobs"]
    assert ("[STATE] action_ledger.json is both at the project root and in state/theaishrink/, "
            "identical: bin/migrate_state.py removes the root copy.") in caplog.text


def test_the_state_writing_scripts_refuse_too(checkout, monkeypatch, capsys, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "migrate_operator_data_under_207",
        Path(__file__).resolve().parent.parent / "bin" / "migrate_operator_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["migrate_operator_data.py", "--from", "/nowhere"])
    with pytest.raises(SystemExit) as exit_:
        mod.main()
    assert exit_.value.code == 1
    assert "bin/migrate_state.py" in capsys.readouterr().err
