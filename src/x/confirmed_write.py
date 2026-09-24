"""The confirmed-write sequence shared by every write chokepoint of
`twitter_client`: admission, dry run, Safari lock, page steps, ledger rows
for a confirmed write only, tab cleanup. A chokepoint supplies its guards,
its page steps and its ledger rows; the order lives here once.

A guard returns None to go on, or the outcome that ends the write. `steps`
opens the page first thing and returns the outcome of the write; ledger
rows are written only when that outcome is truthy, which only a shipped
write is."""
from enum import Enum
from typing import Callable, Sequence, TypeVar

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


# An outcome enum: `WriteOutcome`, or `LikeOutcome` for the like. Both are
# truthy only for the shipped write and both carry DRY_RUN, FAILED and
# UNCONFIRMED.
O = TypeVar("O", bound=Enum)

Rows = Callable[[], list[tuple[str, str | None]]]


class _DryRunExit:
    def __repr__(self):
        return "DRY_RUN_EXIT"


# Where, in a chokepoint's guards, a dry run stops: every guard before it
# runs in a dry run too, every guard after it runs live only.
DRY_RUN_EXIT = _DryRunExit()

Guards = Sequence[Callable[[], O | None] | _DryRunExit]

# Outcomes that sent nothing because of a failure, or may have reached X:
# they get their own log line. A refusal already has the guard's line.
_FAILURES = ("FAILED", "UNCONFIRMED")


def run(tag: str, outcomes: type[O], *, would: Callable[[], str], rows: Rows,
        steps: Callable[[], O], before_lock: Guards[O] = (), under_lock: Guards[O] = (),
        after_record: Callable[[], None] | None = None, close_tab: bool = True) -> O:
    """Run one write of `outcomes`, in this order:

    1. `before_lock`, in order.
    2. Take the Safari lock, released on every path.
    3. `under_lock`, in order.
    4. `steps`: the page steps, opening the page first.
    5. On a truthy outcome only: `rows()` in the ledger, then `after_record`.
    6. With `close_tab`, close the tab `steps` opened. A stop raised there
       never hides a shipped write.

    `DRY_RUN_EXIT` sits exactly once in `before_lock` or `under_lock`. When
    DRY_RUN is on there, the write logs "[TAG][DRY_RUN] would <would()>",
    writes `rows()` as dry-run rows and returns `outcomes.DRY_RUN`.
    """
    if sum(isinstance(guard, _DryRunExit) for guard in (*before_lock, *under_lock)) != 1:
        raise ValueError(f"[{tag}] needs exactly one DRY_RUN_EXIT among its guards")
    outcome = _admit(tag, outcomes, would, rows, before_lock)
    if outcome is not None:
        return outcome
    with safari._safari_lock:
        outcome = _admit(tag, outcomes, would, rows, under_lock)
        if outcome is not None:
            return outcome
        outcome = steps()
        if outcome:
            _record(rows())
            if after_record is not None:
                after_record()
        if close_tab:
            try:
                safari.close_front_tab()
            except OutsideActiveHours:
                if not outcome:
                    raise
    return outcome if outcome else _stopped(tag, outcome)


def _admit(tag: str, outcomes: type[O], would: Callable[[], str], rows: Rows,
           guards: Guards[O]) -> O | None:
    for guard in guards:
        if isinstance(guard, _DryRunExit):
            if config.dry_run():
                log.info(f"[{tag}][DRY_RUN] would {would()}")
                _record(rows(), dry_run=True)
                return outcomes["DRY_RUN"]
            continue
        outcome = guard()
        if outcome is not None:
            return _stopped(tag, outcome)
    return None


def _record(rows: list[tuple[str, str | None]], dry_run: bool = False) -> None:
    flags = {"dry_run": True} if dry_run else {}
    for action, target in rows:
        if target is None:
            action_guard.record(action, **flags)
        else:
            action_guard.record(action, target=target, **flags)


def _stopped(tag: str, outcome: O) -> O:
    log_line = log.info if outcome.name in _FAILURES else log.debug
    log_line(f"[{tag}] Write {outcome.value}; nothing recorded.")
    return outcome
