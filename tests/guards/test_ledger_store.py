"""Action ledger storage (issue #147): one JSON object per line, appended on
each write, read incrementally, compacted at most once a day, and converted in
place from the former single JSON list."""
import json
import os
import stat
from datetime import datetime, timedelta

import pytest

from src.core import config
from src.core.state_errors import StateUnreadable
from src.guards import action_guard as ag


@pytest.fixture()
def ledger(monkeypatch, tmp_path):
    path = tmp_path / "action_ledger.json"
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    return path


def _row(action, ts, target="", dry_run=False):
    return {"action": action, "target": target, "ts": ts, "dry_run": dry_run}


def _jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def _now():
    return ag.now_local()


def test_record_appends_without_rewriting_the_file(ledger):
    ag.record(ag.LIKE, target="https://x.com/a/status/1")
    first = ledger.read_bytes()
    inode = os.stat(ledger).st_ino

    ag.record(ag.REPLY, target="https://x.com/b/status/2")

    content = ledger.read_bytes()
    assert os.stat(ledger).st_ino == inode
    assert content.startswith(first) and len(content) > len(first)
    lines = content.decode().splitlines()
    assert [json.loads(line)["action"] for line in lines] == [ag.LIKE, ag.REPLY]
    assert not os.path.exists(str(ledger) + ".tmp")


def test_legacy_list_is_read_as_is_then_converted_on_the_first_write(ledger):
    today = _now().replace(hour=9, minute=0).isoformat()
    legacy = [_row(ag.POST, today), _row(ag.POST, today, dry_run=True),
              _row(ag.FOLLOW, "2026-08-01T10:00:00", target="alice"),
              _row(ag.REPLY, today, target="https://x.com/c/status/3")]
    raw = json.dumps(legacy)
    ledger.write_text(raw)

    assert ag.count_today(ag.POST) == 1
    assert ag.last_touch("alice") is not None
    # A read-only caller (status skill, dry run) leaves the file untouched.
    assert ledger.read_text() == raw

    ag.record(ag.POST)

    lines = ledger.read_text().splitlines()
    assert [json.loads(line) for line in lines[:-1]] == legacy
    assert json.loads(lines[-1])["action"] == ag.POST
    assert ag.count_today(ag.POST) == 2
    assert ag._load_ledger()[:-1] == legacy


def test_retention_pass_drops_old_rows_at_most_once_a_day(ledger, monkeypatch):
    old = (datetime.now() - timedelta(days=ag._RETENTION_DAYS + 10)).isoformat()
    recent = (datetime.now() - timedelta(days=2)).isoformat()
    ledger.write_text(_jsonl([_row(ag.FOLLOW, old, "old"), _row(ag.FOLLOW, recent, "recent")]))

    ag.record(ag.LIKE)
    assert [r["target"] for r in ag._load_ledger()] == ["recent", ""]

    # Same Toronto day: an old row written since stays until tomorrow's pass.
    with open(ledger, "a") as f:
        f.write(json.dumps(_row(ag.FOLLOW, old, "late")) + "\n")
    inode = os.stat(ledger).st_ino
    ag.record(ag.LIKE)
    assert os.stat(ledger).st_ino == inode
    assert "late" in [r["target"] for r in ag._load_ledger()]

    tomorrow = _now() + timedelta(days=1)
    monkeypatch.setattr(ag, "now_local", lambda: tomorrow)
    ag.record(ag.LIKE)
    assert [r["target"] for r in ag._load_ledger()] == ["recent", "", "", ""]


def test_cut_short_last_line_is_ignored_then_dropped_by_the_next_write(ledger):
    today = _now().isoformat()
    good = _jsonl([_row(ag.POST, today), _row(ag.REPLY, today)])
    ledger.write_text(good + '{"action": "post", "ta')

    assert ag.count_today(ag.POST) == 1
    assert len(ag._load_ledger()) == 2

    ag.record(ag.POST)

    lines = ledger.read_text().splitlines()
    assert len(lines) == 3 and all(json.loads(line) for line in lines)
    assert ag.count_today(ag.POST) == 2


def test_last_row_without_final_newline_counts_and_the_next_write_adds_it(ledger):
    today = _now().isoformat()
    ledger.write_text(_jsonl([_row(ag.LIKE, today)]) + json.dumps(_row(ag.POST, today)))

    assert [r["action"] for r in ag._load_ledger()] == [ag.LIKE, ag.POST]
    assert ag.count_today(ag.POST) == 1

    ag.record(ag.LIKE)

    lines = ledger.read_text().splitlines()
    assert [json.loads(line)["action"] for line in lines] == [ag.LIKE, ag.POST, ag.LIKE]
    assert ag.count_today(ag.POST) == 1


def test_bytes_glued_to_a_row_without_newline_are_not_read_incrementally(ledger):
    today = _now().isoformat()
    ledger.write_text(_jsonl([_row(ag.LIKE, today)]) + json.dumps(_row(ag.POST, today)))
    assert ag.count_today(ag.POST) == 1

    with open(ledger, "a") as f:
        f.write(json.dumps(_row(ag.POST, today)) + "\n")

    with pytest.raises(StateUnreadable):
        ag.count_today(ag.POST)


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
def test_corrupt_ledger_refuses_reads_and_writes(ledger, content):
    ledger.write_text(content)

    with pytest.raises(StateUnreadable, match="ledger unreadable"):
        ag.count_today(ag.POST)
    with pytest.raises(StateUnreadable):
        ag.record(ag.POST)
    assert ledger.read_text() == content


def test_failed_rewrite_leaves_the_ledger_and_no_temporary_file(ledger, monkeypatch):
    raw = json.dumps([_row(ag.POST, _now().isoformat())])
    ledger.write_text(raw)

    def refuse(fd):
        raise OSError("disk full")

    monkeypatch.setattr(ag, "_fsync", refuse)
    with pytest.raises(StateUnreadable, match="could not be saved"):
        ag.record(ag.LIKE)

    assert ledger.read_text() == raw
    assert not os.path.exists(str(ledger) + ".tmp")


def test_rewrite_flushes_the_file_then_its_directory(ledger, monkeypatch):
    flushed = []
    fsync = ag._fsync

    def spy(fd):
        flushed.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        fsync(fd)

    monkeypatch.setattr(ag, "_fsync", spy)
    ledger.write_text(json.dumps([_row(ag.POST, _now().isoformat())]))

    ag.record(ag.LIKE)

    # Conversion: the temporary file, then the directory; then the append.
    assert flushed == ["file", "dir", "file"]


def test_fsync_falls_back_when_full_fsync_is_refused(monkeypatch, tmp_path):
    synced = []
    monkeypatch.setattr(ag.fcntl, "F_FULLFSYNC", 51, raising=False)

    def refuse(fd, cmd):
        raise OSError("not supported")

    monkeypatch.setattr(ag.fcntl, "fcntl", refuse)
    monkeypatch.setattr(ag.os, "fsync", synced.append)
    with open(tmp_path / "f", "wb") as f:
        ag._fsync(f.fileno())
        assert synced == [f.fileno()]


def test_cache_notices_a_same_size_rewrite_that_keeps_the_mtime(ledger):
    today = _now().isoformat()
    ledger.write_text(_jsonl([_row(ag.POST, today), _row(ag.REPLY, today)]))
    assert ag.count_today(ag.POST) == 1
    before = os.stat(ledger)

    ledger.write_text(_jsonl([_row(ag.LIKE, today), _row(ag.REPLY, today)]))
    os.utime(ledger, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(ledger)
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_ino, before.st_size, before.st_mtime_ns)

    assert ag.count_today(ag.POST) == 0


def test_cache_follows_writes_made_by_another_process(ledger):
    today = _now().isoformat()
    ag.record(ag.POST)
    assert ag.count_today(ag.POST) == 1

    with open(ledger, "a") as f:
        f.write(json.dumps(_row(ag.POST, today)) + "\n")
    assert ag.count_today(ag.POST) == 2

    # Rewritten in place (same inode), shorter and then longer.
    ledger.write_text(_jsonl([_row(ag.REPLY, today)]))
    assert ag.count_today(ag.POST) == 0
    ledger.write_text(_jsonl([_row(ag.FOLLOW, today, target="x" * 200)] * 3))
    assert ag.count_today(ag.FOLLOW) == 3

    # Replaced by another file, as a restore or a compaction does.
    other = ledger.with_name("restored.json")
    other.write_text(json.dumps([_row(ag.POST, today)] * 4))
    os.replace(other, ledger)
    assert ag.count_today(ag.POST) == 4

    ledger.unlink()
    assert ag._load_ledger() == []


def test_write_and_check_on_a_large_ledger_parse_only_the_new_line(ledger, monkeypatch):
    base = datetime.now() - timedelta(days=30)
    rows = [_row(ag.LIKE if i % 2 else ag.REPLY, (base + timedelta(seconds=40 * i)).isoformat(),
                 target=f"https://x.com/u{i}/status/{i}") for i in range(50_000)]
    ledger.write_text(_jsonl(rows))
    assert len(ag._load_ledger()) == 50_000

    parsed = []
    parse_lines = ag._parse_lines

    def counting(data):
        out = parse_lines(data)
        parsed.append(len(out[0]))
        return out

    monkeypatch.setattr(ag, "_parse_lines", counting)
    monkeypatch.setattr(ag, "_parse_list", lambda data: pytest.fail("full list parse"))
    monkeypatch.setattr(ag, "is_active", lambda *a, **k: True)
    monkeypatch.setattr(ag, "stop_requested", lambda: False)
    inode = os.stat(ledger).st_ino

    ag.record(ag.LIKE, target="https://x.com/new/status/1")
    ag.can_post(ag.REPLY)

    assert sum(parsed) == 1
    assert os.stat(ledger).st_ino == inode
    assert len(ag._load_ledger()) == 50_001
