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
    before = set(os.listdir(tmp_path))
    state.write(["a", "é", "lone \ud835 surrogate"])
    state.write(["b"])
    assert state.read() == ["b"]
    assert set(os.listdir(tmp_path)) - before == {state.name}


def test_a_failed_write_keeps_the_previous_file(monkeypatch):
    state = _declare("failed_write", {}, GUARDED)
    before = set(os.listdir(os.path.dirname(state.path)))
    state.write({"kept": True})

    def refuse(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(state_store.os, "replace", refuse)

    with pytest.raises(StateUnreadable):
        state.write({"kept": False})
    assert json.load(open(state.path)) == {"kept": True}
    assert set(os.listdir(os.path.dirname(state.path))) - before == {state.name}


def test_one_file_has_one_policy():
    StateFile("test_one_policy.json", {}, GUARDED)
    StateFile("test_one_policy.json", {}, GUARDED)
    with pytest.raises(ValueError):
        StateFile("test_one_policy.json", {}, DISPOSABLE)


def test_paths_follow_the_root_at_call_time(monkeypatch, tmp_path):
    state = _declare("root", {}, DISPOSABLE)
    moved = tmp_path / "moved"
    moved.mkdir()
    monkeypatch.setattr(state_store, "root", lambda: str(moved))
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


def _followback(monkeypatch):
    from src.account import followback_bot
    monkeypatch.setattr(followback_bot, "follow_account", lambda *a, **k: pytest.fail("followed"))
    followback_bot.run_followback_cycle()


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


def _validate(monkeypatch):
    from src.guards import content_guard
    content_guard.validate("Me reading the model card twice before trusting any benchmark "
                           "table, because the eval setup decides the score.", kind="original")


def _personality(monkeypatch):
    from src.core import personality_store
    personality_store.render_account_block("someone")


@pytest.mark.parametrize("name, job", [
    ("followed_accounts.json", _engage),
    ("followed_accounts.json", _followback),
    ("like_bot_state.json", _like),
    ("pin_daily_state.json", _pin),
    ("pin_history.json", _pin),
    ("follow_engagers_state.json", _follow_engagers),
    ("whitelist_discovered.json", _curator),
    ("editorial_state.json", _editorial),
    ("tweet_history.json", _post),
    ("tweet_history.json", _babysit),
    ("tweet_history.json", _validate),
    ("personality.json", _personality),
])
def test_a_job_refuses_while_its_guarded_file_is_unreadable(name, job, monkeypatch, tmp_path,
                                                            settings_override):
    """Each of these files used to read as empty or default on a bad read,
    and the next save replaced it: a lost daily cap, a lost follow or pin
    record, a lost dedup corpus, lost dossiers or Operator tiers. The job now
    stops before acting, and the file waits for the Operator."""
    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    path = _corrupt(tmp_path, name)
    with pytest.raises(StateUnreadable):
        job(monkeypatch)
    assert path.read_text() == CORRUPT


def test_an_unreadable_history_stops_the_editorial_cycle_before_a_draft(monkeypatch, tmp_path):
    """The review dedups the Draft against tweet_history.json: read after
    the Draft, an unreadable history spent the Attempt for nothing."""
    from datetime import datetime
    from src.editorial import editorial_bot as editorial
    from tests.helpers import TORONTO, clock
    path = _corrupt(tmp_path, "tweet_history.json")
    clock(monkeypatch, datetime(2026, 9, 20, 7, 30, tzinfo=TORONTO))
    monkeypatch.setattr(editorial, "collect_sources", lambda *a: pytest.fail("sources fetched"))
    monkeypatch.setattr(editorial, "draft_post", lambda *a: pytest.fail("drafted"))

    with pytest.raises(StateUnreadable):
        editorial.run_editorial_cycle()

    assert not editorial._read_state().get("attempts")
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


def test_two_follows_recorded_at_once_keep_each_other(monkeypatch, tmp_path):
    """engage_job and followback_job each read followed_accounts.json at the
    start of their cycle and saved their copy at the end: the last one to
    save erased the handles the other had followed. Both read here before
    either writes, unless the file's lock serialises them."""
    from src.guards import follow_policy
    both_read = threading.Barrier(2, timeout=0.3)
    real_read = follow_policy.FOLLOWED.read

    def read_then_wait():
        value = real_read()
        try:
            both_read.wait()
        except threading.BrokenBarrierError:
            pass  # serialised: the other thread waits on the lock
        return value
    monkeypatch.setattr(follow_policy.FOLLOWED, "read", read_then_wait)

    threads = [threading.Thread(target=follow_policy.record_followed, args=(handle,))
               for handle in ("fromengage", "fromfollowback")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(json.loads((tmp_path / "followed_accounts.json").read_text())) == {
        "fromengage", "fromfollowback"}


def test_a_write_flushes_the_file_then_the_directory(monkeypatch, tmp_path):
    """The rename lives in the directory: without flushing it, a crash can
    bring the old file back."""
    import stat
    steps = []
    real_replace = state_store.os.replace
    monkeypatch.setattr(state_store, "_fsync", lambda fd: steps.append(
        "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"))
    monkeypatch.setattr(state_store.os, "replace", lambda *a: steps.append("replace") or real_replace(*a))

    state_store.atomic_write_bytes(str(tmp_path / "x.json"), b"{}")

    assert steps == ["file", "replace", "dir"]
    assert (tmp_path / "x.json").read_bytes() == b"{}"


# --- respect_list.json, an Operator file -----------------------------------------


def test_a_missing_respect_list_stops_its_readers_and_is_never_recreated(operator_folder):
    """#206: a missing respect list was seeded with defaults, silently
    replacing the Operator's list when its path changed."""
    from src.core import personality_store
    from src.guards import respect_list
    (operator_folder / "respect_list.json").unlink()

    for read in (respect_list.load, respect_list.render_block, personality_store.hard_rules_block):
        with pytest.raises(StateUnreadable, match="respect_list.json is missing"):
            read()
    assert not (operator_folder / "respect_list.json").exists()


def test_an_unreadable_respect_list_is_never_overwritten(operator_folder):
    """It used to be replaced by the seed, losing every handle the Operator
    added. Every read refuses, the prompt block included; nothing renders
    the block at import, so main.py still starts. Nothing writes the file."""
    from src.core import personality_store
    from src.guards import respect_list
    path = _corrupt(operator_folder, "respect_list.json")

    for read in (respect_list.load, lambda: respect_list.scrub_text_or_skip("@micode"),
                 respect_list.render_block, personality_store._render_hard_rules,
                 personality_store.hard_rules_block):
        with pytest.raises(StateUnreadable):
            read()
    assert path.read_text() == CORRUPT


def test_importing_personality_store_leaves_the_respect_list_unread(monkeypatch, operator_folder):
    """main.py imports it at start: a block rendered at import would stop
    the process on an unreadable respect list."""
    import importlib
    from src.core import personality_store
    from src.guards import respect_list
    path = _corrupt(operator_folder, "respect_list.json")
    monkeypatch.setattr(respect_list, "render_block", lambda: pytest.fail("rendered at import"))
    saved = dict(vars(personality_store))
    try:
        importlib.reload(personality_store)
    finally:
        vars(personality_store).clear()
        vars(personality_store).update(saved)
    assert path.read_text() == CORRUPT


def test_a_reply_cycle_refuses_on_an_unreadable_respect_list(monkeypatch, operator_folder, caplog):
    """The Reply prompt carries the respect list: no prompt, no Reply. The
    cycle stops at the first candidate instead of trying the next ones."""
    from src.core import health
    from src.replies import direct_reply as dr
    from tests.helpers import fresh
    path = _corrupt(operator_folder, "respect_list.json")
    scraped = []
    monkeypatch.setattr(dr, "_run_vip_scan", lambda *a, **k: 0)
    monkeypatch.setattr(dr, "scrape_x_search", lambda *a, **k: scraped.append(a) or [
        {"url": fresh("someone", n=i), "text": "post"} for i in range(3)])
    monkeypatch.setattr(dr, "is_on_niche", lambda text: True)
    from src.replies import reply_generator
    from src.x import twitter_client
    monkeypatch.setattr(reply_generator, "run_llm", lambda *a, **k: pytest.fail("model called"))
    monkeypatch.setattr(twitter_client, "reply_to_tweet", lambda *a, **k: pytest.fail("replied"))
    monkeypatch.setattr(health, "_restart_safari", lambda: pytest.fail("Safari restarted"))

    dr.safe_run_direct_reply_cycle()

    assert len(scraped) == 1, "the cycle stops, it does not move to the next query"
    assert "respect_list.json is unreadable" in caplog.text
    assert "direct_reply halted" in caplog.text
    assert path.read_text() == CORRUPT


def test_the_editorial_cycle_refuses_on_an_unreadable_respect_list(monkeypatch, tmp_path, caplog,
                                                                  operator_folder):
    """The Draft prompt carries the respect list: the cycle stops before the
    model call, and no Attempt is spent."""
    from datetime import datetime
    from src.editorial import editorial_bot as editorial
    from src.x import twitter_client
    from tests.helpers import TORONTO, clock
    path = _corrupt(operator_folder, "respect_list.json")
    clock(monkeypatch, datetime(2026, 9, 20, 7, 30, tzinfo=TORONTO))
    monkeypatch.setattr(editorial, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(editorial, "collect_sources", lambda *a: [dict(
        id="0", title="t", url="https://huggingface.co/docs", publisher="p",
        body="A source sentence long enough to be evidence for a post.", kind="knowledge",
        published_at="")])
    monkeypatch.setattr(editorial, "_json_call", lambda *a: pytest.fail("model called"))
    monkeypatch.setattr(twitter_client, "post_tweet", lambda *a, **k: pytest.fail("posted"))

    assert editorial.safe_run_editorial_cycle() is None

    assert not editorial._read_state().get("attempts")
    assert "respect_list.json is unreadable" in caplog.text
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

    threads = [threading.Thread(target=health.record_failure, args=("job", RuntimeError("job")))
               for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert real_read()["consecutive_failures"] == 40


def test_a_failure_during_a_safari_restart_does_not_restart_it_again(monkeypatch):
    from src.core import health
    monkeypatch.setattr(health, "RECOVERY_THRESHOLD", 1)
    monkeypatch.setattr(health, "_append_autonomous_flag", lambda *a: None)
    restarting, release = threading.Event(), threading.Event()
    restarts = []

    def blocked_restart():
        restarts.append(1)
        restarting.set()
        release.wait(5)
        return True
    monkeypatch.setattr(health, "_restart_safari", blocked_restart)

    first = threading.Thread(target=health.record_failure, args=("first", RuntimeError("first")))
    first.start()
    try:
        assert restarting.wait(5)
        assert health.record_failure("second", RuntimeError("second")) is False
    finally:
        release.set()
        first.join()
    assert restarts == [1]


# --- codex_lockout.json ----------------------------------------------------------


def test_an_unreadable_codex_lockout_is_removed_after_one_warning(monkeypatch, tmp_path):
    from src.core import llm_client
    path = _corrupt(tmp_path, "codex_lockout.json")
    warnings = []
    monkeypatch.setattr(state_store.log, "warning", lambda msg, *a, **k: warnings.append(msg))

    assert llm_client._read_codex_lockout() is None
    assert llm_client._read_codex_lockout() is None

    assert not path.exists()
    assert len(warnings) == 1
