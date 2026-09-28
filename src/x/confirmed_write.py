"""The confirmed-write sequence shared by every write chokepoint of
`twitter_client`: admission, dry run, page session, page steps, ledger rows
for a confirmed write only, tab cleanup. A chokepoint supplies its guards,
its page steps and its ledger rows; the order lives here once.

A guard returns None to go on, or the outcome that ends the write. `steps`
receives the session's page, opens it first thing and returns the outcome
of the write; a page that does not open ends it in FAILED. Ledger rows are
written only when that outcome is truthy, which only a shipped write is."""
from enum import Enum
from typing import Callable, Sequence, TypeVar

from ..core import config
from ..core.logger import log
from ..guards import action_guard
from ..guards.active_hours import OutsideActiveHours
from . import page_session


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


# An outcome enum: `WriteOutcome`, `LikeOutcome` for the like or
# `FollowOutcome` for the follow. Each is truthy only for the shipped write
# and carries DRY_RUN and FAILED; the first two carry UNCONFIRMED too.
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
        steps: Callable[[page_session.Page], O], before_lock: Guards[O] = (),
        under_lock: Guards[O] = (), after_record: Callable[[], None] | None = None) -> O:
    """Run one write of `outcomes`, in this order:

    1. `before_lock`, in order.
    2. Take a page session named `tag`, which holds the Safari lock.
    3. `under_lock`, in order, before any page opens.
    4. `steps(page)`: the page steps, opening the page first. A page that
       does not open (`PageNotOpened`) is FAILED.
    5. On a truthy outcome only: `rows()` in the ledger, then `after_record`.
    6. The session closes the tab `steps` opened, on every path, a raising
       step included, and releases the lock. At bedtime or on a stop,
       `require_active()` refuses that close and the tab stays open. A stop
       raised at the close, once the whole body ran, never hides a shipped
       write; one raised by the steps or `after_record` propagates. A
       write nested in another session, a like on a walk's page, opens
       nothing and closes nothing.

    `DRY_RUN_EXIT` sits exactly once in `before_lock` or `under_lock`. When
    DRY_RUN is on there, the write logs "[TAG][DRY_RUN] would <would()>",
    writes `rows()` as dry-run rows and returns `outcomes.DRY_RUN`.
    """
    if sum(isinstance(guard, _DryRunExit) for guard in (*before_lock, *under_lock)) != 1:
        raise ValueError(f"[{tag}] needs exactly one DRY_RUN_EXIT among its guards")
    outcome = _admit(tag, outcomes, would, rows, before_lock)
    if outcome is not None:
        return outcome
    outcome, finished = None, False
    try:
        with page_session.session(tag) as page:
            outcome = _admit(tag, outcomes, would, rows, under_lock)
            if outcome is not None:
                return outcome
            try:
                outcome = steps(page)
            except page_session.PageNotOpened:
                outcome = outcomes["FAILED"]
            if outcome:
                _record(rows())
                if after_record is not None:
                    after_record()
            finished = True
    except OutsideActiveHours:
        if not (finished and outcome):
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
    log_line(f"[{tag}] Write {outcome.value}; no ledger row.")
    return outcome
