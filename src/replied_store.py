"""Replied store: the tweets the account already answered, keyed on status ID.

`reply_to_tweet` is the only writer that matters: it claims a tweet with
`claim()` right before the Safari write, so two reply loops racing on the
same tweet cannot both ship. Bot cycles read the store to skip taken tweets
before paying for a generation.

Fails closed like the action ledger (issue #100): an unreadable or
malformed file raises `StateUnreadable` instead of reading as empty, because an empty store
lets every duplicate through. Writes go to a temp file then `os.replace`,
so a concurrent reader never sees a half-written list, and the
read-merge-write runs under one lock so parallel jobs cannot drop each
other's entries. Recovery: docs/OPERATIONS.md#recovery.
"""
import json
import os
import tempfile
import threading

from . import config, x_urls
from .state_errors import StateUnreadable

_REPLIED_CAP = 50000
_write_lock = threading.Lock()


def canonical_tweet_id(url: str) -> str:
    """Extract the status ID from a tweet URL.

    Status IDs are globally unique on X, but the SAME tweet can surface
    under multiple author URLs because feed-scraping sometimes mis-attributes
    the author handle (e.g. when a tweet shows in a profile via quote / RT
    context). Dedup keyed on the raw URL string would let the same tweet
    get replied to multiple times under different scraped prefixes.

    Bug 2026-05-17: status 2056061134629933072 got 3 replies same day under
    @elonmusk, @ABaradez, @LeJournalDuCoin URLs — all same actual tweet.
    """
    if not url:
        return ""
    return x_urls.status_id(url) or url.strip().lower()


class CanonReplied(set):
    """Set wrapper that canonicalizes URLs to status IDs on add/contains.
    Lets existing call sites use `url in replied` / `replied.add(url)`
    unchanged while the underlying storage is keyed on status ID."""

    def __contains__(self, item) -> bool:
        return super().__contains__(canonical_tweet_id(item))

    def add(self, item) -> None:
        super().add(canonical_tweet_id(item))

    def update(self, items) -> None:
        for x in items:
            self.add(x)


def _read_entries() -> list:
    """Ordered on-disk entries; a missing file is an empty store."""
    try:
        with open(config.REPLIED_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise StateUnreadable("Replied store unreadable; refusing replies that could duplicate") from exc
    if isinstance(data, dict):
        data = data.get("urls")
    if not isinstance(data, list):
        raise StateUnreadable("Replied store is not a list; refusing replies that could duplicate")
    return [u for u in data if isinstance(u, str) and u]


def _write_entries(entries: list) -> None:
    entries = entries[-_REPLIED_CAP:]
    path = config.REPLIED_FILE
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               prefix=".replied_tweets.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(exc, OSError):
            raise StateUnreadable("Replied store could not be saved") from exc
        raise


def _merge(entries: list, urls) -> int:
    """Append to `entries` the status IDs of `urls` it lacks, preserving
    order; return how many were added."""
    known = {canonical_tweet_id(u) for u in entries}
    added = 0
    for u in urls:
        cid = canonical_tweet_id(u) if isinstance(u, str) else ""
        if cid and cid not in known:
            entries.append(cid)
            known.add(cid)
            added += 1
    return added


def load_replied() -> CanonReplied:
    """Return a canonicalizing set so `url in replied` dedupes on status ID."""
    s = CanonReplied()
    s.update(_read_entries())
    return s


def save_replied(urls) -> None:
    """Merge `urls` into the on-disk store, newest last, capped at 50k.

    Bug 2026-05-16: slicing a Python set (`list(urls)[-2000:]`) randomly
    dropped half the store and let bots reply twice days later. The merge
    re-reads the file under the lock, so a parallel job's entries survive.
    """
    with _write_lock:
        entries = _read_entries()
        if _merge(entries, urls):
            _write_entries(entries)


def claim(url: str) -> bool:
    """Mark `url` as replied; False when it already was.

    Check and mark happen under one lock, so two threads claiming the same
    tweet cannot both win.
    """
    with _write_lock:
        entries = _read_entries()
        if not _merge(entries, [url]):
            return False
        _write_entries(entries)
    return True


def release(url: str) -> None:
    """Drop `url` from the store after a claim that sent nothing.

    Only reply_to_tweet calls this, when its Safari sequence stopped before
    the submit keystroke. A job that holds the claim in its own loaded set
    may save it back later: the tweet then stays taken, the safe side.
    """
    cid = canonical_tweet_id(url)
    with _write_lock:
        entries = _read_entries()
        kept = [u for u in entries if canonical_tweet_id(u) != cid]
        if len(kept) != len(entries):
            _write_entries(kept)
