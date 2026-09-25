#!/usr/bin/env python3
"""Move the bot's state from the project root to state/<BOT_ACCOUNT>/
(issue #207), once, with the bot stopped: the whole procedure is in
docs/OPERATIONS.md#deploying-issue-207.

    python3 bin/migrate_state.py

Each file of `state_store.LEGACY_FILES` found at the root moves under the
same name to state/<BOT_ACCOUNT>/, its bytes untouched: a hard link names it
there, its SHA-256 is checked against the root file's, and only then is the
root name removed. No file is created empty, rewritten or parsed, and the
Operator files (accounts/<BOT_ACCOUNT>/) are never touched.

It checks everything before it moves anything, and moves nothing if a check
fails: bot.lock must be free, each root file a regular file, and a file
already at the destination must hold the same bytes as the root one; then
only the root name goes, which finishes a run cut short. A second run finds
nothing to move.
"""
import argparse
import errno
import fcntl
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.core import settings, state_store  # noqa: E402


class Refused(Exception):
    """A check failed: nothing was moved."""


class Stopped(Exception):
    """A moved file did not match its root copy: the files before it moved,
    that one and the ones after it did not."""


def bot_holds_lock() -> bool:
    """Same lock as main.py: flock on bot.lock, released when python exits."""
    path = os.path.join(ROOT, "bot.lock")
    if not os.path.exists(path):
        return False
    with open(path) as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: str) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)


def _plan(target: str, shown: str) -> list:
    """(name, sha256, already there) for each root file to move; raises
    Refused on the first file that cannot move."""
    steps = []
    for name in state_store.LEGACY_FILES:
        source = os.path.join(state_store.LEGACY_DIR, name)
        if not os.path.lexists(source):
            continue
        if not _regular(source):
            raise Refused(f"{name} at the project root is not a regular file: move it by hand")
        digest = _sha256(source)
        destination = os.path.join(target, name)
        already = os.path.lexists(destination)
        if already and not (_regular(destination) and _sha256(destination) == digest):
            raise Refused(f"{shown}/{name} exists and differs from {name} at the project root: "
                          f"compare them by hand, keep one, then run again")
        steps.append((name, digest, already))
    return steps


def _place(source: str, destination: str) -> None:
    """Name `source` at `destination`, which must not exist."""
    try:
        os.link(source, destination)
        return
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP):
            raise
    # Another file system: an exclusive copy, flushed, with the root file's
    # mode and times.
    with open(source, "rb") as src, open(destination, "xb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(source, destination)


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def migrate() -> list:
    """Check, then move. Returns the report lines; raises Refused, with
    nothing moved, when a check fails."""
    target = state_store.root()
    shown = os.path.relpath(target, state_store.PROJECT_ROOT)
    steps = _plan(target, shown)
    if not steps:
        return [f"nothing to move: no state file left at the project root, the state is in {shown}/"]
    os.makedirs(target, exist_ok=True)
    report = []
    for name, digest, already in steps:
        source = os.path.join(state_store.LEGACY_DIR, name)
        destination = os.path.join(target, name)
        if not already:
            _place(source, destination)
        if _sha256(destination) != digest:
            raise Stopped("\n".join(report + [
                f"{shown}/{name} does not match {name} at the project root after the move: "
                f"both are kept, compare them by hand, then run again"]))
        os.unlink(source)
        report.append(f"{name}: {'already in ' + shown + '/, identical' if already else 'moved to ' + shown + '/'}"
                      f", sha256 {digest[:12]}")
    _fsync_dir(target)
    _fsync_dir(state_store.LEGACY_DIR)
    moved = sum(1 for _, _, already in steps if not already)
    report.append(f"moved {moved} files, {len(steps) - moved} already there; the root holds no state file")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args()
    settings.load()
    if bot_holds_lock():
        print("bot.lock is held: stop the bot and its supervisor first", file=sys.stderr)
        sys.exit(1)
    try:
        report = migrate()
    except Refused as exc:
        print(f"REFUSED, nothing moved: {exc}", file=sys.stderr)
        sys.exit(1)
    except Stopped as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        sys.exit(1)
    for line in report:
        print(line)


if __name__ == "__main__":
    main()
