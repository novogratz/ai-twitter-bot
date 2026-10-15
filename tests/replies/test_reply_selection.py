import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core import account, reply_queue, reply_style
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
    return dict(impact=score, sharpness=score, interest=score, grounded=True, on_topic=True, positive=True,
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
    monkeypatch.setattr(reply_style, "choose_length", lambda: reply_style.Length.FULL)
    monkeypatch.setattr(reply_style, "choose_smiley", lambda: False)
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
    assert 30 <= wait <= 45
    clock[0] += timedelta(seconds=wait + 0.001)
    assert selection.run_selection_cycle() == 1 and len(publisher) == 2


def test_new_pool_gets_fifteen_seconds_then_best_reviewed_draft_can_ship(clock, reviewer, publisher):
    first = stage("one", 1)
    clock[0] += timedelta(seconds=10)
    best = stage("two", 2, "Batching trades latency for throughput.")
    reviewer[1][best] = review(5)
    clock[0] += timedelta(seconds=4)
    assert selection.run_selection_cycle() == 0 and not reviewer[0]
    clock[0] += timedelta(seconds=1)
    assert selection.run_selection_cycle() == 1
    assert x_urls.status_id(publisher[0][0]) == best
    assert first in reply_queue.ready()
    assert set(reviewer[0][0][1]["profile"].schema["required"]) == {first, best}
    assert selection.run_selection_cycle() == 0 and len(publisher) == 1


@pytest.mark.parametrize("bad", [
    {"impact": 3}, {"sharpness": 3}, {"interest": 3}, {"grounded": False}, {"on_topic": False},
    {"positive": False},
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
    json.dumps({"123": {**review(), "positive": "true"}}),
    json.dumps({"123": {**review(), "positive": None}}),
    json.dumps({"123": {k: v for k, v in review().items() if k != "positive"}}),
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


def test_a_better_draft_prepared_during_cooldown_wins(clock, reviewer, publisher, settings_override):
    settings_override(MIN_SECONDS_BETWEEN_REPLIES=300, REPLY_JITTER_SECONDS=180)
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
    assert reply_pacing.remaining() >= 30
    assert selection.run_selection_cycle() == 0 and other in reply_queue.ready()


def test_final_write_refuses_unselected_text_before_browser(clock, monkeypatch, memory_ledger):
    sid = stage()
    monkeypatch.setattr(twitter_client, "_activate_or_abort", lambda *a: pytest.fail("unreviewed browser write"))
    assert twitter_client.reply_to_tweet(reply_queue.ready()[sid]["url"], TEXT) is WriteOutcome.REFUSED
    assert memory_ledger.rows == [] and reply_pacing.PACE.read() == {}


@pytest.mark.parametrize("unkind", [
    "Great, another useless model.",
    "Not bad for someone who barely understands batching.",
])
def test_an_unkind_high_score_cannot_beat_a_kind_draft(clock, reviewer, publisher, unkind):
    rejected = stage("one", 1, unkind)
    accepted = stage("two", 2, "Batching makes better use of that memory bandwidth.")
    reviewer[1][rejected] = {**review(5), "positive": False, "reason": "A put-down instead of encouragement."}
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert x_urls.status_id(publisher[0][0]) == accepted
    assert reply_queue.QUEUE.read()[rejected]["status"] == "rejected"
    prompt, options = reviewer[0][0]
    assert "backhanded" in prompt and "positive=true ONLY" in prompt
    assert "Positive tone never excuses an unsupported claim" in prompt
    assert "positive" in options["profile"].schema["properties"][rejected]["required"]


def test_legacy_review_requires_positive_reapproval(clock, reviewer, publisher):
    sid = stage()
    data = reply_queue.QUEUE.read()
    legacy = {k: v for k, v in review(5).items() if k != "positive"}
    data[sid].update(status="reviewed", review={**legacy, "reviewed_at": clock[0].isoformat()})
    reply_queue.QUEUE.write(data)
    assert not reply_queue.approved(reply_queue.ready()[sid])
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert len(reviewer[0]) == len(publisher) == 1
    assert reply_queue.QUEUE.read()[sid]["review"]["positive"] is True


@pytest.mark.parametrize("positive", [False, None])
def test_saved_selected_draft_cannot_bypass_positive_gate(clock, monkeypatch, memory_ledger, positive):
    sid = stage()
    data = reply_queue.QUEUE.read()
    verdict = {**review(5), "positive": positive, "reviewed_at": clock[0].isoformat()}
    if positive is None:
        del verdict["positive"]  # A selection saved by the previous release.
    data[sid].update(status="selected", review=verdict, selected_at=clock[0].isoformat())
    reply_queue.QUEUE.write(data)
    before = Path(reply_queue.QUEUE.path).read_bytes()
    monkeypatch.setattr(twitter_client, "_activate_or_abort", lambda *a: pytest.fail("unapproved browser write"))
    assert twitter_client.reply_to_tweet(data[sid]["url"], TEXT) is WriteOutcome.REFUSED
    assert reply_queue.ready() == {}  # No automatic retry of a saved selection.
    assert Path(reply_queue.QUEUE.path).read_bytes() == before
    assert memory_ledger.rows == [] and reply_pacing.PACE.read() == {}


def test_few_word_reply_reaches_independent_review_and_publication(clock, monkeypatch, llm, reviewer, publisher):
    monkeypatch.setattr(reply_style, "choose_length", lambda: reply_style.Length.FEW_WORDS)
    monkeypatch.setattr(reply_style, "choose_smiley", lambda: False)
    llm.default = "Bandwidth matters."
    candidate = pipeline.Candidate(fresh("builder"), PARENT, "TEST")
    job = pipeline.Job("brief", "BRIEF", lambda _: ReplyCall("{tweet_text}", Surface.REPLY, "BRIEF"))
    assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    sid, row = next(iter(reply_queue.ready().items()))
    assert row["text"] == llm.default and row["length"] == "FEW_WORDS"
    assert "at most 60 characters and at most 5 words" in llm.calls[0].prompt
    # The same parent cannot redraw its limit or regenerate before selection.
    monkeypatch.setattr(reply_style, "choose_length", lambda: reply_style.Length.FULL)
    assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    assert reply_queue.ready()[sid]["length"] == "FEW_WORDS" and len(llm.calls) == 1
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert publisher == [(candidate.url, "Bandwidth matters.")]
    assert "two-to-five-word answer can earn full marks" in reviewer[0][0][0]


@pytest.mark.parametrize("text", [
    "More memory bandwidth helps those GPUs.",  # Six words, below 60 characters.
    "Bandwidth " + "a" * 55 + ".",  # Two words, above 60 characters.
    "Great post",  # Brief still has to be useful.
])
def test_prepared_search_drafts_cannot_bypass_assigned_limit_or_quality(clock, monkeypatch, text):
    monkeypatch.setattr(reply_style, "choose_length", lambda: reply_style.Length.FEW_WORDS)
    monkeypatch.setattr(reply_style, "choose_smiley", lambda: False)
    candidate = pipeline.Candidate(fresh("builder"), PARENT, "TEST", reply=text)
    assert pipeline.run(pipeline.Job("search", "SEARCH", None), [candidate], pipeline.Cycle()) == 0
    assert reply_queue.ready() == {}
    row = next(iter(reply_queue.QUEUE.read().values()))
    assert row["length"] == "FEW_WORDS" and row["status"] == "rejected"


def test_queue_refuses_a_draft_longer_than_its_saved_limit(clock):
    candidate = pipeline.Candidate(fresh("builder"), PARENT, "TEST")
    sid = reply_queue.reserve(candidate, length=reply_style.Length.FEW_WORDS)
    assert not reply_queue.prepared(sid, TEXT, Generation(Outcome.WRITTEN, "en", TEXT), "OTHER")
    assert reply_queue.ready() == {}
    assert reply_queue.QUEUE.read()[sid]["status"] == "rejected"


def test_old_queue_records_keep_the_previous_ceiling(clock, reviewer, publisher):
    sid = stage()
    data = reply_queue.QUEUE.read()
    del data[sid]["length"]
    reply_queue.QUEUE.write(data)
    assert reply_queue.length_for(reply_queue.ready()[sid]) is reply_style.Length.FULL
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert publisher[0][1] == TEXT


@pytest.mark.parametrize("length", [None, 500, [], "invented"])
def test_corrupt_length_metadata_stops_queue_without_overwriting(clock, length):
    sid = stage()
    data = reply_queue.QUEUE.read()
    data[sid]["length"] = length
    reply_queue.QUEUE.write(data)
    before = Path(reply_queue.QUEUE.path).read_bytes()
    with pytest.raises(StateUnreadable):
        selection.run_selection_cycle()
    assert Path(reply_queue.QUEUE.path).read_bytes() == before


@pytest.mark.parametrize("status", ["ready", "selected"])
def test_saved_overlength_draft_cannot_reach_review_or_browser(clock, monkeypatch, memory_ledger, status):
    sid = stage()
    data = reply_queue.QUEUE.read()
    data[sid].update(length="FEW_WORDS", status=status,
                     review={**review(5), "reviewed_at": clock[0].isoformat()},
                     selected_at=clock[0].isoformat())
    reply_queue.QUEUE.write(data)
    monkeypatch.setattr(selection, "run_llm", lambda *a, **k: pytest.fail("overlong draft reviewed"))
    monkeypatch.setattr(twitter_client, "_activate_or_abort", lambda *a: pytest.fail("overlong browser write"))
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 0
    assert twitter_client.reply_to_tweet(data[sid]["url"], TEXT) is WriteOutcome.REFUSED
    assert memory_ledger.rows == [] and reply_pacing.PACE.read() == {}


@pytest.mark.parametrize("smiley,text", [(False, "Bandwidth matters."), (True, "🙂 Bandwidth matters.")])
def test_smiley_choice_survives_preparation_review_and_publication(
        clock, monkeypatch, llm, reviewer, publisher, smiley, text):
    monkeypatch.setattr(reply_style, "choose_length", lambda: reply_style.Length.FEW_WORDS)
    monkeypatch.setattr(reply_style, "choose_smiley", lambda: smiley)
    llm.default = text
    candidate = pipeline.Candidate(fresh("builder"), PARENT, "TEST")
    job = pipeline.Job("smiley", "SMILEY", lambda _: ReplyCall("{tweet_text}", Surface.REPLY, "SMILEY"))
    assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    sid, row = next(iter(reply_queue.ready().items()))
    assert row["smiley"] is smiley and row["text"] == text
    instruction = "include exactly one friendly smiley" if smiley else "no emoji or text smileys"
    assert instruction in llm.calls[0].prompt
    monkeypatch.setattr(reply_style, "choose_smiley", lambda: not smiley)
    assert pipeline.run(job, [candidate], pipeline.Cycle()) == 0
    assert reply_queue.ready()[sid]["smiley"] is smiley and len(llm.calls) == 1
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 1
    assert publisher == [(candidate.url, text)]  # Nothing added or removed after review.
    assert text in reviewer[0][0][0]
    assert '"smiley": ' + str(smiley).lower() in reviewer[0][0][0]
    assert "Do not reward or penalize smiley presence" in reviewer[0][0][0]


@pytest.mark.parametrize("smiley,text", [(True, TEXT), (False, TEXT + " 🙂"), (True, TEXT + " 🚀")])
def test_queue_refuses_a_draft_that_ignores_its_smiley_choice(clock, smiley, text):
    candidate = pipeline.Candidate(fresh("builder"), PARENT, "TEST")
    sid = reply_queue.reserve(candidate, smiley=smiley)
    assert not reply_queue.prepared(sid, text, Generation(Outcome.WRITTEN, "en", text), "OTHER")
    assert reply_queue.ready() == {}


@pytest.mark.parametrize("status", ["ready", "selected"])
@pytest.mark.parametrize("smiley,text", [(True, TEXT), (False, TEXT + " 🙂")])
def test_saved_wrong_smiley_cannot_reach_review_or_browser(
        clock, monkeypatch, memory_ledger, status, smiley, text):
    sid = stage(text=text)
    data = reply_queue.QUEUE.read()
    data[sid].update(smiley=smiley, status=status,
                     review={**review(5), "reviewed_at": clock[0].isoformat()},
                     selected_at=clock[0].isoformat())
    reply_queue.QUEUE.write(data)
    monkeypatch.setattr(selection, "run_llm", lambda *a, **k: pytest.fail("wrong smiley reviewed"))
    monkeypatch.setattr(twitter_client, "_activate_or_abort", lambda *a: pytest.fail("wrong smiley published"))
    clock[0] += timedelta(seconds=61)
    assert selection.run_selection_cycle() == 0
    assert twitter_client.reply_to_tweet(data[sid]["url"], text) is WriteOutcome.REFUSED
    assert memory_ledger.rows == [] and reply_pacing.PACE.read() == {}


@pytest.mark.parametrize("smiley", [None, "true", 1, []])
def test_corrupt_smiley_choice_stops_queue_without_overwriting(clock, smiley):
    sid = stage()
    data = reply_queue.QUEUE.read()
    data[sid]["smiley"] = smiley
    reply_queue.QUEUE.write(data)
    before = Path(reply_queue.QUEUE.path).read_bytes()
    with pytest.raises(StateUnreadable):
        selection.run_selection_cycle()
    assert Path(reply_queue.QUEUE.path).read_bytes() == before
