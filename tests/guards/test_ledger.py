"""Action ledger (issues #147, #158): the file adapter keeps one JSON object
per line, appended on each write, read incrementally, compacted at most once
a day, and converted in place from the former single JSON list; the memory
adapter gives the same answers."""
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from src.core import config
from src.core.state_errors import StateUnreadable
from src.guards import action_guard as ag, follow_policy as fp, ledger as lg
from src.guards.ledger import FileLedger, MemoryLedger
from tests.helpers import TORONTO

NOW = datetime.now(TORONTO)
TODAY = NOW.date()


@pytest.fixture()
def path(tmp_path):
    return tmp_path / "action_ledger.json"


@pytest.fixture()
def ledger(path):
    return FileLedger(str(path))


def _row(action, ts, target="", dry_run=False):
    return {"action": action, "target": target, "ts": ts, "dry_run": dry_run}


def _jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _add(ledger, action, target="", dry_run=False, at=None):
    ledger.append(action, target, dry_run, at or datetime.now(TORONTO))


def test_append_adds_a_line_without_rewriting_the_file(ledger, path):
    _add(ledger, ag.LIKE, "https://x.com/a/status/1")
    first = path.read_bytes()
    inode = os.stat(path).st_ino

    _add(ledger, ag.REPLY, "https://x.com/B/status/2")

    content = path.read_bytes()
    assert os.stat(path).st_ino == inode
    assert content.startswith(first) and len(content) > len(first)
    rows = _lines(path)
    assert [r["action"] for r in rows] == [ag.LIKE, ag.REPLY]
    assert set(rows[1]) == {"action", "target", "ts", "dry_run"}
    assert rows[1]["target"] == "https://x.com/b/status/2"
    assert not os.path.exists(str(path) + ".tmp")


def test_append_keeps_the_row_format(ledger, path):
    at = datetime(2026, 9, 21, 12, 30, tzinfo=TORONTO)
    ledger.append(ag.FOLLOW, "@SomeOne", True, at)
    assert path.read_text() == (
        '{"action": "follow", "target": "someone", "ts": "2026-09-21T12:30:00-04:00", '
        '"dry_run": true}\n')


def test_legacy_list_is_read_as_is_then_converted_on_the_first_write(ledger, path):
    today = NOW.replace(hour=9, minute=0).isoformat()
    legacy = [_row(ag.POST, today), _row(ag.POST, today, dry_run=True),
              _row(ag.FOLLOW, "2026-08-01T10:00:00", target="alice"),
              _row(ag.REPLY, today, target="https://x.com/c/status/3")]
    raw = json.dumps(legacy)
    path.write_text(raw)

    assert ledger.count(ag.POST, TODAY) == 1
    assert ledger.last_touch("alice") is not None
    # A read-only caller (status skill, dry run) leaves the file untouched.
    assert path.read_text() == raw

    _add(ledger, ag.POST)

    rows = _lines(path)
    assert rows[:-1] == legacy and rows[-1]["action"] == ag.POST
    assert ledger.count(ag.POST, TODAY) == 2


def test_retention_pass_drops_old_rows_at_most_once_a_day(ledger, path):
    old = (datetime.now() - timedelta(days=lg._RETENTION_DAYS + 10)).isoformat()
    recent = (datetime.now() - timedelta(days=2)).isoformat()
    path.write_text(_jsonl([_row(ag.FOLLOW, old, "old"), _row(ag.FOLLOW, recent, "recent")]))

    _add(ledger, ag.LIKE)
    assert [r["target"] for r in _lines(path)] == ["recent", ""]

    # Same Toronto day: an old row written since stays until tomorrow's pass.
    with open(path, "a") as f:
        f.write(json.dumps(_row(ag.FOLLOW, old, "late")) + "\n")
    inode = os.stat(path).st_ino
    _add(ledger, ag.LIKE)
    assert os.stat(path).st_ino == inode
    assert "late" in [r["target"] for r in _lines(path)]
    assert ledger.last_touch("late") is not None

    _add(ledger, ag.LIKE, at=datetime.now(TORONTO) + timedelta(days=1))
    assert [r["target"] for r in _lines(path)] == ["recent", "", "", ""]
    assert ledger.last_touch("late") is None and ledger.last_touch("recent") is not None


def test_cut_short_last_line_is_ignored_then_dropped_by_the_next_write(ledger, path):
    today = NOW.isoformat()
    good = _jsonl([_row(ag.POST, today), _row(ag.REPLY, today)])
    path.write_text(good + '{"action": "post", "ta')

    assert ledger.count(ag.POST, TODAY) == 1
    assert ledger.count(ag.REPLY, TODAY) == 1

    _add(ledger, ag.POST)

    lines = path.read_text().splitlines()
    assert len(lines) == 3 and all(json.loads(line) for line in lines)
    assert ledger.count(ag.POST, TODAY) == 2


def test_last_row_without_final_newline_counts_and_the_next_write_adds_it(ledger, path):
    today = NOW.isoformat()
    path.write_text(_jsonl([_row(ag.LIKE, today)]) + json.dumps(_row(ag.POST, today)))

    assert ledger.count(ag.POST, TODAY) == 1

    _add(ledger, ag.LIKE)

    assert [r["action"] for r in _lines(path)] == [ag.LIKE, ag.POST, ag.LIKE]
    assert ledger.count(ag.POST, TODAY) == 1
    assert ledger.count(ag.LIKE, TODAY) == 2


def test_bytes_glued_to_a_row_without_newline_are_not_read_incrementally(ledger, path):
    today = NOW.isoformat()
    path.write_text(_jsonl([_row(ag.LIKE, today)]) + json.dumps(_row(ag.POST, today)))
    assert ledger.count(ag.POST, TODAY) == 1

    with open(path, "a") as f:
        f.write(json.dumps(_row(ag.POST, today)) + "\n")

    with pytest.raises(StateUnreadable):
        ledger.count(ag.POST, TODAY)


@pytest.mark.parametrize("content", [
    ('{"action": "post", "ts": "2026-09-20T06:00:00"}\n{broken\n'
     '{"action": "post", "ts": "2026-09-20T07:00:00"}\n'),
    '{"action": "post", "ts": "2026-09-20T06:00:00"}\n{broken\n',
    '{"action": "post", "ts": "2026-09-20T06:00:00"}\n5\n',
    '{"action": "post", "ts": "2026-09-20T06:00:00"',
    "",
    "\n",
    "   \n\n",
    "[{broken",
    '{"action": "post", "ts": "2026-09-20T06:00:00"}\n{"action": "post"}\n',
    '{"action": "post", "ts": "2026-09-20T06:00:00"}\n{"action": "post", "ts": 5}\n',
    '[{"action": "post", "ts": null}]',
], ids=["middle", "complete-last-line", "not-an-object", "fragment-only", "empty",
        "newline-only", "blank-lines", "legacy-cut", "no-ts", "ts-not-text", "legacy-ts-not-text"])
def test_corrupt_ledger_refuses_every_query_and_write(ledger, path, content):
    path.write_text(content)

    for query in (lambda: ledger.count(ag.POST, TODAY), lambda: ledger.last_write(ag.REPLY),
                  lambda: ledger.last_touch("alice"), lambda: ledger.targets(ag.DEBATE_TURN)):
        with pytest.raises(StateUnreadable, match="ledger unreadable"):
            query()
    with pytest.raises(StateUnreadable):
        _add(ledger, ag.POST)
    assert path.read_text() == content


def test_corrupt_ledger_refuses_the_policy_and_the_write(monkeypatch, settings_override, path):
    path.write_text("{broken")
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    settings_override(FOLLOW_WHITELIST_ONLY=False)

    for check in (lambda: ag.can_post(ag.POST), lambda: ag.can_post(ag.REPLY),
                  lambda: fp.judge("karpathy"),
                  lambda: ag.can_debate_turn("someone"), lambda: ag.record(ag.LIKE)):
        with pytest.raises(StateUnreadable, match="ledger unreadable"):
            check()


def test_failed_rewrite_leaves_the_ledger_and_no_temporary_file(ledger, path, monkeypatch):
    raw = json.dumps([_row(ag.POST, NOW.isoformat())])
    path.write_text(raw)

    def refuse(fd):
        raise OSError("disk full")

    monkeypatch.setattr(lg, "_fsync", refuse)
    with pytest.raises(StateUnreadable, match="could not be saved"):
        _add(ledger, ag.LIKE)

    assert path.read_text() == raw
    assert not os.path.exists(str(path) + ".tmp")


def test_rewrite_flushes_the_file_then_its_directory(ledger, path, monkeypatch):
    flushed = []
    fsync = lg._fsync

    def spy(fd):
        flushed.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        fsync(fd)

    monkeypatch.setattr(lg, "_fsync", spy)
    path.write_text(json.dumps([_row(ag.POST, NOW.isoformat())]))

    _add(ledger, ag.LIKE)

    # Conversion: the temporary file, then the directory; then the append.
    assert flushed == ["file", "dir", "file"]


def test_fsync_falls_back_when_full_fsync_is_refused(monkeypatch, tmp_path):
    synced = []
    monkeypatch.setattr(lg.fcntl, "F_FULLFSYNC", 51, raising=False)

    def refuse(fd, cmd):
        raise OSError("not supported")

    monkeypatch.setattr(lg.fcntl, "fcntl", refuse)
    monkeypatch.setattr(lg.os, "fsync", synced.append)
    with open(tmp_path / "f", "wb") as f:
        lg._fsync(f.fileno())
        assert synced == [f.fileno()]


def test_index_notices_a_same_size_rewrite_that_keeps_the_mtime(ledger, path):
    today = NOW.isoformat()
    path.write_text(_jsonl([_row(ag.POST, today), _row(ag.REPLY, today)]))
    assert ledger.count(ag.POST, TODAY) == 1
    before = os.stat(path)

    path.write_text(_jsonl([_row(ag.LIKE, today), _row(ag.REPLY, today)]))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_ino, before.st_size, before.st_mtime_ns)

    assert ledger.count(ag.POST, TODAY) == 0


def test_two_ledgers_on_one_file_see_each_others_rows(path):
    """bin/mass_unfollow.py writes the file from another process: each
    Ledger sees the other's rows at its next query, whatever it indexed."""
    bot, script = FileLedger(str(path)), FileLedger(str(path))
    _add(bot, ag.REPLY, "https://x.com/a/status/1")
    assert script.count(ag.REPLY, TODAY) == 1

    _add(script, ag.UNFOLLOW, "someone")
    _add(script, ag.DEBATE_TURN, "fan")
    assert bot.last_touch("someone") is not None
    assert bot.targets(ag.DEBATE_TURN) == ["fan"]

    before = bot.last_write(ag.REPLY)
    later = datetime.now(TORONTO) + timedelta(seconds=5)
    _add(script, ag.REPLY, "https://x.com/a/status/2", at=later)
    assert bot.last_write(ag.REPLY) == later > before
    assert bot.count(ag.REPLY, TODAY) == script.count(ag.REPLY, TODAY) == 2


def test_the_next_policy_check_sees_a_row_another_process_appended(monkeypatch, settings_override, path):
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    settings_override(FOLLOW_WHITELIST_ONLY=False)
    fp.record_followers(["someone"])
    assert ag.can_post(ag.REPLY) == (True, "")
    assert "anti-churn" not in fp.judge("someone").reason

    other = FileLedger(str(path))
    _add(other, ag.REPLY, "https://x.com/a/status/1")
    _add(other, ag.UNFOLLOW, "someone")

    ok, why = ag.can_post(ag.REPLY)
    assert not ok and "too soon since last reply" in why
    verdict = fp.judge("someone")
    assert verdict.refusal is fp.Refusal.POLICY and "anti-churn" in verdict.reason, "an unfollow bin/mass_unfollow.py recorded blocks the re-follow"


def test_index_follows_a_file_rewritten_or_replaced_by_another_process(ledger, path):
    today = NOW.isoformat()
    _add(ledger, ag.POST)
    assert ledger.count(ag.POST, TODAY) == 1

    with open(path, "a") as f:
        f.write(json.dumps(_row(ag.POST, today)) + "\n")
    assert ledger.count(ag.POST, TODAY) == 2

    # Rewritten in place (same inode), shorter and then longer.
    path.write_text(_jsonl([_row(ag.REPLY, today)]))
    assert ledger.count(ag.POST, TODAY) == 0
    path.write_text(_jsonl([_row(ag.FOLLOW, today, target="x" * 200)] * 3))
    assert ledger.count(ag.FOLLOW, TODAY) == 3
    assert ledger.last_touch("x" * 200) is not None

    # Replaced by another file, as a restore or a compaction does.
    other = path.with_name("restored.json")
    other.write_text(json.dumps([_row(ag.POST, today)] * 4))
    os.replace(other, path)
    assert ledger.count(ag.POST, TODAY) == 4
    assert ledger.last_touch("x" * 200) is None

    path.unlink()
    assert ledger.count(ag.POST, TODAY) == 0
    assert ledger.last_write(ag.POST) is None and ledger.targets(ag.POST) == []


def test_write_and_check_on_a_large_ledger_parse_only_the_new_line(monkeypatch, path):
    base = datetime.now() - timedelta(days=30)
    rows = [_row(ag.LIKE if i % 2 else ag.REPLY, (base + timedelta(seconds=40 * i)).isoformat(),
                 target=f"https://x.com/u{i}/status/{i}") for i in range(50_000)]
    path.write_text(_jsonl(rows))
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    assert ag.can_post(ag.REPLY) == (True, "")
    ledger = lg.file_ledger(str(path))
    assert ledger.rows_read == 50_000
    inode = os.stat(path).st_ino

    ag.record(ag.LIKE, target="https://x.com/new/status/1")
    assert ag.can_post(ag.REPLY) == (True, "")
    assert ledger.rows_read == 50_001
    ag.record(ag.REPLY, target="https://x.com/new/status/2")
    assert not ag.can_post(ag.REPLY)[0]

    assert ledger.rows_read == 50_002
    assert os.stat(path).st_ino == inode
    assert len(_lines(path)) == 50_002


def test_policy_reads_the_configured_file_at_call_time(monkeypatch, tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(first))
    ag.record(ag.POST)
    assert ag.profile_count_today() == 1

    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(second))
    assert ag.profile_count_today() == 0
    ag.record(ag.POST)
    ag.record(ag.POST)
    assert ag.profile_count_today() == 2
    assert len(_lines(first)) == 1 and len(_lines(second)) == 2


# --- what both adapters answer ----------------------------------------------------


_TODAY_NOON = datetime(2026, 9, 21, 12, tzinfo=TORONTO)
_ROWS = [
    # Stamps written by older code: naive (Toronto host clock) and UTC.
    {"action": ag.POST, "ts": "2026-09-21T03:59:00+00:00"},  # 23:59 the day before
    {"action": ag.POST, "ts": "2026-09-21T04:00:00+00:00"},
    {"action": ag.POST, "ts": "2026-09-21T06:00:00"},
    {"action": ag.POST, "ts": "2026-09-21T07:00:00", "dry_run": True},
    {"action": ag.POST, "ts": "not a time"},
    _row(ag.REPLY, "2026-09-21T11:00:00-04:00", "https://x.com/a/status/1"),
    # The same instant twice: the first row's stamp seeds the spacing jitter.
    _row(ag.REPLY, "2026-09-21T15:30:00+00:00", "https://x.com/a/status/2"),
    _row(ag.REPLY, "2026-09-21T11:30:00-04:00", "https://x.com/a/status/3"),
    _row(ag.REPLY, "2026-09-21T11:45:00-04:00", "https://x.com/a/status/4", dry_run=True),
    _row(ag.DEBATE_TURN, "2026-09-20T10:00:00-04:00", "oldfan"),
    _row(ag.DEBATE_TURN, "2026-09-21T10:00:00-04:00", "newfan"),
    _row(ag.DEBATE_TURN, "2026-09-21T10:05:00-04:00", "oldfan"),
    _row(ag.DEBATE_TURN, "2026-09-21T10:06:00-04:00", "oldfan"),
    _row(ag.DEBATE_TURN, "2026-09-21T10:07:00-04:00", "simulated", dry_run=True),
    _row(ag.DEBATE_TURN, "2026-09-21T10:08:00-04:00", ""),
    # last_touch compares stamps as text and counts dry runs.
    _row(ag.FOLLOW, "2026-09-01T10:00:00-04:00", "alice"),
    _row(ag.UNFOLLOW, "2026-09-02T10:00:00-04:00", "alice", dry_run=True),
    _row(ag.LIKE, "2026-09-03T10:00:00-04:00", "alice"),
    {"action": ag.FOLLOW, "ts": "2026-09-04T10:00:00-04:00"},
    {"action": ["odd"], "target": {"odd": 1}, "ts": "2026-09-21T10:00:00-04:00"},
]


def _answers(ledger):
    return {
        "posts today": ledger.count(ag.POST, _TODAY_NOON.date()),
        "posts yesterday": ledger.count(ag.POST, (_TODAY_NOON - timedelta(days=1)).date()),
        "replies today": ledger.count(ag.REPLY, _TODAY_NOON.date()),
        "turns oldfan": ledger.count(ag.DEBATE_TURN, _TODAY_NOON.date(), "@OldFan"),
        "turns simulated": ledger.count(ag.DEBATE_TURN, _TODAY_NOON.date(), "simulated"),
        "last post": ledger.last_write(ag.POST),
        "last reply": ledger.last_write(ag.REPLY).isoformat(),
        "last like": ledger.last_write(ag.LIKE),
        "last pin": ledger.last_write(ag.PIN),
        "touch alice": ledger.last_touch("@Alice"),
        "touch nobody": ledger.last_touch("nobody"),
        "engagers": ledger.targets(ag.DEBATE_TURN),
    }


def test_file_and_memory_adapters_answer_alike(path):
    path.write_text(_jsonl(_ROWS))
    expected = {
        "posts today": 2,
        "posts yesterday": 1,
        "replies today": 3,
        "turns oldfan": 2,
        "turns simulated": 0,
        "last post": datetime(2026, 9, 21, 6, tzinfo=TORONTO),
        "last reply": "2026-09-21T15:30:00+00:00",
        "last like": datetime(2026, 9, 3, 10, tzinfo=TORONTO),
        "last pin": None,
        "touch alice": datetime(2026, 9, 2, 10, tzinfo=TORONTO),
        "touch nobody": None,
        "engagers": ["oldfan", "newfan"],
    }
    assert _answers(FileLedger(str(path))) == expected
    assert _answers(MemoryLedger(_ROWS)) == expected


# A hand-edited stamp whose Toronto day falls past the calendar's ends.
_PAST_THE_CALENDAR = ["9999-12-31T23:59:00-10:00", "0001-01-01T00:00:00+05:00"]


def _past_the_calendar_rows(ts):
    return [_row(ag.POST, ts), _row(ag.FOLLOW, ts, "alice"), _row(ag.DEBATE_TURN, ts, "fan")]


def _answers_past_the_calendar(ledger, ts):
    """What the former action_guard answered over _past_the_calendar_rows
    and one post at noon: the stamp counts on no day (it raised
    OverflowError there) and stays in every other answer."""
    stamp = datetime.fromisoformat(ts)
    noon = _TODAY_NOON
    assert ledger.count(ag.POST, noon.date()) == 1
    assert ledger.count(ag.DEBATE_TURN, noon.date(), "fan") == 0
    assert ledger.count(ag.FOLLOW, noon.date()) == 0
    assert ledger.last_write(ag.POST) == max(noon, stamp)
    assert ledger.last_write(ag.FOLLOW) == stamp
    assert ledger.last_touch("alice") == stamp
    assert ledger.targets(ag.DEBATE_TURN) == ["fan"]


@pytest.mark.parametrize("ts", _PAST_THE_CALENDAR)
def test_a_stamp_past_the_calendar_counts_on_no_day(ts, path):
    rows = [_row(ag.POST, _TODAY_NOON.isoformat())] + _past_the_calendar_rows(ts)
    path.write_text(_jsonl(rows))

    _answers_past_the_calendar(FileLedger(str(path)), ts)
    _answers_past_the_calendar(MemoryLedger(rows), ts)


@pytest.mark.parametrize("ts", _PAST_THE_CALENDAR)
def test_a_stamp_past_the_calendar_appended_later_is_indexed_once(ts, path):
    path.write_text(_jsonl([_row(ag.POST, _TODAY_NOON.isoformat())]))
    ledger = FileLedger(str(path))
    assert ledger.count(ag.POST, _TODAY_NOON.date()) == 1

    with open(path, "a") as f:
        f.write(_jsonl(_past_the_calendar_rows(ts)))
    for _ in range(3):
        _answers_past_the_calendar(ledger, ts)
    assert ledger.rows_read == 4

    _add(ledger, ag.POST, at=_TODAY_NOON)
    assert ledger.count(ag.POST, _TODAY_NOON.date()) == 2


@pytest.mark.parametrize("ts", _PAST_THE_CALENDAR)
def test_a_stamp_past_the_calendar_leaves_the_policy_its_budget(ts, monkeypatch, path):
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    ag.record(ag.POST)
    assert ag.profile_count_today() == 1

    with open(path, "a") as f:
        f.write(_jsonl(_past_the_calendar_rows(ts)))
    assert [ag.profile_count_today() for _ in range(3)] == [1, 1, 1]

    ag.record(ag.POST)
    assert ag.profile_count_today() == 2
    assert ag.can_debate_turn("fan") == (True, "")
    assert ag.debate_turn_authors() == ["fan"]


def test_memory_ledger_appends_rows_as_the_file_does(path):
    at = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    memory = MemoryLedger()
    for ledger in (memory, FileLedger(str(path))):
        ledger.append(ag.FOLLOW, "@Alice", False, at)
        ledger.append(ag.PIN, "", True, at)
    assert memory.rows == _lines(path)
