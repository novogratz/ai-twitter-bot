"""The confirmed-write sequence shared by every write chokepoint of
`twitter_client`: admission, dry run, Safari lock, page steps, ledger rows
for a confirmed write only, tab cleanup. A chokepoint supplies its guards,
its page steps and its ledger rows; the order lives here once.

Hooks return None to go on, or the outcome that ends the write. `steps`
opens the page first thing and returns the outcome of the write; ledger
rows are written only when that outcome is truthy, which only a shipped
write is."""
from enum import Enum
from typing import Callable

from ..core import config
from ..core.logger import log
from ..guards import action_guard
from ..guards.active_hours import OutsideActiveHours
from . import safari


class WriteOutcome(Enum):
    """What a write chokepoint did. Truthy only for SHIPPED, so a caller that
    tests the result logs, counts and persists only what shipped."""
    SHIPPED = "shipped"          # confirmed by the page; ledger rows written
    REFUSED = "refused"          # a guard, or the page state, left nothing to write
    FAILED = "failed"            # a page step failed before anything was sent
    UNCONFIRMED = "unconfirmed"  # the write may have reached X; the page never confirmed it
    DRY_RUN = "dry_run"          # DRY_RUN: dry-run ledger rows, nothing sent

    def __bool__(self):
        return self is WriteOutcome.SHIPPED


Hook = Callable[[], Enum | None]
Rows = Callable[[], list[tuple[str, str | None]]]


def _go_on() -> None:
    return None


def _record(rows: list[tuple[str, str | None]], dry_run: bool = False) -> None:
    for action, target in rows:
        kwargs = {} if target is None else {"target": target}
        if dry_run:
            kwargs["dry_run"] = True
        action_guard.record(action, **kwargs)


def _stopped(tag: str, outcome: Enum) -> Enum:
    log.info(f"[{tag}] Write {outcome.value}; nothing recorded.")
    return outcome


def run(tag: str, *, would: Callable[[], str], rows: Rows, steps: Callable[[], Enum],
        admit: Hook = _go_on, before_lock: Hook = _go_on, admit_under_lock: Hook | None = None,
        recheck_under_lock: Hook = _go_on, reserve: Hook = _go_on,
        after_record: Callable[[], None] = _go_on, close_tab: bool = True) -> Enum:
    """Run one write, in this order:

    1. `admit`, before the Safari lock.
    2. The dry-run exit, when there is no `admit_under_lock`: log
       "[TAG][DRY_RUN] would <would()>", write `rows()` as dry-run rows.
    3. `before_lock`: a pause or a last check that needs no browser.
    4. Take the Safari lock, released on every path.
    5. `admit_under_lock`, then the dry-run exit when admission ends here.
    6. `recheck_under_lock`: the admission again, live only, against what
       other threads shipped while this one waited for the browser.
    7. `reserve`: claim the target; `steps` release it if they send nothing.
    8. `steps`: the page steps, opening the page first.
    9. On a truthy outcome only: `rows()` in the ledger, then `after_record`.
    10. With `close_tab`, close the tab `steps` opened. A stop raised there
        never hides a shipped write.
    """
    outcome = admit()
    if outcome is not None:
        return _stopped(tag, outcome)
    if admit_under_lock is None and config.dry_run():
        return _dry_run(tag, would, rows)
    outcome = before_lock()
    if outcome is not None:
        return _stopped(tag, outcome)
    with safari._safari_lock:
        if admit_under_lock is not None:
            outcome = admit_under_lock()
            if outcome is not None:
                return _stopped(tag, outcome)
            if config.dry_run():
                return _dry_run(tag, would, rows)
        for hook in (recheck_under_lock, reserve):
            outcome = hook()
            if outcome is not None:
                return _stopped(tag, outcome)
        outcome = steps()
        if outcome:
            _record(rows())
            after_record()
        if close_tab:
            try:
                safari.close_front_tab()
            except OutsideActiveHours:
                if not outcome:
                    raise
    return outcome if outcome else _stopped(tag, outcome)


def _dry_run(tag: str, would: Callable[[], str], rows: Rows) -> WriteOutcome:
    log.info(f"[{tag}][DRY_RUN] would {would()}")
    _record(rows(), dry_run=True)
    return WriteOutcome.DRY_RUN
