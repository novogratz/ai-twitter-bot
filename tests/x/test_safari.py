"""src/x/safari: bedtime checks at the browser lock and before AppleScript."""
from datetime import datetime

import pytest

from src.guards import active_hours as hours
from tests.helpers import TORONTO, clock


def test_browser_wait_rechecks_bedtime(monkeypatch):
    from src.x.safari import _AwakeSafariLock
    clock(monkeypatch, datetime(2026, 9, 20, 21, 59, tzinfo=TORONTO))
    browser = _AwakeSafariLock()
    released = []

    class SlowLock:
        def acquire(self):
            clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))

        def release(self):
            released.append(True)

    browser._lock = SlowLock()
    with pytest.raises(hours.OutsideActiveHours):
        with browser:
            pytest.fail("Browser action ran after bedtime")
    assert released == [True]


def test_submit_checks_bedtime_before_applescript(monkeypatch):
    from src.x import safari
    # Use the real helper (the suite normally prevents Safari calls).
    import importlib
    from unittest.mock import patch
    with patch("subprocess.run") as run:
        safari = importlib.reload(safari)
        clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))
        with pytest.raises(hours.OutsideActiveHours):
            safari._run_applescript("submission")
        run.assert_not_called()
