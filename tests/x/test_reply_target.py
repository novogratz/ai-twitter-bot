"""Every reply caller inherits the standalone-page check and daily ceiling."""
import pytest

from src.x import safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome
from src.guards import action_guard as ag, replied_store
from tests.helpers import numbered_url


@pytest.mark.parametrize("dry", [False, True])
@pytest.mark.parametrize("debate_turn", [False, True])
def test_protected_author_never_reaches_browser_or_claim(monkeypatch, memory_ledger, dry, debate_turn):
    from src.guards.reply_admission import Refusal
    monkeypatch.setenv("DRY_RUN", "1" if dry else "0")
    # The test suite's Safari wall catches even a browser read on this path.
    parent = numbered_url(52, "ELONMUSK")
    refused = []
    assert tc.reply_to_tweet(parent, "Grok made the storyboard meeting redundant.",
                             debate_turn=debate_turn, on_refused=refused.append) is WriteOutcome.REFUSED
    assert refused == [Refusal.PROTECTED_ACCOUNT]
    assert parent not in replied_store.load_replied()
    assert memory_ledger.rows == []
    assert ag.pending_reply_count() == 0


@pytest.mark.parametrize("answer", ["refused", "", None, "unknown"])
def test_unverified_target_never_passes(answer, monkeypatch):
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: answer)
    assert not tc._standalone_reply_target(numbered_url(1))


def test_target_reader_errors_fail_closed(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("page unreadable")
    monkeypatch.setattr(safari, "_run_js", broken)
    assert not tc._standalone_reply_target(numbered_url(1))


@pytest.mark.parametrize("configured_cap,cap", [(400, 10), (999, 10), (10, 10), (2, 2)])
def test_daily_reply_ceiling_is_checked_at_write(monkeypatch, memory_ledger, settings_override, configured_cap, cap):
    from tests.x.test_write_path import _fake_safari
    from src.guards.active_hours import now_local
    from datetime import timedelta
    settings_override(MAX_REPLIES_PER_DAY=configured_cap)
    _fake_safari(monkeypatch)
    monkeypatch.setattr(ag, "too_soon", lambda action: "")
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: True)
    for n in range(cap - 1):
        memory_ledger.append(ag.REPLY, numbered_url(n), False, now_local() - timedelta(hours=2))
    last, extra = numbered_url(500), numbered_url(501)
    text = "Batching improves throughput; latency still depends on the queue."
    assert tc.reply_to_tweet(last, text) is WriteOutcome.SHIPPED
    assert tc.reply_to_tweet(extra, text) is WriteOutcome.REFUSED
    assert ag.count_today(ag.REPLY) == cap
    assert extra not in replied_store.load_replied()


def test_refused_page_releases_claim_and_never_submits(monkeypatch, memory_ledger):
    from tests.x.test_write_path import _fake_safari
    _fake_safari(monkeypatch)
    monkeypatch.setattr(tc, "_standalone_reply_target", lambda url: False)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("submitted to a conversation"))
    url = numbered_url(50)
    assert tc.reply_to_tweet(url, "Inference throughput depends on batch size and queueing.") is WriteOutcome.REFUSED
    assert url not in replied_store.load_replied()
    assert ag.count_today(ag.REPLY) == 0


@pytest.mark.parametrize("author", ["someone", "elonmusk", "xai"])
@pytest.mark.parametrize("text", ["My lunch today", "AI predicts Bitcoin prices", "Grok DOGE fan"] )
def test_opened_off_topic_post_never_gets_a_reply_or_parent_like(monkeypatch, memory_ledger, author, text):
    import json
    from tests.x.test_write_path import _fake_safari
    real_target_guard = tc._standalone_reply_target
    _fake_safari(monkeypatch)
    monkeypatch.setattr(tc, "_standalone_reply_target", real_target_guard)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps({"text": text, "url": url}))
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: pytest.fail("liked an unrelated parent"))
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("replied to an unrelated parent"))
    url = numbered_url(51, author)
    assert tc.reply_to_tweet(url, "La taille du lot change le débit du modèle, pas sa précision.") is WriteOutcome.REFUSED
    assert url not in replied_store.load_replied()
    assert ag.count_today(ag.REPLY) == ag.pending_reply_count() == 0


@pytest.mark.parametrize("opened_author", ["ELONMUSK", "otherauthor", ""])
def test_misattributed_opened_post_is_refused_before_like_or_submit(monkeypatch, memory_ledger, opened_author):
    import json
    from tests.x.test_write_path import _fake_safari
    real_guard = tc._standalone_reply_target
    _fake_safari(monkeypatch)
    monkeypatch.setattr(tc, "_standalone_reply_target", real_guard)
    parent = numbered_url(53, "someone")
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps({
        "url": numbered_url(53, opened_author), "text": "Grok Imagine generated video"}))
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: pytest.fail("liked misattributed post"))
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: pytest.fail("replied to misattributed post"))
    assert tc.reply_to_tweet(parent, "Grok made the storyboard meeting redundant.") is WriteOutcome.REFUSED
    assert parent not in replied_store.load_replied()
    assert memory_ledger.rows == []
    assert ag.pending_reply_count() == 0


@pytest.mark.parametrize("cap", [5, 10])
def test_ambiguous_last_reply_consumes_budget_across_restart(monkeypatch, memory_ledger, settings_override, cap):
    from tests.x.test_write_path import _fake_safari
    from src.guards.active_hours import now_local
    from datetime import timedelta
    settings_override(MAX_REPLIES_PER_DAY=cap)
    _fake_safari(monkeypatch)
    monkeypatch.setattr(ag, "too_soon", lambda action: "")
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: False)
    for n in range(cap - 1):
        memory_ledger.append(ag.REPLY, numbered_url(n), False, now_local() - timedelta(hours=2))
    assert tc.reply_to_tweet(numbered_url(500), "Batching improves throughput; latency depends on queueing.") is WriteOutcome.UNCONFIRMED
    assert ag.count_today(ag.REPLY) == cap - 1
    assert ag.pending_reply_count() == 1
    # A new StateFile adapter sees the persisted reservation after a restart.
    from src.core.state_store import StateFile, GUARDED
    monkeypatch.setattr(ag, "REPLY_SUBMISSIONS", StateFile("reply_submissions.json", {}, GUARDED))
    assert tc.reply_to_tweet(numbered_url(501), "Another insight about inference batching and latency.") is WriteOutcome.REFUSED


def test_corrupt_reply_reservation_stops_writes_without_overwriting(monkeypatch):
    from src.core.state_errors import StateUnreadable
    ag.REPLY_SUBMISSIONS.write({"123": "not a date"})
    with pytest.raises(StateUnreadable):
        tc.reply_to_tweet(numbered_url(40), "A precise observation about inference cost and latency.")
    assert ag.REPLY_SUBMISSIONS.read() == {"123": "not a date"}


@pytest.mark.parametrize("articles,expected", [
    ([{"id": "50", "text": "An independent AI post"}], True),
    ([{"id": "50", "text": "SI model alignment research"}], True),
    ([{"id": "50", "text": "AI-generated brainrot video made with Grok"}], True),
    ([{"id": "50", "text": "My lunch today"}], False),
    ([{"id": "50", "text": "My lunch today @OpenAI https://ai.example.org/menu"}], False),
    ([{"id": "50", "text": "@someone AI models", "has_text": True}], False),
    ([{"id": "49", "text": "Our own post"}, {"id": "50", "text": "A comment"}], False),
    ([{"id": "50", "text": "Replying to @ouraccount"}], False),
    ([{"id": "50", "text": "En réponse à @ouraccount"}], False),
    ([{"id": "50", "text": "Loading", "has_text": False}], False),
    ([{"id": "99", "text": "A different post"}], False),
    ([{"id": "50", "text": "Grok Imagine generated video", "author": "ELONMUSK"}], False),
    ([{"id": "50", "text": "Grok Imagine generated video", "author": "otherauthor"}], False),
    ([{"id": "50", "text": "Grok Imagine generated video", "quoted": True}], False),
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
        global.document = {querySelectorAll: () => fixtures.map(f => {
          const article = {innerText: f.text};
          const closest = selector => selector === 'article' ? article : f.quoted ? {} : null;
          const path = '/' + (f.author || 'author') + '/status/' + f.id;
          article.querySelectorAll = selector => selector === 'a[href]'
            ? [{pathname: path, href: 'https://x.com' + path, querySelector: () => ({}), closest}]
            : f.has_text === false ? [] : [{innerText: f.text, closest}];
          return article;
        })};
        process.stdout.write(String(eval(process.argv[2])));
        """
        return subprocess.run([node, "-e", fixture, json.dumps(articles), js],
                              check=True, capture_output=True, text=True).stdout
    monkeypatch.setattr(safari, "_run_js", page)
    assert tc._standalone_reply_target("https://x.com/author/status/50") is expected
