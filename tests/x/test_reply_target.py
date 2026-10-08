"""Every reply caller inherits the standalone-page check and daily ceiling."""
import pytest

from src.x import safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome
from src.guards import action_guard as ag, replied_store
from tests.helpers import numbered_url


@pytest.mark.parametrize("answer", ["refused", "", None, "unknown"])
def test_unverified_target_never_passes(answer, monkeypatch):
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: answer)
    assert not tc._standalone_reply_target(numbered_url(1))


def test_target_reader_errors_fail_closed(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("page unreadable")
    monkeypatch.setattr(safari, "_run_js", broken)
    assert not tc._standalone_reply_target(numbered_url(1))


def test_daily_reply_ceiling_is_checked_at_write(monkeypatch, memory_ledger, settings_override):
    from tests.x.test_write_path import _fake_safari
    from src.guards.active_hours import now_local
    from datetime import timedelta
    settings_override(MAX_REPLIES_PER_DAY=10)
    _fake_safari(monkeypatch)
    monkeypatch.setattr(ag, "too_soon", lambda action: "")
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: True)
    for n in range(9):
        memory_ledger.append(ag.REPLY, numbered_url(n), False, now_local() - timedelta(hours=2))
    tenth, eleventh = numbered_url(20), numbered_url(21)
    text = "Batching improves throughput; latency still depends on the queue."
    assert tc.reply_to_tweet(tenth, text) is WriteOutcome.SHIPPED
    assert tc.reply_to_tweet(eleventh, text) is WriteOutcome.REFUSED
    assert ag.count_today(ag.REPLY) == 10
    assert eleventh not in replied_store.load_replied()


def test_refused_page_releases_claim_and_never_submits(monkeypatch, memory_ledger):
    from tests.x.test_write_path import _fake_safari
    _fake_safari(monkeypatch)
    monkeypatch.setattr(tc, "_standalone_reply_target", lambda url: False)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("submitted to a conversation"))
    url = numbered_url(50)
    assert tc.reply_to_tweet(url, "Inference throughput depends on batch size and queueing.") is WriteOutcome.REFUSED
    assert url not in replied_store.load_replied()
    assert ag.count_today(ag.REPLY) == 0


def test_ambiguous_tenth_reply_consumes_budget_across_restart(monkeypatch, memory_ledger, settings_override):
    from tests.x.test_write_path import _fake_safari
    from src.guards.active_hours import now_local
    from datetime import timedelta
    settings_override(MAX_REPLIES_PER_DAY=10)
    _fake_safari(monkeypatch)
    monkeypatch.setattr(ag, "too_soon", lambda action: "")
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: False)
    for n in range(9):
        memory_ledger.append(ag.REPLY, numbered_url(n), False, now_local() - timedelta(hours=2))
    assert tc.reply_to_tweet(numbered_url(30), "Batching improves throughput; latency depends on queueing.") is WriteOutcome.UNCONFIRMED
    assert ag.count_today(ag.REPLY) == 9
    assert ag.pending_reply_count() == 1
    # A new StateFile adapter sees the persisted reservation after a restart.
    from src.core.state_store import StateFile, GUARDED
    monkeypatch.setattr(ag, "REPLY_SUBMISSIONS", StateFile("reply_submissions.json", {}, GUARDED))
    assert tc.reply_to_tweet(numbered_url(31), "Another insight about inference batching and latency.") is WriteOutcome.REFUSED


def test_corrupt_reply_reservation_stops_writes_without_overwriting(monkeypatch):
    from src.core.state_errors import StateUnreadable
    ag.REPLY_SUBMISSIONS.write({"123": "not a date"})
    with pytest.raises(StateUnreadable):
        tc.reply_to_tweet(numbered_url(40), "A precise observation about inference cost and latency.")
    assert ag.REPLY_SUBMISSIONS.read() == {"123": "not a date"}


@pytest.mark.parametrize("articles,expected", [
    ([{"id": "50", "text": "An independent AI post"}], True),
    ([{"id": "49", "text": "Our own post"}, {"id": "50", "text": "A comment"}], False),
    ([{"id": "50", "text": "Replying to @ouraccount"}], False),
    ([{"id": "50", "text": "En réponse à @ouraccount"}], False),
    ([{"id": "50", "text": "Loading", "has_text": False}], False),
    ([{"id": "99", "text": "A different post"}], False),
])
def test_opened_page_classification(articles, expected, monkeypatch):
    """Execute the real guard JS against standalone, conversation and blank DOMs."""
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required to execute page JavaScript fixtures")
    def page(js, *a, **k):
        fixture = """
        const fixtures = JSON.parse(process.argv[1]);
        global.document = {querySelectorAll: () => fixtures.map(f => ({
          innerText: f.text,
          querySelectorAll: () => [{pathname: '/author/status/' + f.id,
                                    querySelector: () => ({})}],
          querySelector: () => f.has_text === false ? null : ({})
        }))};
        process.stdout.write(String(eval(process.argv[2])));
        """
        return subprocess.run([node, "-e", fixture, json.dumps(articles), js],
                              check=True, capture_output=True, text=True).stdout
    monkeypatch.setattr(safari, "_run_js", page)
    assert tc._standalone_reply_target("https://x.com/author/status/50") is expected
