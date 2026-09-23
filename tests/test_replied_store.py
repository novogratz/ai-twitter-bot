"""Replied store (issue #100): fail closed, atomic writes, one claim per tweet."""
import json
import os
import threading

import pytest

from src import config
from src import replied_store as rs
from src.state_errors import StateUnreadable


def _url(n, author="someone"):
    return f"https://x.com/{author}/status/20635000000000{n:05d}"


def test_missing_store_reads_empty():
    assert not os.path.exists(config.REPLIED_FILE)
    assert len(rs.load_replied()) == 0


def test_legacy_shapes_still_read():
    with open(config.REPLIED_FILE, "w") as f:
        json.dump({"urls": [_url(1), "2063500000000000002"]}, f)
    replied = rs.load_replied()
    assert _url(1, "other_author") in replied
    assert _url(2) in replied


@pytest.mark.parametrize("content", ['["https://x.com/a/status/1", "https://x.com/b/sta',
                                     '{"urls": 3}', '"not a list"'])
def test_corrupt_store_fails_closed_and_stays_untouched(content):
    with open(config.REPLIED_FILE, "w") as f:
        f.write(content)
    with pytest.raises(StateUnreadable):
        rs.load_replied()
    with pytest.raises(StateUnreadable):
        rs.claim(_url(1))
    with pytest.raises(StateUnreadable):
        rs.save_replied({_url(1)})
    assert open(config.REPLIED_FILE).read() == content, "a corrupt store is kept for recovery"


def test_claim_is_once_per_status_id():
    assert rs.claim(_url(1)) is True
    assert rs.claim(_url(1, "misattributed") + "?s=20") is False
    assert json.load(open(config.REPLIED_FILE)) == ["2063500000000000001"]
    assert rs.claim("") is False


def test_parallel_claims_ship_each_tweet_once():
    wins = []
    barrier = threading.Barrier(16)

    def worker(i):
        barrier.wait()
        if rs.claim(_url(i % 4)):
            wins.append(i % 4)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(wins) == [0, 1, 2, 3]
    assert all(_url(i) in rs.load_replied() for i in range(4))


def test_save_keeps_claims_made_since_the_snapshot():
    snapshot = rs.load_replied()
    rs.claim(_url(2))            # another job ships while this cycle runs
    snapshot.add(_url(1))
    rs.save_replied(snapshot)
    replied = rs.load_replied()
    assert _url(1) in replied and _url(2) in replied


def test_failed_write_keeps_the_previous_store(monkeypatch):
    rs.claim(_url(1))
    before = open(config.REPLIED_FILE).read()

    def broken_dump(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(rs.json, "dump", broken_dump)
    with pytest.raises(StateUnreadable):
        rs.claim(_url(2))
    assert open(config.REPLIED_FILE).read() == before
    leftovers = [p for p in os.listdir(os.path.dirname(config.REPLIED_FILE)) if p.endswith(".tmp")]
    assert leftovers == []


def test_reply_chokepoint_refuses_on_corrupt_store(monkeypatch):
    from src import action_guard as ag
    from src import twitter_client as tc
    recorded = []
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, ""))
    monkeypatch.setattr(ag, "record", lambda *a, **k: recorded.append(a))
    monkeypatch.setenv("DRY_RUN", "1")
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    with pytest.raises(StateUnreadable):
        tc.reply_to_tweet(_url(1), "Batching is the whole margin story: utilisation decides the price.")
    assert recorded == [], "nothing ships on an unreadable store"


def test_unreadable_state_never_restarts_safari(monkeypatch, tmp_path):
    from src import health
    monkeypatch.setattr(health, "HEALTH_FILE", str(tmp_path / "safari_health.json"))
    restarts = []
    monkeypatch.setattr(health, "_restart_safari", lambda: restarts.append(1) or True)
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        try:
            rs.load_replied()
        except Exception:
            assert health.record_failure("direct_reply") is False
    assert restarts == [], "a corrupt store is not a Safari failure"
    assert not os.path.exists(health.HEALTH_FILE), "the failure counter is left alone"


def test_replyback_stops_on_unreadable_store(monkeypatch):
    """replyback catches reply errors per engager; an unreadable store must
    end the cycle at the first engager instead of paying one generation each."""
    from src import notify_bot as nb
    monkeypatch.setenv("DRY_RUN", "1")
    replies = [{"user": f"@fan{i}", "text": "what about inference margins?",
                "url": f"https://x.com/fan{i}/status/20635000000000{i:05d}"} for i in range(3)]
    monkeypatch.setattr(nb, "scrape_own_tweet_and_replies",
                        lambda: {"own_tweet": "batching is the margin story", "replies": replies})
    monkeypatch.setattr(nb, "_load_replied_back", lambda: set())
    monkeypatch.setattr(nb, "_save_replied_back", lambda s: pytest.fail("cycle must not finish"))
    monkeypatch.setattr(nb, "_influencer_handles", lambda: set())
    monkeypatch.setattr(nb, "_reciprocate_engagers", lambda *a, **k: pytest.fail("cycle must not finish"))
    monkeypatch.setattr(nb, "humanize", lambda t: t)
    generations = []
    monkeypatch.setattr(nb, "generate_replyback", lambda own, text: generations.append(text) or
                        "Utilisation decides it: a busy H100 earns its price, an idle one never does.")
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    with pytest.raises(StateUnreadable):
        nb.run_replyback_cycle()
    assert len(generations) == 1, "one generation, then the cycle stops"
