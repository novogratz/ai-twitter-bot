"""State store: every JSON state file of the bot, under one root.

A module declares its file once, with a default and a policy:

    FOLLOWED = StateFile("followed_accounts.json", [], GUARDED)
    FOLLOWED.read()          # the parsed value, or a copy of the default
    FOLLOWED.write(value)    # atomic

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

Every write goes to a temp file in the same directory, is fsynced, then
`os.replace`d over the file: a reader never sees half a file. Paths resolve
at call time from `ROOT`, the one attribute tests redirect. The action
ledger and the Replied store keep their own implementations.
"""
import copy
import json
import os
import tempfile

from . import config
from .json_safety import sanitize_for_json
from .logger import log
from .state_errors import StateUnreadable

ROOT = config._PROJECT_ROOT

GUARDED = "guarded"
DISPOSABLE = "disposable"

# One file, one policy: two modules declaring the same file must agree.
_DECLARED: dict = {}


class StateFile:
    def __init__(self, name: str, default, policy: str):
        if policy not in (GUARDED, DISPOSABLE):
            raise ValueError(f"unknown state policy {policy!r}")
        if not isinstance(default, (dict, list)):
            raise TypeError(f"{name}: the default must be a dict or a list")
        if _DECLARED.setdefault(name, policy) != policy:
            raise ValueError(f"{name} is already declared {_DECLARED[name]}")
        self.name = name
        self.policy = policy
        self._default = default

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
        if self.policy == GUARDED and os.path.exists(self.path):
            self.read()  # raises while the file on disk is unreadable
        try:
            _replace(self.path, value)
        except OSError as exc:
            if self.policy == GUARDED:
                raise StateUnreadable(f"{self.name} could not be saved: {exc}") from exc
            log.warning(f"[STATE] {self.name} not saved: {exc}")

    def _unreadable(self, why):
        if self.policy == GUARDED:
            log.error(f"[STATE] {self.name} is unreadable ({why}): refusing, the file is "
                      f"left as is for the Operator (docs/OPERATIONS.md#recovery).")
            raise StateUnreadable(f"{self.name} is unreadable ({why})")
        log.warning(f"[STATE] {self.name} is unreadable ({why}): using the default.")
        return self.default()


def _replace(path: str, value) -> None:
    data = json.dumps(sanitize_for_json(value), indent=2, ensure_ascii=False).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o644)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
