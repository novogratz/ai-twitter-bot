"""State store: every JSON state file of the bot, under one root.

A module declares its file once, with a default and a policy:

    FOLLOWED = StateFile("followed_accounts.json", [], GUARDED)
    FOLLOWED.read()          # the parsed value, or a copy of the default
    FOLLOWED.write(value)    # atomic
    FOLLOWED.update(fn)      # read, fn, write, under the file's lock

A missing file reads as the default under both policies, so a first start
needs no seeding. A file that does not parse, or whose top-level JSON type
differs from the default's, is unreadable:

- GUARDED: `read` logs and raises `StateUnreadable`, and `write` refuses to
  replace the file, so the job that needs it stops and the Operator repairs
  the file (docs/OPERATIONS.md#recovery). For guardrails and for the records
  that alone stop a write action from repeating.
- DISPOSABLE: `read` logs and returns the default; the next write replaces
  the file. For caches, counters of internal work, reports and harvested
  lists the bot can lose without acting more.

Every write goes to a temp file in the same directory, flushed to the
drive, then `os.replace`d over the file, and the directory is flushed: a
reader never sees half a file, and a crash never brings the old one back.
Each file has one lock: `update` reads, changes and writes under it, so two
scheduler threads never lose each other's changes. Paths resolve at call
time from `ROOT`, the one attribute tests redirect. The action ledger and
the Replied store keep their own implementations.
"""
import copy
import fcntl
import json
import os
import tempfile
import threading

from . import config
from .json_safety import sanitize_for_json
from .logger import log
from .state_errors import StateUnreadable

ROOT = config._PROJECT_ROOT

GUARDED = "guarded"
DISPOSABLE = "disposable"

# One file, one policy and one lock: two modules declaring the same file
# must agree, and share its lock.
_DECLARED: dict = {}


class StateFile:
    def __init__(self, name: str, default, policy: str):
        if policy not in (GUARDED, DISPOSABLE):
            raise ValueError(f"unknown state policy {policy!r}")
        if not isinstance(default, (dict, list)):
            raise TypeError(f"{name}: the default must be a dict or a list")
        declared, lock = _DECLARED.setdefault(name, (policy, threading.RLock()))
        if declared != policy:
            raise ValueError(f"{name} is already declared {declared}")
        self.name = name
        self.policy = policy
        self._default = default
        self._lock = lock

    @property
    def path(self) -> str:
        return os.path.join(ROOT, self.name)

    def default(self):
        return copy.deepcopy(self._default)

    def read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                value = json.load(f)
        except FileNotFoundError:
            return self.default()
        except (OSError, ValueError) as exc:
            return self._unreadable(exc)
        if not isinstance(value, type(self._default)):
            return self._unreadable(f"top-level {type(value).__name__}, "
                                    f"expected {type(self._default).__name__}")
        return value

    def write(self, value) -> None:
        data = json.dumps(sanitize_for_json(value), indent=2, ensure_ascii=False).encode("utf-8")
        with self._lock:
            if self.policy == GUARDED and os.path.exists(self.path):
                self.read()  # raises while the file on disk is unreadable
            try:
                atomic_write_bytes(self.path, data)
            except OSError as exc:
                if self.policy == GUARDED:
                    raise StateUnreadable(f"{self.name} could not be saved: {exc}") from exc
                log.warning(f"[STATE] {self.name} not saved: {exc}")

    def update(self, fn):
        """Read the file, pass the value to `fn`, write what `fn` returns,
        all under the file's lock. `fn` returns None to leave the file as
        it is. Returns what `fn` returned."""
        with self._lock:
            value = fn(self.read())
            if value is not None:
                self.write(value)
            return value

    def _unreadable(self, why):
        if self.policy == GUARDED:
            log.error(f"[STATE] {self.name} is unreadable ({why}): refusing, the file is "
                      f"left as is for the Operator (docs/OPERATIONS.md#recovery).")
            raise StateUnreadable(f"{self.name} is unreadable ({why})")
        log.warning(f"[STATE] {self.name} is unreadable ({why}): using the default.")
        return self.default()


def _fsync(fd: int) -> None:
    """Flush `fd` to the drive itself: on macOS, os.fsync stops at its cache."""
    if hasattr(fcntl, "F_FULLFSYNC"):
        try:
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return
        except OSError:
            pass  # file system without it
    os.fsync(fd)


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Replace `path` with `data`. The temp file is `.<name>.<random>.tmp`
    in the same directory, removed if anything fails before the rename."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o644)
            f.write(data)
            f.flush()
            _fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # The rename lives in the directory: flush it too, or a crash can bring
    # the old file back.
    dfd = os.open(directory, os.O_RDONLY)
    try:
        _fsync(dfd)
    finally:
        os.close(dfd)
