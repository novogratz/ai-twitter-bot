"""Cross-cutting: the bot reads the Operator files and never writes them (#206).

The Operator files live in the Account folder, versioned: the follow
whitelist, the respect list, the following baseline. What the bot keeps goes
to state files. Each test here makes the test's copy of the folder read-only
and records, through an audit hook, every attempt to open a file in it for
writing, to create, rename or delete one: a job that swallowed the
PermissionError would still be caught.
"""
import json
import os
import socket
import stat
import subprocess
import sys
import time

import pytest

from src.core import account, state_store
from src.core.account import OperatorFile

OPERATOR_FILES = ("whitelist.json", "respect_list.json", "following_baseline.json")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_PATH_EVENTS = {"os.remove": 1, "os.rmdir": 1, "os.mkdir": 1, "os.chmod": 1, "os.truncate": 1,
                "os.rename": 2, "shutil.copyfile": 2, "shutil.move": 2, "tempfile.mkstemp": 1}

_watch = {"folder": None, "writes": []}


def _inside(path) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, (str, os.PathLike)):
        return False
    path = os.path.realpath(os.fspath(path))
    return path == _watch["folder"] or path.startswith(_watch["folder"] + os.sep)


def _audit(event, args):
    if _watch["folder"] is None:
        return
    if event == "open":
        path, mode, flags = args
        writes = (any(c in mode for c in "wax+") if isinstance(mode, str)
                  else bool((flags or 0) & _WRITE_FLAGS))
        if writes and _inside(path):
            _watch["writes"].append((event, path))
    elif event in _PATH_EVENTS:
        if any(_inside(p) for p in args[:_PATH_EVENTS[event]]):
            _watch["writes"].append((event, args[:_PATH_EVENTS[event]]))


sys.addaudithook(_audit)


def _snapshot(folder) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file()}


@pytest.fixture
def watched(operator_folder):
    """The Operator folder copy, read-only and watched; the test fails if
    anything tried to write in it."""
    for name in OPERATOR_FILES:
        assert (operator_folder / name).is_file(), name
    before = _snapshot(operator_folder)
    modes = {p: p.stat().st_mode for p in [operator_folder, *operator_folder.rglob("*")]}
    for p in modes:
        if p.is_dir():
            p.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)
        else:
            p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    _watch.update(folder=os.path.realpath(operator_folder), writes=[])
    try:
        yield _watch["writes"]
    finally:
        _watch["folder"] = None
        for p, mode in modes.items():
            p.chmod(mode)
    assert _watch["writes"] == [], "wrote in the Operator folder"
    assert _snapshot(operator_folder) == before


@pytest.fixture
def walled(monkeypatch):
    """No network, no subprocess, no sleep: a job stops at its first page
    or model call."""
    def refuse(*a, **k):
        raise OSError("walled in this test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(time, "sleep", lambda *a: None)


def test_the_watch_sees_a_write(watched):
    with pytest.raises(PermissionError), open(os.path.join(_watch["folder"], "whitelist.json"), "a"):
        pass
    assert watched == [("open", os.path.join(_watch["folder"], "whitelist.json"))]
    watched.clear()


def test_an_operator_file_offers_no_write_and_is_no_state_file():
    import importlib
    import pkgutil
    import src
    for m in pkgutil.walk_packages(src.__path__, "src."):
        importlib.import_module(m.name)
    assert not any(hasattr(OperatorFile, name) for name in ("write", "update"))
    assert not set(OPERATOR_FILES) & set(state_store._DECLARED)


def test_a_missing_operator_file_stops_its_reader_and_is_never_recreated(operator_folder):
    from src.core.state_errors import StateUnreadable
    from src.guards import follow_policy
    (operator_folder / "whitelist.json").unlink()
    with pytest.raises(StateUnreadable, match="whitelist.json is missing"):
        follow_policy.load_whitelist()
    assert not (operator_folder / "whitelist.json").exists()


@pytest.mark.parametrize("dry_run", ["1", "0"])
def test_no_scheduled_job_writes_the_operator_files(watched, walled, monkeypatch, dry_run):
    import main
    monkeypatch.setenv("DRY_RUN", dry_run)
    jobs = main.build_scheduler().get_jobs()
    assert len(jobs) >= 17
    for job in jobs:
        try:
            job.func()
        except Exception:
            pass  # a walled job may raise; only its writes matter here


def test_the_curator_promotes_into_the_state_never_the_whitelist(watched, tmp_path, monkeypatch):
    from src.account import account_curator
    from src.guards import follow_policy
    monkeypatch.setattr(account_curator, "_author_engagements", lambda: {"deep_macro": 9})

    account_curator.run_curator_cycle()

    assert json.loads((tmp_path / "whitelist_discovered.json").read_text()) == ["deep_macro"]
    assert follow_policy.relation("deep_macro") is follow_policy.Relation.SEED


@pytest.mark.parametrize("dry_run", ["1", "0"])
def test_a_follow_of_a_seed_account_writes_only_state(watched, walled, memory_ledger, tmp_path,
                                                      monkeypatch, dry_run):
    from src.x import safari, scraper, twitter_client
    monkeypatch.setenv("DRY_RUN", dry_run)
    (tmp_path / "following_count.json").write_text(json.dumps({"count": 10}))
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: "CLICKED")
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(scraper, "_scrape_profile_quality",
                        lambda: {"followers": "12K", "bio": "AI", "name": "Seed"})
    seed = account.OperatorFile("whitelist.json", dict).read()["tiers"]["tier3"][0]

    outcome = twitter_client.follow_account(seed)

    expected = {"1": twitter_client.FollowOutcome.DRY_RUN, "0": twitter_client.FollowOutcome.FOLLOWED}
    assert outcome is expected[dry_run]
    count = json.loads((tmp_path / "following_count.json").read_text())["count"]
    assert count == (10 if dry_run == "1" else 11)


def test_the_respect_list_readers_write_nothing(watched, memory_ledger, monkeypatch):
    from src.core import personality_store
    from src.guards import respect_list
    from src.x import twitter_client
    monkeypatch.setenv("DRY_RUN", "1")
    assert "@micode" in personality_store.hard_rules_block()
    assert respect_list.scrub_text_or_skip("@micode is wrong")[0] is None
    assert twitter_client.post_tweet("Inference got cheaper this week, says @micode.") is (
        twitter_client.WriteOutcome.REFUSED)


def test_the_unfollow_keep_sets_write_nothing(watched, monkeypatch):
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "bin", "mass_unfollow.py")
    spec = importlib.util.spec_from_file_location("mass_unfollow_under_test", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert "karpathy" in script._whitelist_keep_set()
    assert "micode" in script._legacy_keep_set()
