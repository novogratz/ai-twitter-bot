import pytest

from src.guards import quote_store
from src.replies import priority_quotes as job, reply_pipeline
from src.x import twitter_client as tc, x_urls
from tests.helpers import fresh

pytestmark = pytest.mark.usefixtures("promotion_account")


@pytest.mark.parametrize("score,approved,writes", [(7, True, 0), (9, False, 0), (9, True, 1)])
def test_popularity_never_replaces_impact_and_independent_review(monkeypatch, memory_ledger, score, approved, writes):
    monkeypatch.setenv("DRY_RUN", "0")
    url = fresh("elonmusk")
    candidate = reply_pipeline.Candidate(url, "The new SI video model is available today.", "WATCH", likes=100000, views=5000000)
    monkeypatch.setattr(job.priority_watch, "discovered", lambda: [candidate])
    monkeypatch.setattr(tc, "read_priority_post", lambda *_: dict(url=url, text=candidate.text))
    calls, sent = [], []
    def model(prompt, label):
        calls.append(label)
        if label.endswith("SELECT"):
            return dict(url=url, text="That is a useful new tool for independent artists.", impact=score, reason="new capability")
        return dict(approved=approved, grounded=True, adds_value=True, natural_voice=True, impact=9)
    monkeypatch.setattr(job, "_call", model)
    monkeypatch.setattr(tc, "quote_priority_post", lambda url: sent.append(url))
    job.run_priority_quote_cycle()
    assert len(sent) == writes
    assert calls == (["PRIORITY_QUOTE_SELECT"] if score < 8 else ["PRIORITY_QUOTE_SELECT", "PRIORITY_QUOTE_REVIEW"])
    assert quote_store.entries()[x_urls.status_id(url)]["state"] == ("approved" if writes else "rejected")
