"""Follow run: one cycle's follows, from a job's candidates to the chokepoint.

A job keeps its source, its order and its caps, and asks the run to follow
its picks one at a time. The run skips the Followed accounts, whatever the
case of the handle, and each handle it already tried; it asks
`twitter_client.follow_account`, which keeps every rule of the follow
policy, and hands the outcome back to the job.

Past CAP_REACHED the run asks no more: the daily cap, the following ceiling
and the ratio brake do not come back within a cycle. TOO_SOON leaves it
open, since the spacing may elapse during the cycle. Only
`OutsideActiveHours` and `StateUnreadable` end the run, as in the Reply
pipeline; any other error is logged and costs the one pick.
"""
import traceback

from ..core.logger import log
from ..core.state_store import StateUnreadable
from ..guards import follow_policy
from ..guards.active_hours import OutsideActiveHours
from ..x import twitter_client


class FollowRun:
    """One job's follows for one cycle. Raises StateUnreadable, before any
    follow, while followed_accounts.json cannot be read."""

    def __init__(self, label: str):
        self._label = label  # the log prefix, "FOLLOW-ENGAGERS"…
        self._followed = {h.lower() for h in follow_policy.followed()}
        self._tried = set()
        self._cap_reached = False

    def fresh(self, handles) -> list:
        """`handles` in order, without the Followed accounts, the handles
        this run tried, and repeats, whatever the case."""
        seen = set(self._followed | self._tried)
        kept = []
        for h in handles:
            if h.lower() not in seen:
                seen.add(h.lower())
                kept.append(h)
        return kept

    def follow(self, handle: str) -> "twitter_client.FollowOutcome | None":
        """The chokepoint's outcome for `handle`; CAP_REACHED without asking
        once the run met it; None, with nothing asked, for a Followed
        account or a handle already tried, and for a pick that failed."""
        if not self.fresh([handle]):
            return None
        if self._cap_reached:
            return twitter_client.FollowOutcome.CAP_REACHED
        self._tried.add(handle.lower())
        try:
            outcome = twitter_client.follow_account(handle)
        except (OutsideActiveHours, StateUnreadable):
            raise
        except Exception:
            log.info(f"[{self._label}] Follow @{handle} failed:")
            traceback.print_exc()
            return None
        if outcome is twitter_client.FollowOutcome.CAP_REACHED:
            self._cap_reached = True
        return outcome
