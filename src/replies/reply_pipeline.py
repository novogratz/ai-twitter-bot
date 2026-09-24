"""Reply pipeline: a job's candidates in, shipped Replies out.

A job keeps its source (scrape, selection filters, order, budgets) and its
voice. Everything between a candidate and a logged Reply happens here, the
same way for every job: Reply admission before the model call, the posts
each job sets aside until restart, the rate-limit stop, the spacing wait of
the pipelined jobs, the write through `twitter_client.reply_to_tweet`, and
the engagement log after a shipped Reply only.

Only `OutsideActiveHours` and `StateUnreadable` end a cycle: the first is
bedtime or a stop request, the second a state file no Reply can ship
without. Any other error in a scrape, a generation or a write is logged and
leaves the post replayable.
"""
import random
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from ..core import engagement_log
from ..core.humanizer import humanize
from ..core.logger import log
from ..core.pattern_tags import extract_pattern
from ..core.state_errors import StateUnreadable
from ..guards import action_guard
from ..guards.active_hours import OutsideActiveHours, require_active
from ..guards.reply_admission import judge_parent
from ..x import twitter_client
from . import reply_generator
from .reply_generator import Generation, Outcome, Voice


@dataclass(frozen=True)
class Job:
    """How one Reply job runs its candidates."""
    # Jobs with the same name share the posts they set aside.
    name: str
    label: str  # the log prefix, "EARLYBIRD", "SEARCH-HOT"…
    # The voice for the author Reply admission read from the status URL.
    voice: Callable[[str], Voice] | None = None
    debate_turn: bool = False
    # Generate the next candidate while this one posts, and wait out the
    # Reply spacing before each send (#131). Sequential jobs never wait: the
    # chokepoint refuses a Reply sent too early, and the post stays replayable.
    pipelined: bool = False
    # Seconds slept after a shipped Reply, drawn in this range.
    pause: tuple[int, int] = (0, 0)
    # Reply text lengths the job sends, after humanize.
    text_bounds: tuple[int, int] | None = None


@dataclass(frozen=True)
class Candidate:
    """A post a job wants to answer, past the job's own filters."""
    url: str
    text: str
    source: str  # the engagement log tag, "EARLYBIRD/sama"
    context: str = ""  # the post the parent answers (replyback)
    # Reply text the reply search wrote while finding the post: no generation.
    reply: str = ""
    pattern: str = ""


@dataclass
class Cycle:
    """One pass of a job, across its pipeline runs."""
    tried: set = field(default_factory=set)  # admitted this cycle, in memory only
    rate_limited: bool = False
    refusals: Counter = field(default_factory=Counter)  # Reply admission refusals by value


# Posts each job is done with until restart, by job name: definitive Reply
# admission refusals, posts the model declined, posts answered. Temporary
# refusals, failed generations and failed writes stay replayable.
_skipped: dict[str, set] = {}

_SPACING_WAIT_SLICE_SECONDS = 1.0
_sleep = time.sleep


def run(job: Job, candidates, cycle: Cycle, *, max_generations: int | None = None,
        max_shipped: int | None = None) -> int:
    """Answer `candidates` in order; returns the Replies shipped.

    `max_generations` bounds the candidates admitted (the generations paid),
    `max_shipped` the Replies shipped; a pipelined job takes the first only.
    Nothing is admitted once `cycle.rate_limited` is set."""
    if job.pipelined:
        if max_shipped is not None:
            raise ValueError(f"[{job.label}] a pipelined job bounds its generations, not its Replies")
        return _run_pipelined(job, iter(candidates), cycle, max_generations)
    shipped = generations = 0
    for candidate in candidates:
        if cycle.rate_limited or _reached(generations, max_generations) or _reached(shipped, max_shipped):
            break
        author = _admit(job, candidate, cycle)
        if author is None:
            continue
        generations += 1
        try:
            generation = _generate(job, candidate, author)
        except (OutsideActiveHours, StateUnreadable):
            raise
        except Exception:
            traceback.print_exc()  # a failed generation: the post stays replayable
            continue
        if generation.outcome is Outcome.RATE_LIMITED:
            _stop_for_rate_limit(job, cycle)
            break
        shipped += _send(job, candidate, author, generation)
    return shipped


def scrape(label: str, what: str, read: Callable[..., list | None], *args, **kwargs) -> list:
    """A job's scrape, `read(*args, **kwargs)`. A failed one reads as nothing
    found; bedtime and an unreadable state file end the cycle."""
    try:
        return read(*args, **kwargs) or []
    except (OutsideActiveHours, StateUnreadable):
        raise
    except Exception:
        log.info(f"[{label}] Scrape failed for {what}:")
        traceback.print_exc()
        return []


def _reached(count: int, bound: int | None) -> bool:
    return bound is not None and count >= bound


def _set_aside(job: Job) -> set:
    # setdefault is atomic: replyback_job and babysit_job share this set
    # from two scheduler threads.
    return _skipped.setdefault(job.name, set())


def _admit(job: Job, candidate: Candidate, cycle: Cycle) -> str | None:
    """Reply admission, just before the model call: it re-reads the Replied
    store, so a post another job answered since the scrape is dropped here,
    not after a paid generation. Returns the author it read, or None."""
    require_active()
    url = candidate.url
    if url in cycle.tried or url in _set_aside(job):
        return None
    verdict = judge_parent(url, debate_turn=job.debate_turn)
    if not verdict:
        cycle.refusals[verdict.refusal.value] += 1
        if verdict.refusal.definitive:
            _set_aside(job).add(url)
        log.debug(f"[{job.label}] Not admitted ({verdict.refusal.value}: {verdict.reason}): {url}")
        return None
    # In memory only: the chokepoint claims the Replied store itself and
    # refuses anything already in it (2026-06-05 premark bug).
    cycle.tried.add(url)
    return verdict.author


def _generate(job: Job, candidate: Candidate, author: str) -> Generation:
    if candidate.reply:
        # The reply search prompt is English (LanguageRule.ENGLISH).
        return Generation(Outcome.WRITTEN, language="en", text=candidate.reply)
    log.info(f"[{job.label}] Generating reply for @{author}...")
    return reply_generator.generate(job.voice(author), author=author, text=candidate.text,
                                    context=candidate.context)


def _stop_for_rate_limit(job: Job, cycle: Cycle) -> None:
    log.info(f"[{job.label}] LLM rate limit reached; stopping this cycle.")
    cycle.rate_limited = True


def _send(job: Job, candidate: Candidate, author: str, generation: Generation) -> int:
    """Send a generation that is not a rate limit; 1 when the Reply shipped."""
    url = candidate.url
    if generation.outcome is Outcome.DECLINED:
        log.info(f"[{job.label}] The model declined @{author}: set aside.")
        _set_aside(job).add(url)
        return 0
    if generation.outcome is not Outcome.WRITTEN:
        return 0  # a failed generation: the post stays replayable
    reply, pattern_id = extract_pattern(generation.text)
    reply = humanize(reply)
    if job.text_bounds and not job.text_bounds[0] <= len(reply) <= job.text_bounds[1]:
        log.info(f"[{job.label}] Reply of {len(reply)} chars out of {job.text_bounds}: not sent.")
        return 0
    if job.pipelined:
        _wait_out_reply_spacing(job.label)
    log.info(f"[{job.label}] Replying to @{author} ({len(reply)} chars): {reply}")
    try:
        shipped = twitter_client.reply_to_tweet(url, reply, debate_turn=job.debate_turn)
    except (OutsideActiveHours, StateUnreadable):
        raise
    except Exception:
        log.info(f"[{job.label}] Reply failed for {url}:")
        traceback.print_exc()
        return 0
    if not shipped:
        return 0  # the chokepoint's outcome is logged there; no phantom log row
    _set_aside(job).add(url)
    try:
        engagement_log.log_reply(url, reply, "reply", source=candidate.source,
                                 pattern_id=pattern_id or candidate.pattern)
    except Exception:
        log.info(f"[{job.label}] Engagement log failed for a shipped Reply {url}:")
        traceback.print_exc()
    if job.pause[1]:
        _sleep(random.randint(*job.pause))
    return 1


def _run_pipelined(job: Job, candidates, cycle: Cycle, max_generations: int | None) -> int:
    """Reply N+1 generates (worker thread, no Safari lock) while reply N
    posts (2026-06-09, operator: "BOT REALLY SLOW... ACCELERATE"): a cycle
    takes about max(generation, post) per Reply instead of their sum."""
    from concurrent.futures import ThreadPoolExecutor

    shipped = submitted = 0

    def next_generation(pool):
        nonlocal submitted
        if cycle.rate_limited or _reached(submitted, max_generations):
            return None
        for candidate in candidates:
            author = _admit(job, candidate, cycle)
            if author is None:
                continue
            try:
                future = pool.submit(_generate, job, candidate, author)
            except RuntimeError:
                # The executor is shutting down (SIGTERM mid-cycle): end the
                # stream instead of crashing the cycle.
                return None
            submitted += 1
            return candidate, author, future
        return None

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = next_generation(pool)
        while pending is not None:
            candidate, author, future = pending
            # Submit the next generation before blocking on Safari for this
            # one: this line is what buys the overlap.
            upcoming = next_generation(pool)
            try:
                generation = future.result()
            except (OutsideActiveHours, StateUnreadable):
                raise  # bedtime, or no prompt can be built: the next candidates would fail too
            except Exception:
                traceback.print_exc()  # a failed generation: the post stays replayable
                pending = upcoming
                continue
            if generation.outcome is Outcome.RATE_LIMITED:
                _stop_for_rate_limit(job, cycle)
                break  # the generation already submitted runs; its post stays replayable
            # No sleep after a ship: the spacing is waited out before the
            # next send, for the gap action_guard drew.
            shipped += _send(job, candidate, author, generation)
            pending = upcoming
    return shipped


def _wait_out_reply_spacing(label: str) -> None:
    """Wait, outside the Safari lock, for the Reply spacing action_guard will
    require: the next generation is often ready 0-2 s after the last Reply
    and would be refused on spacing, its model call wasted. The chokepoint
    still judges: a Reply from another job during the wait makes it refuse.
    Short slices so a stop request or 22:00 raises OutsideActiveHours."""
    remaining = action_guard.seconds_until_allowed(action_guard.REPLY)
    if remaining > 0:
        log.info(f"[{label}] Waiting {remaining:.1f}s for Reply spacing...")
    while remaining > 0:
        require_active()
        step = min(remaining, _SPACING_WAIT_SLICE_SECONDS)
        _sleep(step)
        remaining -= step
