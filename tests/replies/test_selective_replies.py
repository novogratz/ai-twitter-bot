"""Ten selective Replies: priority from URLs, strict scores, and short drafts."""
from datetime import timedelta
from dataclasses import replace

import pytest

from src.core import account
from src.guards import active_hours
from src.replies import reply_generator, reply_pipeline as pipeline
from src.replies import reply_pool as pool, reply_selector as selector
from src.core.llm_client import Surface
from tests.helpers import fresh_local as fresh, clock


@pytest.fixture(autouse=True)
def priority_policy(monkeypatch):
    """Exercise generic priority behavior with an unprotected fictitious author."""
    current = account.current()
    policy = replace(current.replies, priority_handles=("priorityauthor",), min_score=92)
    monkeypatch.setattr(account, "current", lambda: replace(current, replies=policy))


def collect(monkeypatch, authors):
    urls = [fresh(author, n=i) for i, author in enumerate(authors)]
    pool.collect(pipeline.Job("scan", "SCAN", None),
                 [pipeline.Candidate(url, "Grok Imagine generated video", "FEED") for url in urls])
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=61))
    return urls


def reviews(batch, scores):
    return [dict(id=row["id"], on_topic=True, score=scores[row["url"]],
                 reason="Specific comic angle", angle="Tease the unnecessary production meeting") for row in batch]


@pytest.mark.parametrize("priority_score,other_score,expected", [
    (92, 100, 0), (91, 100, 1), (92, 96, 0), (91, 96, None),
])
def test_priority_and_exceptional_other_thresholds(monkeypatch, priority_score, other_score, expected):
    urls = collect(monkeypatch, ["PRIORITYAUTHOR", "anotherbuilder"])
    # Display names cannot gain or remove priority; only the URL names the author.
    records = pool.read()
    records[urls[0].rsplit("/", 1)[1]]["author"] = "ordinary display name"
    records[urls[1].rsplit("/", 1)[1]]["author"] = "priorityauthor"
    pool.POOL.write(records)
    scores = dict(zip(urls, (priority_score, other_score)))
    monkeypatch.setattr(selector, "_rank", lambda batch: reviews(batch, scores))
    sent = []
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, *a, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == (expected is not None)
    assert [candidate.url for candidate in sent] == ([] if expected is None else [urls[expected]])


def test_priority_posts_enter_the_comparison_before_a_full_backlog():
    rows = [dict(id=str(i), state="queued", text="SI research", url=f"https://x.com/builder/status/{i}")
            for i in range(30)]
    priority = dict(id="31", state="queued", text="Grok Imagine", url="https://x.com/PriorityAuthor/status/31")
    selected = selector.comparison_order(rows + [priority])[:pool.BATCH_SIZE]
    assert selected[0] == priority
    assert len(selected) == pool.BATCH_SIZE


def test_new_priority_post_is_reviewed_before_sending_a_cached_other(monkeypatch):
    other, = collect(monkeypatch, ["anotherbuilder"])
    pool.decide(pool.contenders(), reviews(pool.contenders(), {other: 100}))
    priority, = collect(monkeypatch, ["priorityauthor"])
    compared, sent = [], []
    monkeypatch.setattr(selector, "_rank", lambda batch: compared.extend(batch) or reviews(batch, {other: 100, priority: 92}))
    monkeypatch.setattr(pipeline, "dispatch", lambda job, candidates, *a, **k: sent.extend(candidates) or 1)
    assert selector.run_reply_selection_cycle() == 1
    assert compared[0]["url"] == priority
    assert [candidate.url for candidate in sent] == [priority]


def test_old_ready_scores_do_not_bypass_the_new_threshold(monkeypatch):
    url, = collect(monkeypatch, ["anotherbuilder"])
    pool.decide(pool.contenders(), reviews(pool.contenders(), {url: 100}))
    records = pool.read()
    records[url.rsplit("/", 1)[1]]["score"] = 96
    pool.POOL.write(records)
    assert pool.read(), "old ready state remains readable; never discard production state"
    monkeypatch.setattr(selector, "_rank", lambda batch: None)
    monkeypatch.setattr(pipeline, "dispatch", lambda *a, **k: pytest.fail("old weak approval shipped"))
    assert selector.run_reply_selection_cycle() == 0


@pytest.mark.parametrize("rewrites", [True, False])
def test_long_reply_gets_one_rewrite_even_without_a_selected_style(llm, rewrites):
    long = "One two three four five six seven eight nine ten eleven twelve thirteen."
    short = "Grok made the storyboard meeting redundant."
    answers = iter([long, short if rewrites else long])
    llm.default = lambda prompt: next(answers)
    call = reply_generator.ReplyCall("Parent: {tweet_text}", Surface.REPLY_ON_AI_CLI, "TEST", dossier=False)
    result = reply_generator.generate(call, author="someone", text="Grok Imagine generated video")
    assert result.outcome is (reply_generator.Outcome.WRITTEN if rewrites else reply_generator.Outcome.FAILED)
    assert result.text == (short if rewrites else "")
    assert len(llm.calls) == 2
