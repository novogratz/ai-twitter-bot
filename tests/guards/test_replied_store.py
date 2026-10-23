"""Replied store (issue #100): fail closed, atomic writes, one claim per tweet."""
import json
import multiprocessing
import os
import threading

import pytest

from src.core import config
from src.guards import replied_store as rs
from src.core.state_errors import StateUnreadable
from tests.helpers import numbered_url


def test_missing_store_reads_empty():
    assert not os.path.exists(config.REPLIED_FILE)
    assert len(rs.load_replied()) == 0


def test_legacy_shapes_still_read():
    with open(config.REPLIED_FILE, "w") as f:
        json.dump({"urls": [numbered_url(1), "2063500000000000002"]}, f)
    replied = rs.load_replied()
    assert numbered_url(1, "other_author") in replied
    assert numbered_url(2) in replied


@pytest.mark.parametrize("content", ['["https://x.com/a/status/1", "https://x.com/b/sta',
                                     '{"urls": 3}', '"not a list"', '[null]', '[123]', '[""]', '["  "]'])
def test_corrupt_store_fails_closed_and_stays_untouched(content):
    with open(config.REPLIED_FILE, "w") as f:
        f.write(content)
    with pytest.raises(StateUnreadable):
        rs.load_replied()
    with pytest.raises(StateUnreadable):
        rs.claim(numbered_url(1))
    with pytest.raises(StateUnreadable):
        rs.save_replied({numbered_url(1)})
    assert open(config.REPLIED_FILE).read() == content, "a corrupt store is kept for recovery"


def test_claim_is_once_per_status_id():
    assert rs.claim(numbered_url(1)) is True
    assert rs.claim(numbered_url(1, "misattributed") + "?s=20") is False
    assert json.load(open(config.REPLIED_FILE)) == ["2063500000000000001"]
    assert rs.claim("") is False


def test_parallel_claims_ship_each_tweet_once():
    wins = []
    barrier = threading.Barrier(16)

    def worker(i):
        barrier.wait()
        if rs.claim(numbered_url(i % 4)):
            wins.append(i % 4)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(wins) == [0, 1, 2, 3]
    assert all(numbered_url(i) in rs.load_replied() for i in range(4))


def test_save_keeps_claims_made_since_the_snapshot():
    snapshot = rs.load_replied()
    rs.claim(numbered_url(2))            # another job ships while this cycle runs
    snapshot.add(numbered_url(1))
    rs.save_replied(snapshot)
    replied = rs.load_replied()
    assert numbered_url(1) in replied and numbered_url(2) in replied


def test_failed_write_keeps_the_previous_store(monkeypatch):
    rs.claim(numbered_url(1))
    before = open(config.REPLIED_FILE).read()

    def broken_dump(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(rs.json, "dump", broken_dump)
    with pytest.raises(StateUnreadable):
        rs.claim(numbered_url(2))
    assert open(config.REPLIED_FILE).read() == before
    leftovers = [p for p in os.listdir(os.path.dirname(config.REPLIED_FILE)) if p.endswith(".tmp")]
    assert leftovers == []


def test_release_drops_only_the_claimed_tweet(monkeypatch):
    from src.core import config
    from src.guards import replied_store

    keep, drop = "2063500000000000150", "2063500000000000151"
    with open(config.REPLIED_FILE, "w") as f:
        json.dump({"urls": [f"https://x.com/a/status/{keep}", drop]}, f)

    replied_store.release(f"https://x.com/b/status/{drop}")

    assert json.load(open(config.REPLIED_FILE)) == [f"https://x.com/a/status/{keep}"]


def test_history_is_retained_past_the_old_eviction_limit():
    old = [str(2063500000000000000 + i) for i in range(50001)]
    with open(config.REPLIED_FILE, "w") as f:
        json.dump(old, f)
    assert rs.claim(numbered_url(50001))
    assert json.load(open(config.REPLIED_FILE)) == old + ["2063500000000050001"]
    assert not rs.claim(numbered_url(0, "renamed"))


def _claim_in_process(path, i, barrier, results):
    import time
    config.REPLIED_FILE = path
    read = rs._read_entries

    def delayed_read():
        entries = read()
        time.sleep(0.04)  # expose a read/merge/write race if only the thread lock exists
        return entries

    rs._read_entries = delayed_read
    barrier.wait(timeout=10)
    results.put((i % 4, rs.claim(numbered_url(i % 4, f"worker{i}"))))


def test_processes_cannot_double_claim_or_drop_each_others_history():
    context = multiprocessing.get_context("fork")
    barrier, results = context.Barrier(9), context.Queue()
    workers = [context.Process(target=_claim_in_process,
                               args=(os.fspath(config.REPLIED_FILE), i, barrier, results))
               for i in range(8)]
    try:
        for worker in workers:
            worker.start()
        barrier.wait(timeout=10)
        claims = [results.get(timeout=10) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
        assert all(worker.exitcode == 0 for worker in workers)
        assert sorted(i for i, won in claims if won) == [0, 1, 2, 3]
        assert all(numbered_url(i) in rs.load_replied() for i in range(4))
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()


def test_lock_failure_refuses_without_changing_history(monkeypatch):
    rs.claim(numbered_url(1))
    before = open(config.REPLIED_FILE).read()

    def unavailable(*args):
        raise OSError("lock unavailable")

    monkeypatch.setattr(rs.fcntl, "flock", unavailable)
    with pytest.raises(StateUnreadable):
        rs.claim(numbered_url(2))
    assert open(config.REPLIED_FILE).read() == before
