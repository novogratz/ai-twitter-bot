"""src/core/state_store: guarded and disposable JSON state files (#159)."""
import json
import os
import threading

import pytest

from src.core import state_store
from src.core.state_errors import StateUnreadable
from src.core.state_store import DISPOSABLE, GUARDED, StateFile

CORRUPT = '{"handles": {"half'


def _declare(name, default, policy):
    return StateFile(f"test_{name}_{policy}.json", default, policy)


@pytest.mark.parametrize("policy", [GUARDED, DISPOSABLE])
def test_a_missing_file_reads_as_a_fresh_copy_of_the_default(policy):
    state = _declare("missing", {"entries": []}, policy)
    first = state.read()
    first["entries"].append("mutated")
    assert state.read() == {"entries": []}
    assert not os.path.exists(state.path), "reading never creates the file"


@pytest.mark.parametrize("content", [CORRUPT, "[]", "null", b"\xff\xfe"])
def test_a_guarded_file_that_is_unreadable_raises_and_is_never_overwritten(content, monkeypatch):
    state = _declare("guarded", {}, GUARDED)
    with open(state.path, "wb") as f:
        f.write(content if isinstance(content, bytes) else content.encode())
    before = open(state.path, "rb").read()
    errors = []
    monkeypatch.setattr(state_store.log, "error", lambda msg, *a, **k: errors.append(msg))

    with pytest.raises(StateUnreadable):
        state.read()
    with pytest.raises(StateUnreadable):
        state.write({"fresh": True})

    assert open(state.path, "rb").read() == before
    assert errors and all(state.name in msg for msg in errors), "the refusal is logged"


def test_a_disposable_file_that_is_unreadable_reads_as_the_default_then_is_replaced(monkeypatch):
    state = _declare("disposable", {"count": 0}, DISPOSABLE)
    with open(state.path, "w") as f:
        f.write(CORRUPT)
    warnings = []
    monkeypatch.setattr(state_store.log, "warning", lambda msg, *a, **k: warnings.append(msg))

    assert state.read() == {"count": 0}
    state.write({"count": 1})

    assert state.read() == {"count": 1}
    assert warnings and state.name in warnings[0]


@pytest.mark.parametrize("policy", [GUARDED, DISPOSABLE])
def test_writes_are_atomic_and_leave_no_temp_file(policy, tmp_path):
    state = _declare("atomic", [], policy)
    state.write(["a", "é", "lone \ud835 surrogate"])
    state.write(["b"])
    assert state.read() == ["b"]
    assert sorted(os.listdir(tmp_path)) == [state.name]


def test_a_failed_write_keeps_the_previous_file(monkeypatch):
    state = _declare("failed_write", {}, GUARDED)
    state.write({"kept": True})

    def refuse(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(state_store.os, "replace", refuse)

    with pytest.raises(StateUnreadable):
        state.write({"kept": False})
    assert json.load(open(state.path)) == {"kept": True}
    assert os.listdir(os.path.dirname(state.path)) == [state.name]


def test_one_file_has_one_policy():
    StateFile("test_one_policy.json", {}, GUARDED)
    StateFile("test_one_policy.json", {}, GUARDED)
    with pytest.raises(ValueError):
        StateFile("test_one_policy.json", {}, DISPOSABLE)


def test_paths_follow_the_root_at_call_time(monkeypatch, tmp_path):
    state = _declare("root", {}, DISPOSABLE)
    moved = tmp_path / "moved"
    moved.mkdir()
    monkeypatch.setattr(state_store, "ROOT", str(moved))
    state.write({"here": True})
    assert (moved / state.name).exists()


# --- the guarded files, through the jobs that need them -----------------------


def _corrupt(tmp_path, name):
    path = tmp_path / name
    path.write_text(CORRUPT)
    return path


def _engage(monkeypatch):
    from src.account import engage_bot
    monkeypatch.setattr(engage_bot, "follow_account", lambda *a, **k: pytest.fail("followed"))
    engage_bot.run_engage_cycle()


def _like(monkeypatch):
    from src.account import like_bot
    from src.x import twitter_client
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(twitter_client, "like_search_posts", lambda *a: pytest.fail("liked"))
    like_bot.run_like_cycle()


def _pin(monkeypatch):
    from src.account import pin_bot
    monkeypatch.setattr(pin_bot, "scrape_profile_tweets", lambda *a, **k: pytest.fail("scraped"))
    monkeypatch.setattr(pin_bot.twitter_client, "pin_own_tweet", lambda *a: pytest.fail("pinned"))
    pin_bot.run_pin_cycle()


def _follow_engagers(monkeypatch):
    from src.account import follow_engagers_bot
    monkeypatch.setenv("ENABLE_FOLLOW_ENGAGERS", "1")
    monkeypatch.setattr("src.x.twitter_client.follow_account", lambda *a, **k: pytest.fail("followed"))
    follow_engagers_bot.run_follow_engagers_cycle()


def _curator(monkeypatch):
    from src.account import account_curator as ac
    monkeypatch.setattr(ac, "_author_engagements", lambda: {"goodfinance": 9})
    ac.run_curator_cycle()


def _editorial(monkeypatch):
    from src.editorial import editorial_bot
    monkeypatch.setattr(editorial_bot, "draft_post", lambda *a, **k: pytest.fail("drafted"))
    editorial_bot.run_editorial_cycle()


def _post(monkeypatch):
    from src.guards import content_guard
    from src.x import twitter_client
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(content_guard, "validate", lambda *a, **k: (True, ""))
    twitter_client.post_tweet("A fresh and sourced take on model evaluation datasets today.")


def _babysit(monkeypatch):
    from src.replies import first_hour_babysitter
    monkeypatch.setattr("src.replies.notify_bot.run_replyback_cycle", lambda: pytest.fail("swept"))
    first_hour_babysitter.run_babysit_cycle()


def _personality(monkeypatch):
    from src.core import personality_store
    personality_store.render_account_block("someone")


@pytest.mark.parametrize("name, job", [
    ("followed_accounts.json", _engage),
    ("like_bot_state.json", _like),
    ("pin_daily_state.json", _pin),
    ("pin_history.json", _pin),
    ("follow_engagers_state.json", _follow_engagers),
    ("whitelist.json", _curator),
    ("editorial_state.json", _editorial),
    ("tweet_history.json", _post),
    ("tweet_history.json", _babysit),
    ("personality.json", _personality),
])
def test_a_job_refuses_while_its_guarded_file_is_unreadable(name, job, monkeypatch, tmp_path):
    """Each of these files used to read as empty or default on a bad read,
    and the next save replaced it: a lost daily cap, a lost follow or pin
    record, a lost dedup corpus, lost dossiers or Operator tiers. The job now
    stops before acting, and the file waits for the Operator."""
    path = _corrupt(tmp_path, name)
    with pytest.raises(StateUnreadable):
        job(monkeypatch)
    assert path.read_text() == CORRUPT


def test_the_history_writer_leaves_an_unreadable_history_alone(tmp_path):
    from src.core import history
    path = _corrupt(tmp_path, "tweet_history.json")
    with pytest.raises(StateUnreadable):
        history.save_tweet("shipped text")
    assert path.read_text() == CORRUPT


def test_an_interaction_never_erases_unreadable_dossiers(tmp_path):
    """engagement_log.log_reply bumps a dossier after every Reply, and
    swallows the error: the Reply stays logged, the dossiers stay intact."""
    from src.core import engagement_log
    path = _corrupt(tmp_path, "personality.json")
    engagement_log.log_reply("https://x.com/someone/status/2063500000000000100", "a reply", "reply")
    assert path.read_text() == CORRUPT


# --- respect_list.json ---------------------------------------------------------


def test_a_missing_respect_list_is_seeded_with_the_defaults(tmp_path):
    from src.guards import respect_list
    assert "micode" in respect_list.load()
    assert "micode" in json.loads((tmp_path / "respect_list.json").read_text())["handles"]


def test_an_unreadable_respect_list_is_never_overwritten(tmp_path):
    """It used to be replaced by the seed, losing every handle the Operator
    added. Changes refuse; the prompt block and the block computed when
    personality_store is imported fall back to the defaults, without writing."""
    from src.core import personality_store
    from src.guards import respect_list
    path = _corrupt(tmp_path, "respect_list.json")

    for change in (lambda: respect_list.add("newhandle"), lambda: respect_list.remove("micode"),
                   respect_list.load, lambda: respect_list.is_protected("micode")):
        with pytest.raises(StateUnreadable):
            change()
    assert "@micode" in respect_list.render_block()
    assert "@micode" in personality_store._render_hard_rules()
    assert "@micode" in personality_store.hard_rules_block()
    assert path.read_text() == CORRUPT


# --- safari_health.json ----------------------------------------------------------


def test_health_updates_are_serialised(monkeypatch):
    """About twelve scheduler threads report to the same counter: none of
    their increments may be lost."""
    from src.core import health
    monkeypatch.setattr(health, "RECOVERY_THRESHOLD", 10_000)
    real_read = health.HEALTH.read

    def slow_read():
        data = real_read()
        threading.Event().wait(0.001)  # widen the read-modify-write window
        return data
    monkeypatch.setattr(health.HEALTH, "read", slow_read)

    threads = [threading.Thread(target=health.record_failure, args=("job",)) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert real_read()["consecutive_failures"] == 40
