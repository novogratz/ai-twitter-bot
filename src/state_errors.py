"""Errors raised by the fail-closed state files (action ledger, replied store)."""


class StateUnreadable(RuntimeError):
    """A fail-closed state file cannot be read or saved. The bot refuses the
    write; restarting Safari cannot fix it, so health.record_failure does not
    count it (docs/OPERATIONS.md#recovery)."""
