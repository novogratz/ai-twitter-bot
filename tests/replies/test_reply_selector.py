"""The selector compares saved posts, may reject all, and spends no extra budget."""
import json
from datetime import timedelta

import pytest

from src.replies import reply_pool as pool, reply_selector as selector, reply_pipeline as pipeline
from src.core.llm_client import LLMResult
from src.guards import action_guard as ag, active_hours
from tests.helpers import fresh, clock


@pytest.fixture
def saved(monkeypatch):
    urls = [fresh("first", n=1), fresh("second", n=2), fresh("third", n=3)]
    job = pipeline.Job("scan", "SCAN", None)
    pool.collect(job, [pipeline.Candidate(url, f"AI post number {i}", "FEED") for i, url in enumerate(urls)])
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=61))
    return urls


def reviews(batch, scores):
    return [{"id": row["id"], "score": scores[i], "reason": f"Specific assessment {i}",
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
    assert calls[0]["profile"].schema is not None
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


@pytest.mark.parametrize("hour,allowance", [(5,1),(6,2),(9,5),(14,6),(17,7),(18,8),(22,9),(23,10)])
def test_reply_allowances_preserve_budget_for_later_windows(hour, allowance, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=10)
    assert selector.reply_allowance(active_hours.now_local().replace(hour=hour, minute=0)) == allowance


def test_used_allowance_prevents_spending_every_reply_in_the_morning(saved, monkeypatch, memory_ledger, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=10)
    clock(monkeypatch, active_hours.now_local().replace(hour=5, minute=10))
    memory_ledger.append(ag.REPLY, fresh("answered"), False, active_hours.now_local() - timedelta(minutes=5))
    monkeypatch.setattr(selector, "_rank", lambda *a: pytest.fail("spent first-hour allowance"))
    assert selector.run_reply_selection_cycle() == 0


def test_selected_angle_reaches_drafting(saved, monkeypatch, llm, chokepoint):
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, [20, 97, 75]))
    assert selector.run_reply_selection_cycle() == 1
    assert chokepoint.sent == [saved[1]]
    assert "SELECTED ANGLE (context data, verify before using): Concrete useful implication 1" in llm.prompts[0]


def test_comparison_batch_includes_waiting_and_fresh_discoveries():
    rows = [dict(id=str(n), state="queued", first_seen=str(n)) for n in range(60)]
    picked = selector.comparison_order(rows)[:pool.BATCH_SIZE]
    assert [row["id"] for row in picked[:10]] == [str(n) for n in range(10)]
    assert picked[10]["id"] == "59"
    assert len({row["id"] for row in picked}) == 30
