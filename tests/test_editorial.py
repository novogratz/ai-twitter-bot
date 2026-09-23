import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.guards import action_guard as ag, active_hours as hours
from src.core import config
from src.editorial import editorial_bot as editorial

TORONTO = ZoneInfo("America/Toronto")


def clock(monkeypatch, value):
    monkeypatch.setattr(hours, "now_local", lambda: value)
    monkeypatch.setattr(ag, "now_local", lambda: value)
    monkeypatch.setattr(editorial, "now_local", lambda: value)


@pytest.mark.parametrize("when,awake", [
    ("2026-09-20T04:29:59-04:00", False),
    ("2026-09-20T04:30:00-04:00", True),
    ("2026-09-20T21:59:59-04:00", True),
    ("2026-09-20T22:00:00-04:00", False),
    ("2026-09-21T00:00:00-04:00", False),
    ("2026-11-01T09:29:59+00:00", False),
    ("2026-11-01T09:30:00+00:00", True),
    ("2026-03-08T08:29:59+00:00", False),
    ("2026-03-08T08:30:00+00:00", True),
])
def test_exact_waking_boundaries_and_dst(when, awake):
    assert hours.is_active(datetime.fromisoformat(when)) is awake


def test_night_rejects_all_posting_and_queued_jobs(monkeypatch):
    clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))
    called = []
    hours.awake_job(lambda: called.append(True))()
    assert not called
    for action in (ag.POST, ag.QUOTE, ag.REPLY, ag.RETWEET):
        assert not ag.can_post(action, urgent=True, high_value=True)[0]


def test_browser_wait_rechecks_bedtime(monkeypatch):
    from src.x.twitter_client import _AwakeSafariLock
    clock(monkeypatch, datetime(2026, 9, 20, 21, 59, tzinfo=TORONTO))
    browser = _AwakeSafariLock()
    released = []

    class SlowLock:
        def acquire(self):
            clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))

        def release(self):
            released.append(True)

    browser._lock = SlowLock()
    with pytest.raises(hours.OutsideActiveHours):
        with browser:
            pytest.fail("Browser action ran after bedtime")
    assert released == [True]


def test_submit_checks_bedtime_before_applescript(monkeypatch):
    from src.x import twitter_client as tc
    # Use the real helper (the suite normally prevents Safari calls).
    import importlib
    from unittest.mock import patch
    with patch("subprocess.run") as run:
        tc = importlib.reload(tc)
        clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))
        with pytest.raises(hours.OutsideActiveHours):
            tc._run_applescript("submission")
        run.assert_not_called()


def test_toronto_day_budget_ignores_dry_runs_and_uses_all_profile_actions(monkeypatch, tmp_path):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    rows = [{"action": ag.POST, "ts": "2026-09-20T03:59:00+00:00"},
            {"action": ag.POST, "ts": "2026-09-20T04:00:00+00:00", "dry_run": True}]
    rows += [{"action": action, "ts": "2026-09-20T06:00:00"}
             for action in [ag.POST] * 5 + [ag.QUOTE, ag.RETWEET]]
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(rows))
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    assert ag.count_today(ag.POST) == 5
    assert ag.profile_count_today() == 7
    assert not ag.can_post(ag.POST, urgent=True, high_value=True)[0]
    assert ag.can_post(ag.REPLY)[0]
    assert ag.seconds_since_last(ag.POST) == 6 * 3600


def test_replies_uncapped_but_still_paced(monkeypatch):
    monkeypatch.setattr(ag, "count_today", lambda action: 1_000_000)
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    assert ag.can_post(ag.REPLY)[0]
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: False)
    assert not ag.can_post(ag.REPLY, urgent=True)[0]


def test_stale_strategy_cannot_restore_quotes_or_raise_post_ceiling(monkeypatch, tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps({"caps": {"MAX_QUOTES_PER_DAY": 999,
                                          "MAX_ORIGINALS_PER_DAY": 999,
                                          "MAX_REPLIES_PER_DAY": 4}}))
    monkeypatch.setattr(config, "_LIVE_STRATEGY_FILE", str(path))
    assert config.get_live_cap("MAX_QUOTES_PER_DAY", 100) == 0
    assert config.get_live_cap("MAX_ORIGINALS_PER_DAY", 100) <= 7
    assert config.get_live_cap("MAX_REPLIES_PER_DAY", 100) == 0


def test_slots_do_not_catch_up_or_repeat_after_restart():
    at = lambda h, m: datetime(2026, 9, 20, h, m, tzinfo=TORONTO)
    assert editorial.due_slot(at(5, 0), {})[0] == "05:00"
    assert editorial.due_slot(at(5, 45), {}) is None
    assert editorial.due_slot(at(10, 0), {}) is None
    state = {"date": "2026-09-20", "slots": {"05:00": "published"}}
    assert editorial.due_slot(at(5, 30), state) is None
    state["slots"]["05:00"] = "pending"
    assert editorial.due_slot(at(5, 30), state) is None
    assert editorial.due_slot(at(21, 59), {})[0] == "21:30"
    assert editorial.due_slot(at(22, 0), {}) is None


@pytest.fixture
def draft_fixture(monkeypatch, tmp_path):
    now = datetime(2026, 9, 20, 8, tzinfo=TORONTO)
    clock(monkeypatch, now)
    monkeypatch.setattr(editorial, "STATE_FILE", tmp_path / "editorial.json")
    monkeypatch.setattr(editorial, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setenv("CONTENT_LANG_PRIMARY", "en")
    monkeypatch.setattr(editorial.content_guard, "is_duplicate", lambda text: False)
    quote = "Chat templates convert conversations into the format expected by the model."
    source = dict(id="0", title="Chat templates", url="https://huggingface.co/docs/transformers/chat_templating",
                  publisher="Hugging Face", body=quote, kind="knowledge", published_at="")
    draft = dict(source_id="0", text="Your model expects a particular conversation format. Check its chat template before changing your prompts; the wrapper around your words matters too.",
                 angle="format before prompting", takeaway="check the model chat template", evidence=[quote])
    review = {key: True for key in ("approved", "grounded", "ai_relevant", "adds_value", "natural_voice", "novel", "exceptional")}
    review["reason"] = "Specific, grounded and useful"
    monkeypatch.setattr(editorial, "_json_call", lambda *a: review)
    monkeypatch.setattr(editorial, "collect_sources", lambda *a: [source])
    monkeypatch.setattr(editorial, "draft_post", lambda *a: draft)
    return draft, source, review


def test_quality_gate_requires_actual_source_and_complete_boolean_review(draft_fixture):
    draft, source, review = draft_fixture
    assert editorial.review_draft(draft, [source], [])[0]
    review["grounded"] = "true"
    assert not editorial.review_draft(draft, [source], [])[0]
    review["grounded"] = True
    draft["evidence"] = ["Invented quote that never appeared in the article"]
    assert not editorial.review_draft(draft, [source], [])[0]


@pytest.mark.parametrize("text", ["AI is a game changer. " * 6, "Follow for more. " * 8, "Thoughts? " * 12])
def test_quality_gate_rejects_bait(draft_fixture, text):
    draft, source, _ = draft_fixture
    draft["text"] = text
    assert not editorial.review_draft(draft, [source], [])[0]


def test_seventh_post_needs_fresh_exceptional_news(draft_fixture):
    draft, source, review = draft_fixture
    assert not editorial.review_draft(draft, [source], [], exceptional=True)[0]
    source.update(kind="news", published_at=(hours.now_local() - timedelta(hours=2)).isoformat())
    assert editorial.review_draft(draft, [source], [], exceptional=True)[0]
    review["exceptional"] = False
    assert not editorial.review_draft(draft, [source], [], exceptional=True)[0]


def test_preview_has_no_writes_and_success_consumes_one_slot(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    calls = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: calls.append((text, k)) or True)
    assert editorial.run_editorial_cycle(preview=True)["approved"]
    assert not calls and not editorial.STATE_FILE.exists() and not editorial.AUDIT_FILE.exists()
    assert editorial.run_editorial_cycle()["approved"]
    assert len(calls) == 1 and calls[0][1] == {"editorial": True}
    assert calls[0][0].endswith(draft_fixture[1]["url"])
    assert editorial.run_editorial_cycle() is None
    assert len(calls) == 1


def test_weak_draft_never_posts_and_retries_are_bounded(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    draft_fixture[2]["adds_value"] = False
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: pytest.fail("weak draft published"))
    for _ in range(3):
        assert editorial.run_editorial_cycle()["approved"] is False
    assert editorial.run_editorial_cycle() is None
    assert not editorial._read_state().get("published")


def test_passes_without_a_draft_consume_no_attempt(monkeypatch, draft_fixture):
    """An Attempt is a Draft submitted to the Editor (CONTEXT.md). A feed
    outage, a generator error or an explicit skip must not burn the Slot."""
    from src.x import twitter_client as tc
    calls = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: calls.append(text) or True)
    monkeypatch.setattr(editorial, "collect_sources", lambda *a: [])
    for _ in range(3):
        assert editorial.run_editorial_cycle() is None
    monkeypatch.setattr(editorial, "collect_sources", lambda *a: [draft_fixture[1]])
    for no_draft in ({}, None, {"skip": True, "source_id": "0", "text": "", "evidence_ids": []}):
        monkeypatch.setattr(editorial, "draft_post", lambda *a, d=no_draft: d)
        for _ in range(3):
            assert editorial.run_editorial_cycle() is None
    def provider_down(*a):
        raise TimeoutError("cold load")
    monkeypatch.setattr(editorial, "draft_post", provider_down)
    assert editorial.safe_run_editorial_cycle() is None
    assert not editorial._read_state().get("attempts", {}).get("08:00")
    assert not editorial.AUDIT_FILE.exists()
    monkeypatch.setattr(editorial, "draft_post", lambda *a: draft_fixture[0])
    assert editorial.run_editorial_cycle()["approved"]
    assert len(calls) == 1
    assert editorial._read_state()["attempts"]["08:00"] == 1


def test_slow_generation_cannot_publish_after_window_or_bedtime(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: pytest.fail("expired draft published"))
    draft = draft_fixture[0]
    def slow(*args):
        clock(monkeypatch, datetime(2026, 9, 20, 9, tzinfo=TORONTO))
        return draft
    monkeypatch.setattr(editorial, "draft_post", slow)
    editorial.run_editorial_cycle()
    assert not editorial._read_state().get("slots")


def test_failed_or_ambiguous_submission_does_not_log_success(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: False)
    editorial.run_editorial_cycle()
    assert not editorial._read_state()["slots"]
    assert not editorial._read_state()["published"]
    def ambiguous(*a, **k):
        raise RuntimeError("connection interrupted after submission")
    monkeypatch.setattr(tc, "post_tweet", ambiguous)
    with pytest.raises(RuntimeError):
        editorial.run_editorial_cycle()
    assert editorial._read_state()["slots"]["08:00"] == "pending"
    assert editorial.run_editorial_cycle() is None


def test_concurrent_posts_cannot_both_take_last_slot(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.x import twitter_client as tc
    clock(monkeypatch, datetime(2026, 9, 20, 12, tzinfo=TORONTO))
    for _ in range(6):
        ag.record(ag.POST)
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    monkeypatch.setattr(tc.content_guard if hasattr(tc, "content_guard") else editorial.content_guard, "is_duplicate", lambda *a: False)
    monkeypatch.setattr(tc, "_record_posted", lambda *a: None)
    monkeypatch.setattr(tc, "_run_applescript", lambda *a: True)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    barrier = Barrier(2)
    original_validate = editorial.content_guard.validate
    def simultaneous(*a, **k):
        result = original_validate(*a, **k)
        barrier.wait(timeout=3)
        return result
    monkeypatch.setattr(editorial.content_guard, "validate", simultaneous)
    text = "AI model evaluation needs examples from your real workflow. Test the failure cases your team actually sees before choosing a model."
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: tc.post_tweet(text, editorial=True), range(2)))
    assert sorted(results) == [False, True]
    assert ag.count_today(ag.POST) == 7


def test_source_dates_and_domains_are_checked():
    assert editorial._stamp("Sun, 20 Sep 2026 10:00:00 +0200").hour == 8
    assert editorial._stamp("2026-09-20T10:00:00") is None
    assert not editorial._trusted("https://huggingface.co.evil.example/guide")
    assert not editorial._trusted("http://huggingface.co/guide")
    assert editorial._trusted("https://huggingface.co/docs/transformers")


def test_reach_reports_missing_coverage_without_inventing_homepage_views():
    from src.editorial.reach_report import summarize
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    posts = [dict(ts=now.isoformat(), text="A useful AI workflow", slot="08:00"),
             dict(ts=now.isoformat(), text="Another AI idea", slot="11:30")]
    tweet = dict(url=f"https://x.com/{config.BOT_HANDLE}/status/1", text=posts[0]["text"], views=250, likes=5)
    report = summarize(posts, [tweet, tweet], now)
    assert report["views"] == 250 and report["target_views"] == 500_000
    assert report["originals_observed"] == 1 and not report["coverage_complete"]
    assert report["homepage_views"] is None


def test_reply_only_still_registers_the_reply_engine():
    from main import build_scheduler
    scheduler = build_scheduler(reply_only=True)
    assert scheduler.get_job("direct_reply_job") is not None
    assert scheduler.get_job("replyback_job") is not None
    assert scheduler.get_job("editorial_job") is None


def test_structured_editorial_json_preserves_text_and_evidence():
    from src.core.llm_client import unwrap_text
    draft = {"text": "A useful post", "source_id": "1", "evidence": ["source quote"]}
    assert json.loads(unwrap_text(json.dumps(draft), structured_output=True)) == draft


def test_article_extraction_prioritizes_content_over_navigation():
    html = '<main><div>menu menu menu</div><div class="prose-doc relative"><p>Useful AI facts here.</p></div></main>'
    assert editorial._plain(html) == "Useful AI facts here."


def test_corrupt_ledger_cannot_grant_extra_posts(monkeypatch, tmp_path):
    ledger = tmp_path / "broken.json"
    ledger.write_text("{broken")
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(ledger))
    with pytest.raises(RuntimeError, match="ledger unreadable"):
        ag.can_post(ag.POST)


def test_editorial_requests_use_dedicated_model_and_strict_schema(monkeypatch):
    import urllib.request
    from src.core import llm_client as llm
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"response": "{}"}'

    def request(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", request)
    monkeypatch.setattr(llm, "EDITORIAL_OLLAMA_MODEL", "editor-model")
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "reply-model")
    llm._run_ollama_http("Draft prompt", "EDITORIAL_DRAFT", 30)
    llm._run_ollama_http("Review prompt", "EDITORIAL_REVIEW", 30)
    llm._run_ollama_http("Reply prompt", "DIRECT_REPLY", 30)
    assert requests[0]["model"] == requests[1]["model"] == "editor-model"
    assert "evidence_ids" in requests[0]["format"]["required"]
    assert requests[1]["format"]["properties"]["grounded"] == {"type": "boolean"}
    assert requests[2]["model"] == "reply-model" and "format" not in requests[2]
    assert llm._FUNNY_FORCER not in requests[0]["prompt"]


def test_explicit_skip_is_not_publishable_even_with_complete_fields(draft_fixture):
    draft, source, _ = draft_fixture
    draft["skip"] = True
    assert not editorial.review_draft(draft, [source], [])[0]


def test_evidence_ids_resolve_to_exact_fetched_text(draft_fixture):
    draft, source, _ = draft_fixture
    draft["evidence_ids"] = ["0"]
    draft["evidence"] = ["invented quotation"]
    assert editorial.review_draft(draft, [source], [])[0]
    assert draft["evidence"] == [source["body"]]
    draft["evidence_ids"] = ["invented"]
    assert not editorial.review_draft(draft, [source], [])[0]


def test_source_collection_excludes_stale_future_and_undated_news(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    feed = "https://openai.com/news/rss.xml"
    monkeypatch.setattr(editorial, "FEEDS", (("OpenAI", feed),))
    monkeypatch.setattr(editorial, "KNOWLEDGE", ())
    items = "".join(
        f"<item><title>AI model {name}</title><link>https://openai.com/{name}</link>"
        f"<pubDate>{stamp}</pubDate></item>"
        for name, stamp in (("fresh", "2026-09-20T10:00:00-04:00"),
                            ("old", "2026-09-10T10:00:00-04:00"),
                            ("future", "2026-09-21T10:00:00-04:00"),
                            ("unknown", "")))
    xml = f"<rss><channel>{items}</channel></rss>"
    monkeypatch.setattr(editorial, "_fetch", lambda url: xml if url == feed else
                        "<article>" + "A useful AI model update with sourced details. " * 10 + "</article>")
    sources = editorial.collect_sources({}, now)
    assert [s["url"] for s in sources] == ["https://openai.com/fresh"]
