"""The Reply pipeline, tested once for every job: Reply admission before the
model call, the posts set aside, the stop on an unreadable state file or at
bedtime, the rate-limit stop, the spacing wait, the log after ship. The
model is the fake LLM, the chokepoint a stub in twitter_client; Reply
admission, the Replied store, the ledger and the engagement log are real
(tests/conftest.py points their files at tmp_path)."""
import math
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.core import config
from src.core.llm_client import LLM_RATE_LIMIT_CODE, LLMResult
from src.core.state_errors import StateUnreadable
from src.guards import replied_store
from src.guards.active_hours import OutsideActiveHours
from src.replies import reply_pipeline as rp
from src.x import x_urls
from src.x.confirmed_write import WriteOutcome
# The real chokepoint, before the chokepoint fixture replaces it.
from src.x.twitter_client import reply_to_tweet as REAL_REPLY_TO_TWEET
from tests.helpers import fresh, stop_requested
from tests.replies.fakes import logged

FAILED_CALL = LLMResult(1, "", "model down")
RATE_LIMITED = LLMResult(LLM_RATE_LIMIT_CODE, "", "hourly budget")
MODES = [pytest.param(False, id="in-turn"), pytest.param(True, id="pipelined")]


def job(**options):
    from src.replies.reply_generator import Voice

    voice = Voice("Parent: {tweet_text}", "model", "TEST", identity=False)
    options.setdefault("voice", lambda author: voice)
    return rp.Job(options.pop("name", "test_job"), "TEST", **options)


def candidate(url, text):
    return rp.Candidate(url, text, f"TEST/{text}")


def run(the_job, candidates, cycle=None, **budgets):
    return rp.run(the_job, candidates, cycle or rp.Cycle(), **budgets)


def set_aside(name="test_job"):
    return rp._skipped.get(name, set())


def corrupt_replied_store():
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")


# --- Reply admission comes first ----------------------------------------------


@pytest.mark.parametrize("pipelined", MODES)
def test_admission_comes_before_the_generation(llm, chokepoint, pipelined):
    answered = fresh("someone", n=1)
    replied_store.claim(answered)
    refused = {
        fresh("pgm_pm", n=2): "post blocked",
        fresh(config.BOT_HANDLE, n=3): "post own",
        answered: "post answered",
        "https://x.com/i/web/status/" + x_urls.status_id(fresh("x", n=4)): "post no author",
    }
    ok = fresh("someone", n=5)
    candidates = [candidate(u, t) for u, t in refused.items()] + [candidate(ok, "post admitted")]

    assert run(job(pipelined=pipelined), candidates) == 1

    assert llm.parents("post admitted", *refused.values()) == ["post admitted"], \
        "no generation for a post admission refuses"
    assert chokepoint.sent == [ok]
    assert set_aside() == set(refused) | {ok}, "definitive refusals and answered posts are set aside"


def test_a_temporary_refusal_stays_replayable(llm, chokepoint, monkeypatch):
    from src.guards import action_guard
    from src.guards.reply_admission import Refusal

    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "1")
    action_guard.record(action_guard.DEBATE_TURN, target="capped")
    capped, admitted = fresh("capped", n=1), fresh("someone", n=2)
    cycle = rp.Cycle()

    run(job(debate_turn=True), [candidate(capped, "post capped"), candidate(admitted, "post admitted")], cycle)

    assert llm.parents("post capped", "post admitted") == ["post admitted"]
    assert [(c.url, c.debate_turn) for c in chokepoint.calls] == [(admitted, True)]
    assert set_aside() == {admitted}, "the Debate turn cap is temporary"
    assert cycle.refusals == {Refusal.DEBATE_TURN_CAP.value: 1}, "counted for the job's summary"


def test_each_job_sets_aside_its_own_posts(llm, chokepoint):
    url = fresh("someone")
    llm.default = "SKIP"

    run(job(name="one"), [candidate(url, "post")])
    run(job(name="other"), [candidate(url, "post")])

    assert len(llm.calls) == 2, "a decline under one voice is not a decline under another"
    assert set_aside("one") == set_aside("other") == {url}


# --- What is set aside, what is replayed ---------------------------------------


@pytest.mark.parametrize("pipelined", MODES)
def test_a_decline_is_set_aside_and_failures_are_replayed(llm, chokepoint, pipelined):
    declined, failed, bounced = fresh("someone", n=1), fresh("other", n=2), fresh("third", n=3)
    llm.answers.update({"post declined": "SKIP", "post failed": FAILED_CALL})
    chokepoint.answer = WriteOutcome.REFUSED
    texts = ("post declined", "post failed", "post bounced")
    candidates = [candidate(declined, texts[0]), candidate(failed, texts[1]), candidate(bounced, texts[2])]

    for _cycle in range(2):
        run(job(pipelined=pipelined), candidates)

    assert llm.parents(*texts) == ["post declined", "post failed", "post bounced",
                                   "post failed", "post bounced"], \
        "a SKIP is not paid twice; a failed call or a chokepoint refusal is replayed"
    assert set_aside() == {declined}
    assert replied_store.load_replied() == set(), "nothing shipped, nothing marked"


@pytest.mark.parametrize("pipelined", MODES)
def test_other_errors_leave_the_post_replayable(llm, chokepoint, monkeypatch, pipelined):
    """A write or a generation that raises is logged; the cycle moves on."""
    from src.replies import reply_generator

    broken_write, broken_prompt, ok = fresh("someone", n=1), fresh("other", n=2), fresh("third", n=3)
    chokepoint.answer = lambda url: RuntimeError("Safari hiccup") if url == broken_write else True
    real = reply_generator.generate

    def generate(voice, *, text, **kwargs):
        if text == "post broken":
            raise KeyError("template field")
        return real(voice, text=text, **kwargs)

    monkeypatch.setattr(reply_generator, "generate", generate)
    candidates = [candidate(broken_write, "post one"), candidate(broken_prompt, "post broken"),
                  candidate(ok, "post three")]

    assert run(job(pipelined=pipelined), candidates) == 1

    assert chokepoint.sent == [broken_write, ok]
    assert set_aside() == {ok}


# --- Errors that end the cycle -------------------------------------------------


@pytest.mark.parametrize("pipelined", MODES)
def test_an_unreadable_replied_store_stops_before_the_model(llm, chokepoint, pipelined):
    corrupt_replied_store()
    candidates = [candidate(fresh("someone", n=i), f"post {i}") for i in range(2)]

    with pytest.raises(StateUnreadable):
        run(job(pipelined=pipelined), candidates)

    assert llm.calls == [] and chokepoint.sent == []


@pytest.mark.parametrize("pipelined", MODES)
@pytest.mark.parametrize("error", [StateUnreadable("replied store unreadable"),
                                   OutsideActiveHours("stop requested")], ids=["unreadable", "bedtime"])
@pytest.mark.parametrize("where", ["write", "generation"])
def test_errors_that_end_the_cycle_are_never_swallowed(llm, chokepoint, monkeypatch, pipelined, error, where):
    from src.replies import reply_generator

    if where == "write":
        chokepoint.answer = error
    else:
        monkeypatch.setattr(reply_generator, "generate", lambda *a, **k: (_ for _ in ()).throw(error))
    candidates = [candidate(fresh("someone", n=i), f"post {i}") for i in range(3)]

    with pytest.raises(type(error)):
        run(job(pipelined=pipelined), candidates)

    assert len(chokepoint.sent) == (1 if where == "write" else 0), "the cycle ends at the first error"
    assert set_aside() == set()


@pytest.mark.parametrize("pipelined", MODES)
def test_a_stop_request_ends_the_cycle_before_admission(llm, chokepoint, monkeypatch, pipelined):
    stop_requested(monkeypatch)
    with pytest.raises(OutsideActiveHours):
        run(job(pipelined=pipelined), [candidate(fresh("someone"), "post")])
    assert llm.calls == [] and chokepoint.sent == []


def test_a_scrape_that_fails_reads_as_nothing_found():
    def broken():
        raise RuntimeError("blank page")

    assert rp.scrape("TEST", "@someone", broken) == []
    assert rp.scrape("TEST", "@someone", lambda: None) == []


@pytest.mark.parametrize("error", [StateUnreadable("ledger unreadable"), OutsideActiveHours("22:00")])
def test_a_scrape_lets_bedtime_and_unreadable_state_through(error):
    def scrape():
        raise error

    with pytest.raises(type(error)):
        rp.scrape("TEST", "@someone", scrape)


# --- Rate limit and budgets ------------------------------------------------------


@pytest.mark.parametrize("pipelined, calls", [(False, 1), (True, 2)])
def test_the_rate_limit_ends_the_cycle(llm, chokepoint, pipelined, calls):
    """Pipelined, the generation already submitted runs; no other starts."""
    llm.default = RATE_LIMITED
    cycle = rp.Cycle()
    candidates = [candidate(fresh("someone", n=i), f"post {i}") for i in range(4)]

    assert run(job(pipelined=pipelined), candidates, cycle) == 0
    assert run(job(pipelined=pipelined), candidates, cycle) == 0, "the next run of the cycle admits nothing"

    assert len(llm.calls) == calls and cycle.rate_limited
    assert chokepoint.sent == [] and set_aside() == set(), "a rate-limited post stays replayable"


def test_budgets_bound_shipped_replies_or_generations(llm, chokepoint):
    candidates = [candidate(fresh("someone", n=i), f"post {i}") for i in range(4)]

    assert run(job(), candidates, max_shipped=1) == 1 and len(llm.calls) == 1
    llm.calls.clear()
    chokepoint.answer = WriteOutcome.REFUSED
    assert run(job(), candidates, max_generations=2) == 0 and len(llm.calls) == 2
    llm.calls.clear()
    chokepoint.answer = True
    assert run(job(pipelined=True), candidates, max_generations=1) == 1 and len(llm.calls) == 1


def test_a_pipelined_job_takes_no_shipped_budget():
    with pytest.raises(ValueError):
        run(job(pipelined=True), [], max_shipped=1)


# --- Sending and logging -------------------------------------------------------------


def test_a_shipped_reply_is_logged_once_with_its_source(llm, chokepoint):
    from src.core import personality_store

    shipped, refused = fresh("someone", n=1), fresh("other", n=2)
    llm.default = "Batching is where margins live — not the model.\n[PATTERN: RENAME]"
    chokepoint.answer = lambda url: True if url == shipped else WriteOutcome.UNCONFIRMED

    run(job(), [candidate(shipped, "post one"), candidate(refused, "post two")])

    sent = chokepoint.calls[0].text
    assert "—" not in sent and "[PATTERN" not in sent, "humanized, pattern tag stripped"
    assert [(r.url, r.source, r.text, r.pattern) for r in logged()] == [(shipped, "TEST/post one", sent, "RENAME")]
    assert personality_store.get_account("someone")["interaction_count"] == 1, "the dossier bump"
    assert personality_store.get_account("other") is None


def test_callers_never_premark_the_replied_store(llm, chokepoint):
    """2026-06-07 post-mortem: five bots wrote the URL into the Replied store
    before posting, and the chokepoint refused its own caller every time."""
    url = fresh("someone")
    chokepoint.answer = lambda u: u in replied_store.load_replied()

    run(job(), [candidate(url, "post")])

    assert chokepoint.sent == [url] and logged() == []


def test_a_written_reply_skips_the_generation(llm, chokepoint):
    url = fresh("someone")
    written = rp.Candidate(url, "the parent", "", reply="Batching wins.", pattern="RENAME")

    assert run(job(voice=None), [written]) == 1

    assert llm.calls == [] and chokepoint.calls[0].text == "Batching wins."
    assert [(r.source, r.pattern) for r in logged()] == [("", "RENAME")]


def test_a_reply_out_of_the_job_text_bounds_is_not_sent(llm, chokepoint):
    url = fresh("someone")
    llm.default = "Yes."

    assert run(job(text_bounds=(10, 270)), [candidate(url, "post")]) == 0

    assert chokepoint.sent == [] and set_aside() == set(), "replayable"


def test_the_job_pace_follows_each_shipped_reply(llm, chokepoint, monkeypatch):
    slept = []
    monkeypatch.setattr(rp, "_sleep", slept.append)
    shipped = [fresh("someone", n=1), fresh("other", n=2)]
    chokepoint.answer = lambda url: url in shipped
    candidates = [candidate(u, f"post {i}") for i, u in enumerate(shipped + [fresh("third", n=3)])]

    run(job(pause=(5, 12)), candidates)

    assert len(slept) == 2 and all(5 <= s <= 12 for s in slept), "one pause per shipped Reply"


def test_pipelined_generation_overlaps_posting(llm, chokepoint):
    """2026-06-09 (operator: 'BOT REALLY SLOW... ACCELERATE'): reply N+1
    starts generating while reply N is still posting."""
    import threading

    second_started = threading.Event()
    llm.answers["post two"] = lambda prompt: second_started.set() or "a sharp take for the second post"

    def post(url):
        if not chokepoint.calls[:-1]:
            assert second_started.wait(timeout=5), "the second generation never started during the first post"
        return True

    chokepoint.answer = post
    candidates = [candidate(fresh("usera", n=1), "post one"), candidate(fresh("userb", n=2), "post two")]

    assert run(job(pipelined=True), candidates) == 2
    assert sorted(llm.parents("post one", "post two")) == ["post one", "post two"]


# --- Reply spacing in the pipelined jobs (#131) -----------------------------------------


@pytest.fixture
def spacing(llm, chokepoint, monkeypatch, memory_ledger):
    """A Toronto noon clock that the pipeline's sleeps advance. The stub
    chokepoint records each Reply in the ledger, as a ship would."""
    from src.guards import action_guard as ag, active_hours

    s = SimpleNamespace(chokepoint=chokepoint, slept=[], waited_at_send=[], gap_after_send=[],
                        on_sleep=lambda: None, ledger=memory_ledger,
                        now=datetime(2026, 9, 21, 12, tzinfo=ZoneInfo("America/Toronto")))
    monkeypatch.setattr(active_hours, "now_local", lambda: s.now)
    monkeypatch.setattr(ag, "now_local", lambda: s.now)

    def sleep(seconds):
        s.slept.append(seconds)
        # Round up like time.sleep, which never returns early.
        s.now += timedelta(microseconds=math.ceil(seconds * 1_000_000))
        s.on_sleep()

    def ship(url):
        s.waited_at_send.append(sum(s.slept))
        assert ag.seconds_until_allowed(ag.REPLY) == 0, "sent before the spacing cleared"
        ag.record(ag.REPLY, url)
        # The clock stands still: the whole gap is left to wait.
        s.gap_after_send.append(ag.seconds_until_allowed(ag.REPLY))
        return True

    monkeypatch.setattr(rp, "_sleep", sleep)
    chokepoint.answer = ship
    return s


def test_a_pipelined_job_waits_out_the_spacing_after_its_own_reply(spacing):
    s = spacing
    candidates = [candidate(fresh("someone", n=1), "one"), candidate(fresh("other", n=2), "two")]

    assert run(job(pipelined=True), candidates) == 2

    assert s.waited_at_send == [0, pytest.approx(s.gap_after_send[0])]
    assert all(0 < step <= 1.0 for step in s.slept), "short slices, so a stop cuts the wait"


def test_a_pipelined_job_does_not_wait_when_the_spacing_is_clear(spacing):
    from src.guards import action_guard as ag

    s = spacing
    ag.record(ag.REPLY, fresh("earlier"))
    s.now += timedelta(seconds=60)
    url = fresh("someone", n=1)

    assert run(job(pipelined=True), [candidate(url, "post")]) == 1

    assert s.slept == [] and s.chokepoint.sent == [url]


def test_a_job_in_turn_never_waits_for_the_spacing(spacing):
    """The wait is the pipelined jobs' own: a job in turn keeps its rhythm,
    and the chokepoint refuses a Reply sent too early."""
    from src.guards import action_guard as ag

    s = spacing
    ag.record(ag.REPLY, fresh("earlier"))
    s.chokepoint.answer = WriteOutcome.REFUSED
    url = fresh("someone", n=1)

    assert run(job(), [candidate(url, "post")]) == 0

    assert s.slept == [] and s.chokepoint.sent == [url]
    assert url not in set_aside(), "the post stays replayable"


def test_a_reply_from_another_job_during_the_wait_is_refused_unconsumed(spacing, monkeypatch):
    """The chokepoint stays the judge: another job's Reply lands mid-wait,
    the real reply_to_tweet refuses on spacing before Safari, writes no
    ledger row, and the post stays replayable."""
    from src.guards import action_guard as ag, reply_admission
    from src.guards.reply_admission import Refusal
    from src.x import twitter_client as tc

    s = spacing
    monkeypatch.setattr(config, "REPLY_JITTER_SECONDS", 0)  # every gap is exactly the minimum
    ag.record(ag.REPLY, fresh("earlier"))

    def another_job_replies_after_the_first_slice():
        if len(s.slept) == 1:
            ag.record(ag.REPLY, fresh("elsewhere", n=9))

    s.on_sleep = another_job_replies_after_the_first_slice
    verdicts = []
    judge = reply_admission.judge_reply
    monkeypatch.setattr(reply_admission, "judge_reply",
                        lambda *a, **k: verdicts.append(judge(*a, **k)) or verdicts[-1])
    monkeypatch.setattr(tc, "reply_to_tweet", REAL_REPLY_TO_TWEET)
    url, cycle = fresh("someone", n=1), rp.Cycle()

    assert run(job(pipelined=True), [candidate(url, "post")], cycle) == 0

    assert sum(s.slept) == config.MIN_SECONDS_BETWEEN_REPLIES
    assert [v.refusal for v in verdicts] == [Refusal.SPACING]
    assert s.ledger.count(ag.REPLY, s.now.date()) == 2, "only the earlier Reply and the other job's"
    assert url not in set_aside() and url not in replied_store.load_replied()
    assert url in cycle.tried, "tried again next cycle, with a new generation"


@pytest.mark.parametrize("cut", ["stop", "overnight"])
def test_the_spacing_wait_ends_on_a_stop_request_and_overnight(spacing, monkeypatch, cut):
    import threading
    from src.guards import action_guard as ag, active_hours

    s = spacing
    stop = threading.Event()
    monkeypatch.setattr(active_hours, "_STOP", stop)

    def cut_short():
        if cut == "stop":
            stop.set()
        else:
            s.now = s.now.replace(hour=22, minute=0, second=0)

    ag.record(ag.REPLY, fresh("earlier"))
    s.on_sleep = cut_short

    with pytest.raises(active_hours.OutsideActiveHours):
        run(job(pipelined=True), [candidate(fresh("someone", n=1), "post")])

    assert len(s.slept) == 1, "the next slice sees the stop or 22:00"
    assert s.chokepoint.sent == [], "nothing ships"
    assert s.ledger.count(ag.REPLY, s.now.date()) == 1
