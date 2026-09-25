"""State store: every state file of the bot, under state/<BOT_ACCOUNT>/.

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
scheduler threads never lose each other's changes. The action ledger and
the Replied store keep their own implementations.

Every state path resolves at call time through `root()`, the one place that
knows where the state lives: `state/<BOT_ACCOUNT>/` (issue #207). A file
the store neither reads nor writes (the ledger, the Replied store, logs and
reports) is declared as a `StatePath`, which any `open()` or `os.path`
call takes. Before issue #207 the state lived at the project root, and it
is LEGACY_ACCOUNT's: `require_migrated()`, which main.py and the scripts
that write state call first, refuses while a root file is missing from
state/<LEGACY_ACCOUNT>/ or differs from its copy there, whichever Account
runs, and bin/migrate_state.py moves it.
"""
import copy
import fcntl
import filecmp
import json
import os
import tempfile
import threading

from . import account, settings
from .json_safety import sanitize_for_json
from .logger import log
from .state_errors import StateUnreadable

PROJECT_ROOT = os.path.abspath(settings.PROJECT_ROOT)
# Relative to the project root, like accounts/.
STATE_DIR = "state"
# Where the state lived before issue #207; tests point it at an empty folder.
LEGACY_DIR = PROJECT_ROOT
# The only Account before issue #207: the state at the project root is its
# own, whichever Account BOT_ACCOUNT names now.
LEGACY_ACCOUNT = "theaishrink"

# Every file the bot kept at the project root before issue #207. Frozen: a
# state file born later never lived there.
LEGACY_FILES = (
    "action_ledger.json", "codex_lockout.json", "directives.md", "discovered_accounts.json",
    "dynamic_accounts.json", "editorial_reach.json", "editorial_reach.md",
    "editorial_review.jsonl", "editorial_state.json", "engagement_log.csv",
    "engagement_targets_log.json", "follow_engagers_state.json", "follow_quality_rejects.json",
    "followed_accounts.json", "follower_history.json", "followers_seen.json",
    "following_count.json", "like_bot_state.json", "liked_tweets.json",
    "mass_unfollow_results.json", "personality.json", "pin_daily_state.json",
    "pin_history.json", "pruned_accounts.json", "reinforced_accounts.json",
    "replied_back.json", "replied_tweets.json", "safari_health.json",
    "safari_hygiene_state.json", "tracked_accounts.json", "tweet_history.json",
    "whitelist_discovered.json",
)


def root() -> str:
    """state/<BOT_ACCOUNT>/, absolute: the folder of the running Account's
    state. It may not exist yet: `ensure_root` creates it."""
    return os.path.join(PROJECT_ROOT, STATE_DIR, account.current().name)


def ensure_root() -> str:
    """`root()`, created when missing. main.py calls it at start, and each
    script that writes state."""
    path = root()
    os.makedirs(path, exist_ok=True)
    return path


def legacy_root() -> str:
    """state/<LEGACY_ACCOUNT>/, absolute: where the state of the project
    root belongs."""
    return os.path.join(PROJECT_ROOT, STATE_DIR, LEGACY_ACCOUNT)


def _left_at_root(copy_there: str) -> list:
    """The LEGACY_FILES at the project root whose copy in `legacy_root()`
    is "missing", "identical" or "different", as `copy_there` asks."""
    found = []
    for name in LEGACY_FILES:
        here, there = os.path.join(LEGACY_DIR, name), os.path.join(legacy_root(), name)
        if not os.path.lexists(here):
            continue
        if not os.path.lexists(there):
            state = "missing"
        else:
            state = "identical" if _same_bytes(here, there) else "different"
        if state == copy_there:
            found.append(name)
    return found


def _same_bytes(a: str, b: str) -> bool:
    regular = all(os.path.isfile(p) and not os.path.islink(p) for p in (a, b))
    try:
        return regular and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def unmigrated() -> list:
    """The LEGACY_FILES still at the project root and missing from
    `legacy_root()`: started now, the bot would read them as empty, and an
    empty ledger resets today's ceiling."""
    return _left_at_root("missing")


def conflicting() -> list:
    """The LEGACY_FILES both at the project root and in `legacy_root()`,
    with different bytes: the root copy may hold today's rows."""
    return _left_at_root("different")


class Unmigrated(Exception):
    """State files still at the project root: nothing may start on the
    empty or older ones under `legacy_root()`."""


def require_migrated() -> None:
    """Raise Unmigrated, naming the files, while a root file is missing from
    `legacy_root()` or differs from its copy there; log a warning for a root
    file identical to its copy."""
    shown = os.path.join(STATE_DIR, LEGACY_ACCOUNT)
    refusals = []
    left = unmigrated()
    if left:
        refusals.append(f"state files still at the project root, missing from {shown}/, "
                        f"where the state of {LEGACY_ACCOUNT}, the only Account before issue "
                        f"#207, belongs: {', '.join(left)}. Stop the bot and run "
                        f"bin/migrate_state.py")
    both = conflicting()
    if both:
        refusals.append(f"state files both at the project root and in {shown}/, with different "
                        f"bytes: {', '.join(both)}. Compare each pair by hand, keep the right "
                        f"one in {shown}/ (for the ledger, the one holding today's rows), and "
                        f"move the other outside the checkout")
    if refusals:
        raise Unmigrated("; ".join(refusals) + " (docs/OPERATIONS.md#deploying-issue-207)")
    for name in _left_at_root("identical"):
        log.warning(f"[STATE] {name} is both at the project root and in {shown}/, identical: "
                    f"bin/migrate_state.py removes the root copy.")


def bot_holds_lock(project_root: str) -> bool:
    """Same lock as main.py: flock on <project_root>/bot.lock, released when
    python exits. The scripts that write state check it first."""
    path = os.path.join(project_root, "bot.lock")
    if not os.path.exists(path):
        return False
    with open(path) as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


class StatePath(os.PathLike):
    """A state file the store neither reads nor writes: its name, resolved
    under `root()` at each use."""

    def __init__(self, name: str):
        self.name = name

    def __fspath__(self) -> str:
        return os.path.join(root(), self.name)

    def __str__(self) -> str:
        return self.__fspath__()

    def __repr__(self) -> str:
        return f"StatePath({self.name!r})"

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
        return os.path.join(root(), self.name)

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
