"""Slot journal: the editorial state of the Toronto day, and its one owner.

It answers what the editorial cycle and the reach report ask of that state:

- the day: `roll_to` starts a new Toronto day; each day-scoped query names
  its day and reads nothing of another one;
- a Slot's Attempts and the Editor's feedback on its last Attempt;
- the Pending slot's life: `reserve` before the submission, then `confirm`
  once it shipped or `release` when nothing was sent;
- the Slots closed for a day (pending or published), the source URLs
  already used, the recent texts (published and pending), the day's
  submissions and the latest one.

The file, `editorial_state.json`, keeps its format:

    {"date": "YYYY-MM-DD",
     "slots": {"<slot>": "pending" | "published"},
     "attempts": {"<slot>": n}, "feedback": {"<slot>": "reason"},
     "published": [{"ts", "text", "source_url", "angle", "slot"}],
     "pending_sources": {"YYYY-MM-DD/<slot>": {"url", "text", "ts"}}}

A Startup post's slot is `startup@HH:MM:SS`. Keys the journal does not
know are kept as they are.

Two adapters: `FileJournal` reads the guarded file once when made and
writes it whole at each change; `MemoryJournal` holds it in memory for
tests. Both keep the state in memory between two saves: every change saves,
the day change alone waits for the next one. The editorial cycle's lock and
its one-thread executor exclude two writers.
"""
import copy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import NamedTuple, Optional

from ..core.state_store import GUARDED, StateFile

# Guarded: it holds the Pending slots and the spent Attempts.
STATE = StateFile("editorial_state.json", {}, GUARDED)
# Publications carried into a new day: the recent texts and used sources.
KEPT_PUBLISHED = 90
# A source published within this span is not used again.
USED_SOURCE_DAYS = 7
FEEDBACK_MAX_CHARS = 500


def stamp(raw):
    """An ISO or RFC 2822 (feed) timestamp in UTC, None when it is missing,
    malformed or naive."""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(raw)
        except (ValueError, TypeError):
            return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


class Submissions(NamedTuple):
    """A day's submissions the journal knows: its Slots marked published,
    and its pending submissions."""
    published: int
    pending: int


class SlotJournal:
    """The queries and changes of both adapters, on the state `_data`."""

    def __init__(self, data: dict):
        self._data = data

    def _save(self) -> None:
        raise NotImplementedError

    def _holds(self, day: date) -> bool:
        return self._data.get("date") == day.isoformat()

    def _of(self, day: date) -> dict:
        """The state of `day`, empty when the journal holds another day."""
        return self._data if self._holds(day) else {}

    def _pending_key(self, clock: str) -> str:
        # Keyed by day too: tomorrow's same Slot must not overwrite it.
        return f"{self._data['date']}/{clock}"

    # --- the day ------------------------------------------------------------

    def roll_to(self, day: date) -> None:
        """Hold `day`. A new day starts with no closed Slot, Attempt or
        feedback, and keeps the latest publications and every pending
        submission: those may be live. Saved with the next change."""
        if self._holds(day):
            return
        self._data = {"date": day.isoformat(), "slots": {},
                      "published": self._data.get("published", [])[-KEPT_PUBLISHED:],
                      "pending_sources": self._data.get("pending_sources", {})}

    def closed(self, clock: str, day: date) -> bool:
        """`clock` is pending or published on `day`."""
        return clock in self._of(day).get("slots", {})

    def attempts(self, clock: str, day: date) -> int:
        return self._of(day).get("attempts", {}).get(clock, 0)

    def feedback(self, clock: str, day: date) -> str:
        """The Editor's reason on `clock`'s last Attempt of `day`, or ""."""
        return self._of(day).get("feedback", {}).get(clock, "")

    def submissions(self, day: date) -> Submissions:
        """`day`'s Slots marked published, and its pending submissions: in
        `pending_sources` or a Slot marked pending, the Operator's hand
        edits included."""
        slots = self._of(day).get("slots", {})
        prefix = f"{day.isoformat()}/"
        pending = {key for key in self._data.get("pending_sources", {}) if key.startswith(prefix)}
        pending |= {prefix + clock for clock, mark in slots.items() if mark == "pending"}
        return Submissions(published=sum(1 for mark in slots.values() if mark == "published"),
                           pending=len(pending))

    # --- changes of the held day ---------------------------------------------

    def spend_attempt(self, clock: str) -> None:
        attempts = self._data.setdefault("attempts", {})
        attempts[clock] = attempts.get(clock, 0) + 1
        self._save()

    def note_feedback(self, clock: str, reason) -> None:
        self._data.setdefault("feedback", {})[clock] = str(reason)[:FEEDBACK_MAX_CHARS]
        self._save()

    def reserve(self, clock: str, url: str, text: str, at: datetime) -> None:
        """Mark `clock` pending before its submission: until confirmed or
        released, its source and text stay out of later Drafts, and it
        counts toward the ceiling and the spacing."""
        self._data.setdefault("slots", {})[clock] = "pending"
        self._data.setdefault("pending_sources", {})[self._pending_key(clock)] = dict(
            url=url, text=text, ts=at.isoformat())
        self._save()

    def confirm(self, clock: str, url: str, text: str, angle: str, at: datetime) -> None:
        """The reserved submission of `clock` shipped at `at`."""
        del self._data["pending_sources"][self._pending_key(clock)]
        self._data["slots"][clock] = "published"
        self._data.setdefault("published", []).append(
            dict(ts=at.isoformat(), text=text, source_url=url, angle=angle, slot=clock))
        self._save()

    def release(self, clock: str) -> None:
        """The reserved submission of `clock` sent nothing: the Slot opens
        again."""
        del self._data["slots"][clock]
        del self._data["pending_sources"][self._pending_key(clock)]
        self._save()

    # --- every day -----------------------------------------------------------

    def published(self) -> list:
        """The publications kept, oldest first."""
        return list(self._data.get("published", []))

    def used_urls(self, now: datetime) -> set:
        """Source URLs published within USED_SOURCE_DAYS of `now`, and every
        pending one: an ambiguous submission may be live."""
        floor = datetime.min.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(days=USED_SOURCE_DAYS)
        used = {r["source_url"] for r in self._data.get("published", [])
                if (stamp(r.get("ts", "")) or floor) > cutoff}
        return used | {p["url"] for p in self._data.get("pending_sources", {}).values()}

    def recent_texts(self) -> list:
        """The published texts, then the pending ones."""
        return ([p["text"] for p in self._data.get("published", [])]
                + [p["text"] for p in self._data.get("pending_sources", {}).values()])

    def last_submission(self) -> Optional[datetime]:
        """The latest pending or published submission time, any day."""
        entries = (*self._data.get("pending_sources", {}).values(), *self._data.get("published", []))
        return max((s for s in (stamp(e.get("ts", "")) for e in entries) if s), default=None)

    def get(self, key, default=None):
        """One key of the file format, read only: the tests that still read
        the state as a dict (#232 moves them to the journal)."""
        return self._data.get(key, default)


class FileJournal(SlotJournal):
    """The journal kept in editorial_state.json, read when made:
    StateUnreadable while the file is unreadable."""

    def __init__(self):
        super().__init__(STATE.read())

    def _save(self) -> None:
        STATE.write(self._data)


class MemoryJournal(SlotJournal):
    """The journal in memory, for tests: FileJournal's answers without its
    file. `data` seeds it as the file would hold it; `saved` is a copy of
    the state at the last save, None before one."""

    def __init__(self, data: Optional[dict] = None):
        super().__init__(copy.deepcopy(data) if data else {})
        self.saved: Optional[dict] = None

    def _save(self) -> None:
        self.saved = copy.deepcopy(self._data)
