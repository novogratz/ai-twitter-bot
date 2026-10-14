import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core import account, reply_queue
from src.core.llm_client import LLMResult, Surface
from src.core.state_errors import StateUnreadable
from src.guards import action_guard, active_hours, reply_admission, reply_pacing, replied_store
from src.replies import reply_pipeline as pipeline, reply_selection as selection
from src.replies.reply_generator import Generation, Outcome, ReplyCall
from src.x import twitter_client, x_urls
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, fresh


TEXT = "Memory bandwidth is the inference bottleneck."
PARENT = "AI inference depends on memory bandwidth and batching."


@pytest.fixture
def clock(monkeypatch):
    now = [datetime(2026, 10, 14, 8, 0, tzinfo=TORONTO)]
    monkeypatch.setattr(active_hours, "now_local", lambda: now[0])
    monkeypatch.setattr(action_guard, "now_local", lambda: now[0])
    return now


def stage(handle="builder", n=1, text=TEXT):
    candidate = pipeline.Candidate(fresh(handle, n=n), PARENT, "TEST/" + handle)
    sid = reply_queue.reserve(candidate)
    assert sid
    reply_queue.prepared(sid, text, Generation(Outcome.WRITTEN, "en", text, "fake", "writer"), "OTHER")
    return sid


def review(score=4, **overrides):
    return dict(impact=score, sharpness=score, interest=score, grounded=True, on_topic=True,
                support="The parent explicitly identifies memory bandwidth.",
                reason="A precise, useful answer to this parent.", **overrides)


@pytest.fixture
def reviewer(monkeypatch):
    calls, scores = [], {}
    def answer(prompt, model, **kwargs):
        calls.append((prompt, kwargs))
        ids = kwargs["profile"].schema["required"]
        return LLMResult(0, json.dumps({sid: scores.get(sid, review()) for sid in ids}), "")
    monkeypatch.setattr(selection, "run_llm", answer)
    return calls, scores


@pytest.fixture
def publisher(monkeypatch, memory_ledger):
    sent = []
    def send(url, text, **kwargs):
        verdict = reply_admission.judge_reply(url, text)
        assert verdict, verdict
        assert reply_pacing.reserve(url)
        assert replied_store.claim(url)
        action_guard.record(action_guard.REPLY, url)
        sent.append((url, text))
        return WriteOutcome.SHIPPED
    monkeypatch.setattr(twitter_client, "reply_to_tweet", send)
    return sent


def test_collectors_prepare_without_publishing_and_deduplicate_model_work(clock, monkeypatch):
    generated = []
    monkeypatch.setattr(pipeline, "_generate", lambda *a: generated.append(a) or Generation(Outcome.WRITTEN, "en", TEXT))
    monkeypatch.setattr(twitter_client, "reply_to_tweet", lambda *a, **k: pytest.fail("collector published"))
    job = pipeline.Job("one", "ONE", lambda _: ReplyCall("{tweet_text}", Surface.REPLY, "TEST"))
    candidate = pipeline.Candidate(fresh("builder"), PARENT, "TEST")
    for _ in range(2):
        assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    assert len(generated) == 1 and len(reply_queue.ready()) == 1


@pytest.mark.parametrize("handle,parent,context", [
    ("elonmusk", PARENT, ""), ("thesimaximalist", PARENT, ""),
    ("TheAIShrink", PARENT, ""), ("someone", "@another AI inference", ""),
    ("someone", PARENT, "An earlier post"), ("someone", "A lovely lunch", ""),
    ("someone", "AI news for @elonmusk", ""),
])
def test_ineligible_parents_never_reach_preparation(clock, monkeypatch, handle, parent, context):
    monkeypatch.setattr(pipeline, "_generate", lambda *a: pytest.fail("drafted a forbidden target"))
    job = pipeline.Job("test", "TEST", lambda _: None)
    assert pipeline.run(job, [pipeline.Candidate(fresh(handle), parent, "TEST", context)], pipeline.Cycle()) == 0
    assert reply_queue.ready() == {}


def test_startup_collects_choices_then_publishes_the_best_one(clock, reviewer, publisher):
    first = stage("one", 1)
    best = stage("two", 2, "Batching trades latency for throughput.")
    reviewer[1][best] = review(5)
    assert selection.run_selection_cycle() == 0 and not reviewer[0]
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert len(publisher) == 1 and x_urls.status_id(publisher[0][0]) == best
    assert first in reply_queue.ready()
    assert selection.run_selection_cycle() == 0 and len(publisher) == 1
    # Same prepared choices cannot send again until the shared deadline.
    wait = action_guard.seconds_until_allowed(action_guard.REPLY)
    assert 300 <= wait <= 480
    clock[0] += timedelta(seconds=wait + 0.001)
    assert selection.run_selection_cycle() == 1 and len(publisher) == 2


@pytest.mark.parametrize("bad", [
    {"impact": 3}, {"sharpness": 3}, {"interest": 3}, {"grounded": False}, {"on_topic": False},
])
def test_no_weak_or_unsupported_draft_is_forced_when_the_slot_is_due(clock, reviewer, publisher, bad):
    sid = stage()
    reviewer[1][sid] = {**review(5), **bad}
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 0
    assert publisher == [] and reply_queue.ready() == {}
    assert reply_pacing.PACE.read() == {}


@pytest.mark.parametrize("response", [
    '{}', '[]', '{"invented": {}}', '{"123": {}, "123": {}}',
    json.dumps({"123": {**review(), "impact": True}}),
    json.dumps({"123": {**review(), "support": ""}}),
    json.dumps({"123": {**review(), "interest": 6}}),
])
def test_comparison_rejects_missing_duplicate_or_malformed_scores(response):
    with pytest.raises((ValueError, TypeError)):
        selection._parse(response, ["123"])


def test_review_schema_requires_each_supplied_id_once():
    schema = selection._schema(["123", "456"])
    assert set(schema["required"]) == set(schema["properties"]) == {"123", "456"}
    assert schema["additionalProperties"] is False


def test_provider_failure_never_falls_back_to_unreviewed_draft(clock, monkeypatch, publisher):
    stage()
    clock[0] += timedelta(seconds=61)
    monkeypatch.setattr(selection, "run_llm", lambda *a, **k: LLMResult(1, "", "failed"))
    assert selection.run_selection_cycle() == 0 and not publisher
    assert list(reply_queue.ready().values())[0]["status"] == "ready"


def test_only_exact_selected_text_and_parent_can_pass_the_final_gate(clock):
    sid = stage()
    row = reply_queue.ready()[sid]
    assert reply_admission.judge_reply(row["url"], TEXT).refusal is reply_admission.Refusal.UNSELECTED
    reply_queue.reviewed({sid: row}, {sid: {**review(5), "reviewed_at": clock[0].isoformat()}})
    row = reply_queue.ready()[sid]
    assert reply_queue.select(sid, row)
    assert reply_admission.judge_reply(row["url"], TEXT)
    assert not reply_admission.judge_reply(row["url"], "A different unreviewed reply.")
    assert reply_queue.matches_parent(row["url"], PARENT)
    assert not reply_queue.matches_parent(row["url"], "A changed AI claim.")
    assert not reply_queue.is_selected(row["url"].replace("builder", "other"), TEXT)
    clock[0] += timedelta(minutes=5)
    assert not reply_queue.is_selected(row["url"], TEXT)


def test_stale_drafts_and_selected_after_crash_are_not_automatically_replayed(clock):
    sid = stage()
    row = reply_queue.ready()[sid]
    reply_queue.reviewed({sid: row}, {sid: {**review(5), "reviewed_at": clock[0].isoformat()}})
    assert reply_queue.select(sid, reply_queue.ready()[sid])
    assert reply_queue.ready() == {}
    clock[0] += timedelta(minutes=31)
    assert not reply_queue.is_selected(row["url"], TEXT)


def test_queue_is_bounded_and_corruption_is_not_overwritten(clock):
    for i in range(reply_queue.MAX_PENDING):
        stage("builder", i)
    assert not reply_queue.reserve(pipeline.Candidate(fresh("ninth", n=99), PARENT, "TEST"))
    path = Path(reply_queue.QUEUE.path)
    path.write_text('{"123": {"status": []}}')
    with pytest.raises(StateUnreadable):
        reply_queue.reserve(pipeline.Candidate(fresh("new"), PARENT, "TEST"))
    assert path.read_text() == '{"123": {"status": []}}'


def test_dry_run_starts_no_preparation_review_or_publication(clock, monkeypatch):
    stage()
    before = Path(reply_queue.QUEUE.path).read_bytes()
    clock[0] += timedelta(seconds=61)
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(selection, "run_llm", lambda *a, **k: pytest.fail("dry run called model"))
    assert selection.run_selection_cycle() == 0
    assert Path(reply_queue.QUEUE.path).read_bytes() == before


def test_a_better_draft_prepared_during_cooldown_wins(clock, reviewer, publisher):
    assert reply_pacing.reserve(fresh("previous"))
    first = stage("early", 1)
    due = datetime.fromisoformat(reply_pacing.PACE.read()["next_at"])
    clock[0] = due - timedelta(seconds=80)
    assert selection.run_selection_cycle() == 0
    assert len(reviewer[0]) == 1 and not publisher
    better = stage("later", 2, "Batching trades latency for throughput.")
    reviewer[1][better] = review(5)
    clock[0] = due
    assert selection.run_selection_cycle() == 1
    assert x_urls.status_id(publisher[0][0]) == better
    assert first in reply_queue.ready() and len(reviewer[0]) == 2


def test_review_expiry_requires_a_fresh_comparison(clock, reviewer, publisher):
    sid = stage()
    row = reply_queue.ready()[sid]
    reply_queue.reviewed({sid: row}, {sid: {**review(5), "reviewed_at": clock[0].isoformat()}})
    clock[0] += timedelta(minutes=11)
    reviewer[1][sid] = {**review(5), "grounded": False}
    assert selection.run_selection_cycle() == 0
    assert len(reviewer[0]) == 1 and not publisher


def test_two_selectors_cannot_review_or_publish_concurrently(clock, reviewer, publisher, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    stage()
    clock[0] += timedelta(seconds=61)
    entered, release = threading.Event(), threading.Event()
    answer = selection.run_llm
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return answer(*args, **kwargs)
    monkeypatch.setattr(selection, "run_llm", delayed)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(selection.run_selection_cycle)
        try:
            assert entered.wait(5)
            assert selection.run_selection_cycle() == 0
        finally:
            release.set()
        assert pending.result(timeout=5) == 1
    assert len(reviewer[0]) == len(publisher) == 1


def test_selected_draft_reaches_real_write_guards_once(clock, reviewer, monkeypatch, memory_ledger):
    from src.x import safari
    sid = stage()
    other = stage("other", 2, "Batching trades latency for throughput.")
    reviewer[1][sid] = review(5)
    submitted, pasted = [], []
    for name in ("_activate_or_abort", "_open_or_abort"):
        monkeypatch.setattr(twitter_client, name, lambda *a, **k: True)
    monkeypatch.setattr(twitter_client, "_maybe_like_parent", lambda *a: None)
    monkeypatch.setattr(twitter_client, "_paste_or_abort", lambda text, *a: pasted.append(text) or True)
    monkeypatch.setattr(twitter_client, "_submit_or_abort", lambda *a, **k: submitted.append(k["target"]) or True)
    monkeypatch.setattr(twitter_client.time, "sleep", lambda *a: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    url = reply_queue.ready()[sid]["url"]
    monkeypatch.setattr(safari, "_run_js", lambda js, *a, **k: json.dumps(
        {"url": url, "text": PARENT, "clicked": "click = true" in js}))
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert pasted == [TEXT] and submitted == [url]
    assert url in replied_store.load_replied()
    assert action_guard.count_today(action_guard.REPLY) == 1
    assert reply_pacing.remaining() >= 300
    assert selection.run_selection_cycle() == 0 and other in reply_queue.ready()


def test_final_write_refuses_unselected_text_before_browser(clock, monkeypatch, memory_ledger):
    sid = stage()
    monkeypatch.setattr(twitter_client, "_activate_or_abort", lambda *a: pytest.fail("unreviewed browser write"))
    assert twitter_client.reply_to_tweet(reply_queue.ready()[sid]["url"], TEXT) is WriteOutcome.REFUSED
    assert memory_ledger.rows == [] and reply_pacing.PACE.read() == {}
