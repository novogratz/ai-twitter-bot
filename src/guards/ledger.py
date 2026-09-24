"""Action ledger: every counted write, and what the write policy asks of it.

A row is {action, target, ts, dry_run}: the action type, the handle or URL
written to (lowercased, no @), the Toronto timestamp, and whether it was a
dry run. A Ledger answers the policy's questions from an index kept up to
date row by row, never by scanning its rows:

- `count`: shipped rows of an action on a Toronto day, of one target if asked;
- `last_write`: the latest shipped row of an action;
- `last_touch`: the latest follow or unfollow of a handle, dry runs included;
- `targets`: the targets of an action's shipped rows, most recent first.

Two adapters: `FileLedger` keeps `action_ledger.json`, `MemoryLedger` holds
the rows in memory for tests. Both answer through the same index.

The file holds one JSON object per line: `append` adds a line, each query
parses only the lines added since the previous read, so rows another process
appends (`bin/mass_unfollow.py`) count from the next query on, and a file
rewritten or replaced is read again in full. Rows past the 90-day retention
are dropped at most once a day. A ledger in the former format, one JSON
list, is read as is and converted in place at the next `append`. A file that
cannot be read refuses every query and every append (StateUnreadable).

The bot is the file's only writer while it runs. The lock is per process:
another process writing at the same time can lose rows when `append`
rewrites the file or drops an unreadable last line. Run
`bin/mass_unfollow.py` with the bot stopped.
"""
import contextlib
import fcntl
import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Protocol, Tuple
from zoneinfo import ZoneInfo

from ..core import config
from ..core.logger import log
from ..core.state_errors import StateUnreadable

# Action types
POST = "post"
QUOTE = "quote"
REPLY = "reply"
FOLLOW = "follow"
UNFOLLOW = "unfollow"
LIKE = "like"
RETWEET = "retweet"
PIN = "pin"
# Bookkeeping row beside REPLY: the answered author, for the per-author cap.
DEBATE_TURN = "debate_turn"


class Ledger(Protocol):
    def append(self, action: str, target: str, dry_run: bool, at: datetime) -> None:
        """Keep one row stamped `at`; StateUnreadable when it cannot be kept."""

    def count(self, action: str, day: date, target: Optional[str] = None) -> int:
        """Shipped rows of `action` on the Toronto `day`, of `target` only
        when given."""

    def last_write(self, action: str) -> Optional[datetime]:
        """Stamp of the latest shipped row of `action`."""

    def last_touch(self, target: str) -> Optional[datetime]:
        """Stamp of the latest follow or unfollow of `target`, dry runs
        included."""

    def targets(self, action: str) -> list:
        """Targets of the shipped rows of `action`, most recent first, once
        each."""


def _target(value) -> str:
    return (value or "").lower().lstrip("@")


def _row(action: str, target: str, dry_run: bool, at: datetime) -> dict:
    return {"action": action, "target": _target(target), "ts": at.isoformat(),
            "dry_run": bool(dry_run)}


def _stamp(ts) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts)
        # Historical entries were recorded using the Toronto host's naive clock.
        dt = dt.replace(tzinfo=ZoneInfo(config.BOT_TIMEZONE)) if dt.tzinfo is None else dt
        dt.timestamp()
        return dt
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _day(stamp: datetime) -> Optional[date]:
    """The Toronto day of `stamp`, None past the calendar's ends (a hand-edited
    `9999-12-31T23:59:00-10:00`): no caller can ask for that day."""
    try:
        return stamp.astimezone(ZoneInfo(config.BOT_TIMEZONE)).date()
    except (OverflowError, ValueError, OSError):
        return None


def _key(value) -> Optional[str]:
    # A hand-edited row can hold any JSON value; only text names something.
    return value if isinstance(value, str) else None


class _Index:
    """The rows, oldest first, and the answer to every query."""

    def __init__(self):
        self.rows: list = []
        self._totals: dict = {}   # (action, Toronto day) -> shipped rows
        self._days: dict = {}     # (action, Toronto day) -> {target: shipped rows}
        self._last: dict = {}     # action -> latest shipped stamp
        self._touch: dict = {}    # target -> latest follow/unfollow ts, as text
        self._targets: dict = {}  # action -> {target: None}, most recent last

    def add(self, rows: Iterable[dict]) -> None:
        # Every key first: a row that fails leaves the index as it was.
        keyed = []
        for row in rows:
            action, target, ts = _key(row.get("action")), _key(row.get("target")), row["ts"]
            shipped = not row.get("dry_run")
            stamp = _stamp(ts) if shipped else None
            day = _day(stamp) if stamp is not None else None
            keyed.append((row, action, target, ts, shipped, stamp, day))
        for row, action, target, ts, shipped, stamp, day in keyed:
            self.rows.append(row)
            if action in (FOLLOW, UNFOLLOW) and ts > self._touch.get(target, ""):
                self._touch[target] = ts
            if not shipped:
                continue
            if stamp is not None:
                last = self._last.get(action)
                # Strictly later: of two equal instants the first row wins.
                if last is None or stamp.timestamp() > last.timestamp():
                    self._last[action] = stamp
            if day is not None:
                key = (action, day)
                self._totals[key] = self._totals.get(key, 0) + 1
                per_target = self._days.setdefault(key, {})
                per_target[target] = per_target.get(target, 0) + 1
            if target:
                seen = self._targets.setdefault(action, {})
                seen.pop(target, None)
                seen[target] = None

    def count(self, action: str, day: date, target: Optional[str] = None) -> int:
        if target is None:
            return self._totals.get((action, day), 0)
        return self._days.get((action, day), {}).get(_target(target), 0)

    def last_write(self, action: str) -> Optional[datetime]:
        return self._last.get(action)

    def last_touch(self, target: str) -> Optional[datetime]:
        ts = self._touch.get(_target(target))
        return _stamp(ts) if ts else None

    def targets(self, action: str) -> list:
        return list(reversed(self._targets.get(action, {})))


class _Queries:
    """The Ledger queries, answered by the adapter's current index."""

    def _current(self) -> _Index:
        raise NotImplementedError

    def count(self, action: str, day: date, target: Optional[str] = None) -> int:
        return self._current().count(action, day, target)

    def last_write(self, action: str) -> Optional[datetime]:
        return self._current().last_write(action)

    def last_touch(self, target: str) -> Optional[datetime]:
        return self._current().last_touch(target)

    def targets(self, action: str) -> list:
        return self._current().targets(action)


class MemoryLedger(_Queries):
    """A Ledger in memory, for tests: FileLedger's answers without its file,
    lock, retention or failure modes. `rows` seeds it with rows as the file would
    hold them."""

    def __init__(self, rows: Iterable[dict] = ()):
        self._index = _Index()
        self._index.add([_checked(r) for r in rows])

    @property
    def rows(self) -> list:
        """Every row, oldest first."""
        return list(self._index.rows)

    def append(self, action: str, target: str, dry_run: bool, at: datetime) -> None:
        self._index.add([_row(action, target, dry_run, at)])

    def _current(self) -> _Index:
        return self._index


# --- the file -------------------------------------------------------------------

_RETENTION_DAYS = 90  # plenty for the 30-day cooldown + audit
# Bytes compared at the head of the file and before the end of the last row
# read, to tell an append (read only the new lines) from a rewrite (read
# everything).
_FINGERPRINT_BYTES = 64
_UNREADABLE = "Action ledger unreadable; refusing unaudited writes"

# Reentrant: append() holds it while _refresh() takes it again. One lock per
# process, shared by every FileLedger.
_LOCK = threading.RLock()


@dataclass
class _View:
    """What the last read of the file saw."""
    ident: Tuple[int, int]  # st_dev, st_ino
    size: int
    mtime_ns: int
    offset: int  # end of the last row read
    prints: Tuple[bytes, bytes]  # _fingerprints at `offset`
    legacy: bool  # the former single JSON list
    unterminated: bool  # the last row has no final newline
    index: _Index


def _checked(row) -> dict:
    # Retention compares `ts` as text: any other type would fail every write.
    if not isinstance(row, dict) or not isinstance(row.get("ts"), str):
        raise StateUnreadable(f"{_UNREADABLE}: a row is not an object with a text ts")
    return row


def _parse_row(line: bytes) -> dict:
    try:
        row = json.loads(line)
    except ValueError as exc:
        raise StateUnreadable(_UNREADABLE) from exc
    return _checked(row)


def _parse_lines(data: bytes) -> Tuple[list, int]:
    """Rows of the complete lines in `data`, and the bytes they span. The
    bytes after the last newline are left to the caller."""
    end = data.rfind(b"\n") + 1
    return [_parse_row(line) for line in data[:end].split(b"\n") if line.strip()], end


def _parse_list(data: bytes) -> list:
    try:
        rows = json.loads(data)
    except ValueError as exc:
        raise StateUnreadable(_UNREADABLE) from exc
    if not isinstance(rows, list):
        raise StateUnreadable(f"{_UNREADABLE}: not a list of objects")
    return [_checked(r) for r in rows]


def _fingerprints(f, offset: int) -> Tuple[bytes, bytes]:
    f.seek(0)
    head = f.read(min(_FINGERPRINT_BYTES, offset))
    start = max(0, offset - _FINGERPRINT_BYTES)
    f.seek(start)
    return head, f.read(offset - start)


def _resume_offset(f, fst, view: Optional[_View]) -> int:
    """Where to resume reading `f`: the end of the last row read when the file
    only grew since, else 0 to read it all."""
    if (view is None or view.ident != (fst.st_dev, fst.st_ino)
            or view.legacy or fst.st_size < view.offset
            or _fingerprints(f, view.offset) != view.prints):
        return 0
    if view.unterminated and fst.st_size > view.offset:
        # Bytes glued to a row without its newline corrupt that row.
        f.seek(view.offset)
        if f.read(1) != b"\n":
            return 0
    return view.offset


def _read(f, fst, start: int, view: Optional[_View]) -> _View:
    """Parse `f` from `start` on; the rows before `start` are in `view`."""
    f.seek(start)
    data = f.read()
    legacy = start == 0 and data.lstrip()[:1] == b"["
    unterminated = False
    if legacy:
        rows, used = _parse_list(data), len(data)
    else:
        rows, used = _parse_lines(data)
        rest, skipped = data[used:], b""
        if rest.strip():
            # A last row whose newline is missing still counts; only an
            # unreadable fragment (an interrupted write) is skipped.
            try:
                rows.append(_parse_row(rest))
                used, unterminated = len(data), True
            except StateUnreadable:
                skipped = rest
        if start == 0 and not rows:
            raise StateUnreadable(f"{_UNREADABLE}: no row")
        if skipped:
            log.warning("[LEDGER] Ignoring an unreadable last line (interrupted write): %r",
                        skipped[:80])
    prints = _fingerprints(f, start + used)
    # Nothing can fail past this point: the index grows only with a new view.
    index = view.index if start else _Index()
    index.add(rows)
    return _View(ident=(fst.st_dev, fst.st_ino), size=start + len(data),
                 mtime_ns=fst.st_mtime_ns, offset=start + used, prints=prints,
                 legacy=legacy, unterminated=unterminated, index=index)


def _fsync(fd: int) -> None:
    """Flush `fd` to the drive itself: on macOS, os.fsync stops at its cache."""
    if hasattr(fcntl, "F_FULLFSYNC"):
        try:
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return
        except OSError:
            pass  # file system without it
    os.fsync(fd)


def _rewrite(path: str, rows: list) -> None:
    """Replace the ledger atomically with `rows`, one JSON object per line."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(b"".join(json.dumps(r).encode() + b"\n" for r in rows))
            f.flush()
            _fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)
    # The rename lives in the directory: flush it too, or a crash can bring
    # the old file back.
    dfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        _fsync(dfd)
    finally:
        os.close(dfd)


class FileLedger(_Queries):
    """The Ledger kept in `path`, one JSON object per line."""

    def __init__(self, path: str):
        self.path = path
        self._view: Optional[_View] = None
        self._compacted_on: Optional[date] = None  # Toronto day of the last retention pass
        # Diagnostic: rows parsed from the file since this ledger was made.
        self.rows_read = 0

    def append(self, action: str, target: str, dry_run: bool, at: datetime) -> None:
        with _LOCK:
            view = self._refresh()  # a corrupt ledger refuses the write here
            rows = view.index.rows if view else []
            row = _row(action, target, dry_run, at)
            try:
                if view and view.legacy:
                    _rewrite(self.path, rows)
                    log.info("[LEDGER] Converted %d rows from a JSON list to one row per line",
                             len(rows))
                elif view and view.size > view.offset:
                    # Appending after an unreadable last line would glue both
                    # into one corrupt line: drop the fragment the read skipped.
                    os.truncate(self.path, view.offset)
                rewritten = self._compact_if_due(rows, at.date())
                lead = b"\n" if view and view.unterminated and not rewritten else b""
                with open(self.path, "ab") as f:
                    f.write(lead + json.dumps(row).encode() + b"\n")
                    f.flush()
                    _fsync(f.fileno())
            except OSError as exc:
                raise StateUnreadable("Action ledger could not be saved") from exc

    def _current(self) -> _Index:
        view = self._refresh()
        return view.index if view else _Index()

    def _refresh(self) -> Optional[_View]:
        """The file as it stands on disk, None when it does not exist."""
        with _LOCK:
            try:
                with open(self.path, "rb") as f:
                    fst = os.fstat(f.fileno())
                    v = self._view
                    if (v is not None and v.ident == (fst.st_dev, fst.st_ino)
                            and (v.size, v.mtime_ns) == (fst.st_size, fst.st_mtime_ns)
                            and _fingerprints(f, v.offset) == v.prints):
                        return v
                    start = _resume_offset(f, fst, v)
                    kept = len(v.index.rows) if start else 0
                    self._view = _read(f, fst, start, v)
                    self.rows_read += len(self._view.index.rows) - kept
            except FileNotFoundError:
                self._view = None
            except OSError as exc:
                raise StateUnreadable(_UNREADABLE) from exc
            return self._view

    def _compact_if_due(self, rows: list, today: date) -> bool:
        """Drop the rows past the retention once per Toronto day; True when
        the file was rewritten."""
        if self._compacted_on == today:
            return False
        cutoff = (datetime.now() - timedelta(days=_RETENTION_DAYS)).isoformat()
        kept = [r for r in rows if r.get("ts", "") >= cutoff]
        rewritten = len(kept) < len(rows)
        if rewritten:
            _rewrite(self.path, kept)
            log.info("[LEDGER] Dropped %d rows older than %d days", len(rows) - len(kept),
                     _RETENTION_DAYS)
        self._compacted_on = today
        return rewritten


_file: Optional[FileLedger] = None


def file_ledger(path: str) -> FileLedger:
    """The FileLedger of `path`, kept across calls so its index lives on."""
    global _file
    with _LOCK:
        if _file is None or _file.path != path:
            _file = FileLedger(path)
        return _file
