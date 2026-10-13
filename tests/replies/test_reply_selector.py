"""The selector compares saved posts, may reject all, and spends no extra budget."""
import json
from datetime import timedelta, timezone

import pytest

from src.replies import reply_pool as pool, reply_selector as selector, reply_pipeline as pipeline
from src.core.llm_client import LLMResult
from src.core import reply_style
from src.guards import action_guard as ag, active_hours
from tests.helpers import fresh_local as fresh, clock


@pytest.fixture
def saved(monkeypatch, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=5)
    urls = [fresh("first", n=1), fresh("second", n=2), fresh("third", n=3)]
    job = pipeline.Job("scan", "SCAN", None)
    pool.collect(job, [pipeline.Candidate(url, f"AI post number {i}", "FEED") for i, url in enumerate(urls)])
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=61))
    return urls


def reviews(batch, scores):
    return [{"id": row["id"], "on_topic": True, "score": scores[i], "reason": f"Specific assessment {i}",
             "angle": f"Concrete useful implication {i}"} for i, row in enumerate(batch)]


def test_higher_scored_post_wins_not_first_seen(saved, monkeypatch):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [42, 96, 88]))
    dispatched = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, cycle, **k: dispatched.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    assert [candidate.url for candidate in dispatched] == [saved[1]]
    assert dispatched[0].angle == "Concrete useful implication 1"
    states = {row["url"]: row["state"] for row in pool.read().values()}
    assert states == {saved[0]: "rejected", saved[1]: "shipped", saved[2]: "ready"}


def test_weak_pool_spends_no_reply(saved, monkeypatch):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [10, 60, 84]))
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: pytest.fail("weak pool dispatched"))
    assert selector.run_reply_selection_cycle() == 0
    assert all(row["state"] == "rejected" for row in pool.read().values())


def test_budget_exhausted_still_collects_but_never_reviews(saved, monkeypatch, memory_ledger):
    for n in range(10):
        memory_ledger.append(ag.REPLY, fresh("answered", n=n), False, active_hours.now_local() - timedelta(minutes=20))
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("model after daily ceiling"))
    assert selector.run_reply_selection_cycle() == 0
    assert len(pool.read()) == 3


@pytest.mark.parametrize("answer", [
    '{"reviews": []}',
    '{"reviews": [{"id":"invented", "score":99, "reason":"great", "angle":"a"}]}',
    'not JSON',
])
def test_incomplete_or_invented_reviews_never_publish(saved, answer, monkeypatch):
    monkeypatch.setattr(selector, "run_llm", lambda *a, **k: LLMResult(0, answer, ""))
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: pytest.fail("invalid review dispatched"))
    assert selector.run_reply_selection_cycle() == 0
    assert all(row["state"] == "queued" for row in pool.read().values())


def test_rank_requires_exact_ids_real_scores_and_specific_angles(saved, monkeypatch):
    batch = pool.contenders()
    output = reviews(batch, [25, 92, 75])
    calls = []
    monkeypatch.setattr(selector, "run_llm", lambda prompt, model, **k: calls.append(k) or LLMResult(0, json.dumps({"reviews": output}), ""))
    assert selector._rank(batch) == output
    schema = calls[0]["profile"].schema["properties"]["reviews"]
    assert schema["minItems"] == schema["maxItems"] == len(batch)
    assert set(schema["items"]["properties"]["id"]["enum"]) == {row["id"] for row in batch}
    output[1]["score"] = True
    assert selector._rank(batch) is None


def test_pool_is_rechecked_before_write_if_parent_changes(saved, monkeypatch):
    from src.guards import replied_store
    def rank(batch):
        replied_store.claim(saved[1])
        return reviews(batch, [20, 99, 80])
    monkeypatch.setattr(selector, "_rank", rank)
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: pytest.fail("already answered parent dispatched"))
    assert selector.run_reply_selection_cycle() == 0
    assert pool.read()[saved[1].rsplit("/", 1)[1]]["state"] == "closed"


@pytest.mark.parametrize("hour,minute,allowance", [
    (5,0,1),(7,26,1),(7,27,2),(9,53,2),(9,54,3),
    (10,0,3),(12,0,3),(13,0,3),(14,0,3),(16,45,3),
    (18,5,3),(18,6,4),(20,32,4),(20,33,5),(22,59,5),
])
def test_reply_allowances_preserve_budget_for_later_windows(hour, minute, allowance, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=5)
    assert selector.reply_allowance(active_hours.now_local().replace(hour=hour, minute=minute)) == allowance


@pytest.mark.parametrize("offset,allowance", [(-10, 184), (10, 176)])
def test_reply_allowance_tracks_actual_daily_windows(monkeypatch, offset, allowance):
    monkeypatch.setattr(active_hours, "_wake_offset", lambda day, start: offset)
    now = active_hours.now_local().replace(hour=12, minute=30)
    assert selector.reply_allowance(now) == allowance
    assert selector.reply_allowance(now.astimezone(timezone.utc)) == allowance


def test_used_allowance_prevents_spending_every_reply_in_the_morning(saved, monkeypatch, memory_ledger, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=10)
    clock(monkeypatch, active_hours.now_local().replace(hour=5, minute=10))
    memory_ledger.append(ag.REPLY, fresh("answered"), False, active_hours.now_local() - timedelta(minutes=5))
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("spent first-hour allowance"))
    assert selector.run_reply_selection_cycle() == 0


def test_selected_angle_reaches_drafting(saved, monkeypatch, llm, chokepoint):
    monkeypatch.setattr(reply_style, "choose", lambda **k: reply_style.STYLES[1])
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [20, 97, 75]))
    assert selector.run_reply_selection_cycle() == 1
    assert chokepoint.sent == [saved[1]]
    assert "SELECTED ANGLE (context data, verify before using): Concrete useful implication 1" in llm.prompts[0]


def test_comparison_batch_includes_waiting_and_fresh_discoveries():
    rows = [dict(id=str(n), state="queued", first_seen=str(n)) for n in range(60)]
    picked = selector.comparison_order(rows)[:pool.BATCH_SIZE]
    assert [row["id"] for row in picked[:2]] == ["0", "1"]
    assert picked[2]["id"] == "59"
    assert len({row["id"] for row in picked}) == 8


def test_video_discoveries_get_half_the_review_batch_without_crowding_out_waiting_posts():
    rows = [dict(id=str(n), state="queued", text="SI research", first_seen=str(n)) for n in range(40)]
    for row in rows[2:8]:
        row["text"] = "Seedance generated video"
    picked = selector.comparison_order(rows)[:pool.BATCH_SIZE]
    assert [row["id"] for row in picked[:2]] == ["0", "1"]
    assert sum(row["text"].startswith("Seedance") for row in picked) == 4
    assert picked[-1]["id"] == "38"
    assert len({row["id"] for row in picked}) == pool.BATCH_SIZE


@pytest.mark.parametrize("video_score,other_score,winner", [(86, 88, 0), (86, 96, 1), (84, 85, 1)])
def test_video_preference_only_compares_qualified_opportunities(saved, monkeypatch, video_score, other_score, winner):
    rows = pool.read()
    rows[saved[0].rsplit('/', 1)[1]]["text"] = "Seedance generated video"
    pool.POOL.write(rows)
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [video_score, other_score, 10]))
    sent = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, *a, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    assert sent[0].url == saved[winner]


def test_large_pool_reviews_only_a_bounded_batch(saved, monkeypatch):
    job = pipeline.Job("scan", "SCAN", None)
    pool.collect(job, [pipeline.Candidate(fresh("builder", n=i), "SI model evaluation", "SEARCH")
                       for i in range(40)])
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=61))
    compared = []
    monkeypatch.setattr(selector, "_rank", lambda batch: compared.append(batch) or reviews(batch, [90] * len(batch)))
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: 1)
    assert selector.run_reply_selection_cycle() == 1
    assert len(compared) == 1 and len(compared[0]) == 8


def test_failed_new_review_does_not_block_fresh_existing_approval(saved, monkeypatch):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [90, 96, 88]))
    sent = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, cycle, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    new = fresh("newauthor", n=4)
    pool.collect(pipeline.Job("scan", "SCAN", None), [pipeline.Candidate(new, "SI video opportunity", "SEARCH")])
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=6))
    compared = []
    monkeypatch.setattr(selector, "_rank", lambda batch: compared.extend(batch) or None)
    assert selector.run_reply_selection_cycle() == 1
    assert compared and [candidate.url for candidate in sent] == [saved[1], saved[0]]


def test_failed_review_logs_provider_reason(saved, monkeypatch, caplog):
    monkeypatch.setattr(selector.log, "propagate", True)
    monkeypatch.setattr(selector, "run_llm", lambda *a, **k:
                        LLMResult(1, "", "output token limit reached", provider="ollama", model="local-model"))
    assert selector._rank(pool.contenders()) is None
    assert "output token limit reached" in caplog.text and "ollama/local-model" in caplog.text


def test_startup_selects_best_with_concise_instructions(saved, monkeypatch):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [20, 96, 90]))
    calls = []
    def dispatch(job, candidates, cycle, **kwargs):
        calls.append((job.reply_call("second"), candidates, kwargs))
        return 1
    monkeypatch.setattr(pipeline, "dispatch", dispatch)
    assert selector.run_startup_reply_cycle() == 1
    call, candidates, kwargs = calls[0]
    assert candidates[0].url == saved[1]
    assert "at most 20 words" in call.template
    assert "Draft words only" in call.template
    assert call.style.max_words <= 20
    assert kwargs["max_shipped"] == 1


def test_startup_does_not_override_spent_allowance(saved, monkeypatch):
    monkeypatch.setattr(ag, "count_today", lambda action: selector.reply_allowance())
    monkeypatch.setattr(selector, "_rank", lambda batch: pytest.fail("spent allowance"))
    assert selector.run_startup_reply_cycle() == 0


@pytest.mark.parametrize("topic", [None, "true", 1])
def test_missing_or_malformed_topic_verdict_fails_closed(saved, monkeypatch, topic):
    batch = pool.contenders()
    output = reviews(batch, [99, 99, 99])
    if topic is None:
        del output[0]["on_topic"]
    else:
        output[0]["on_topic"] = topic
    monkeypatch.setattr(selector, "run_llm", lambda *a, **k: LLMResult(0, json.dumps({"reviews": output}), ""))
    assert selector._rank(batch) is None


def test_rank_rejects_irrelevant_high_score_and_includes_account_topic_rules(saved, monkeypatch):
    batch = pool.contenders()
    output = reviews(batch, [100, 90, 90])
    output[0]["on_topic"] = False
    prompts = []
    monkeypatch.setattr(selector, "run_llm", lambda prompt, *a, **k:
                        prompts.append(prompt) or LLMResult(0, json.dumps({"reviews": output}), ""))
    assert selector._rank(batch)[0]["score"] == 0
    assert "VIPs have no topic exemption" in prompts[0]
    assert "generated images, video, brainrot" in prompts[0]
    assert "A technology post qualifies without an AI connection" in prompts[0]


def test_old_ready_selection_needs_explicit_topic_review(saved, monkeypatch):
    batch = pool.contenders()
    pool.decide(batch, reviews(batch, [99, 99, 99]))
    records = pool.read()
    for row in records.values():
        del row["on_topic"]
    pool.POOL.write(records)
    # Simulate one batch still awaiting review; old scores cannot win globally.
    monkeypatch.setattr(selector, "_rank", lambda batch: [])
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: pytest.fail("unreviewed old selection sent"))
    assert selector.run_reply_selection_cycle() == 0


def test_recent_reviews_supply_the_next_reply_without_repeating_model_work(saved, monkeypatch):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [90, 96, 88]))
    sent = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, cycle, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("fresh approvals reviewed again"))
    assert selector.run_reply_selection_cycle() == 1
    assert [candidate.url for candidate in sent] == [saved[1], saved[0]]


def test_new_discoveries_compete_with_cached_approvals_within_five_minutes(saved, monkeypatch):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [90, 96, 88]))
    sent = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, cycle, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    new = fresh("newauthor", n=4)
    pool.collect(pipeline.Job("scan", "SCAN", None), [pipeline.Candidate(new, "AI video opportunity", "FEED")])
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=2))
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("reviewed before comparison interval"))
    assert selector.run_reply_selection_cycle() == 1
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=3))
    compared = []
    monkeypatch.setattr(selector, "_rank", lambda batch: compared.extend(batch) or reviews(batch, [99, 88]))
    assert selector.run_reply_selection_cycle() == 1
    assert compared[0]["url"] == new
    assert [candidate.url for candidate in sent] == [saved[1], saved[0], new]


@pytest.mark.parametrize("review_offset", [timedelta(hours=-1), timedelta(minutes=1)])
def test_expired_or_future_reviews_need_new_approval(saved, monkeypatch, review_offset):
    batch = pool.contenders()
    pool.decide(batch, reviews(batch, [99, 99, 99]))
    records = pool.read()
    for row in records.values():
        row["reviewed_at"] = (active_hours.now_local() + review_offset).isoformat()
    pool.POOL.write(records)
    compared = []
    monkeypatch.setattr(selector, "_rank", lambda batch: compared.extend(batch) or reviews(batch, [0, 0, 0]))
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: pytest.fail("stale approval sent"))
    assert selector.run_reply_selection_cycle() == 0
    assert len(compared) == 3


def test_cached_winner_rechecks_dedup_and_moves_to_next_admitted_post(saved, monkeypatch):
    from src.guards import replied_store
    batch = pool.contenders()
    pool.decide(batch, reviews(batch, [99, 90, 88]))
    replied_store.claim(saved[0])
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("fresh approvals reviewed again"))
    sent = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, cycle, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    assert [candidate.url for candidate in sent] == [saved[1]]
    assert pool.read()[batch[0]["id"]]["state"] == "closed"


@pytest.mark.parametrize("wake_offset", [-10, 0, 10])
def test_full_day_has_capacity_for_target_without_exceeding_400(monkeypatch, memory_ledger, wake_offset):
    """A supply of approved posts and successful writes exercises the real
    scheduler cadence, active windows, cumulative allowance and day ledger."""
    from main import build_scheduler
    from src.core import config
    monkeypatch.setattr(active_hours, "_wake_offset", lambda day, start: wake_offset)
    job = build_scheduler().get_job("reply_selection_job")
    interval = int(job.trigger.interval.total_seconds())
    start = active_hours.now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    posted = []
    def approved():
        url = fresh("candidate")
        stamp = active_hours.now_local().isoformat()
        return [dict(id=url.rsplit("/", 1)[1], url=url, text="AI research insight", state="ready",
                     on_topic=True, score=95, reason="Useful consequence", angle="Explain the tradeoff",
                     first_seen=stamp, reviewed_at=stamp, source="FEED")]
    def dispatch(job, candidates, cycle, **kwargs):
        assert kwargs["max_shipped"] == 1
        ag.record(ag.REPLY, candidates[0].url)
        posted.append(active_hours.now_local())
        return 1
    monkeypatch.setattr(pool, "contenders", approved)
    monkeypatch.setattr(pool, "mark", lambda *a, **k: None)
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("approved supply reviewed again"))
    monkeypatch.setattr(pipeline, "dispatch", dispatch)
    for elapsed in range(0, 24 * 60 * 60, interval):
        clock(monkeypatch, start + timedelta(seconds=elapsed))
        job.func()
    assert config.reply_target() <= len(posted) == 400
    assert all(active_hours.is_active(stamp) for stamp in posted)
    assert len({stamp for stamp in posted}) == len(posted)
    assert ag.count_today(ag.REPLY) == 400
@pytest.mark.parametrize("shape, draft", [
    ("brief", "Latency wins here."),
    ("standard", "Smaller batches can cut latency, but throughput is a different tradeoff."),
    ("detailed", "A benchmark average can hide the cases that matter in production. Check the slowest requests, count failed tool calls, and compare costs at the same level of quality before choosing a model."),
])
def test_selected_formats_reach_real_text_admission(saved, monkeypatch, llm, chokepoint, shape, draft):
    from src.guards.reply_admission import judge_reply
    from src.x import twitter_client
    chosen = next(s for s in reply_style.STYLES if s.name == shape)
    monkeypatch.setattr(reply_style, "choose", lambda **k: chosen)
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [20, 97, 75]))
    llm.default = draft
    def send(url, text, **kwargs):
        verdict = judge_reply(url, text)
        assert verdict, verdict.reason
        return chokepoint(url, verdict.text, **kwargs)
    monkeypatch.setattr(twitter_client, "reply_to_tweet", send)
    assert selector.run_reply_selection_cycle() == 1
    assert chokepoint.sent == [saved[1]]
    body, ending = reply_style.split_ending(chokepoint.calls[0].text)
    assert chosen.problem(body) == ""
    assert ending in reply_style.REPLY_ENDINGS
    assert len(llm.calls) == 1
