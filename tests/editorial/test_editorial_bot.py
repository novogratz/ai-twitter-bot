"""src/editorial/editorial_bot: slots, sources, evidence, the separate
review, bounded attempts and ambiguous submissions."""
import os
from datetime import datetime, timedelta

import pytest

from src.guards import active_hours as hours
from src.editorial import editorial_bot as editorial
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, clock


def test_slots_do_not_catch_up_or_repeat_after_restart():
    at = lambda h, m: datetime(2026, 9, 20, h, m, tzinfo=TORONTO)
    assert editorial.due_slot(at(5, 0), {})[0] == "05:00"
    assert editorial.due_slot(at(5, 45), {}) is None
    assert editorial.due_slot(at(10, 15), {}) is None
    state = {"date": "2026-09-20", "slots": {"05:00": "published"}}
    assert editorial.due_slot(at(5, 30), state) is None
    state["slots"]["05:00"] = "pending"
    assert editorial.due_slot(at(5, 30), state) is None
    assert editorial.due_slot(at(20, 45), {})[0] == "20:45"
    assert editorial.due_slot(at(21, 29), {})[0] == "20:45"
    assert editorial.due_slot(at(21, 30), {}) is None
    assert editorial.due_slot(at(22, 0), {}) is None


def test_evening_slots_stay_inside_waking_hours():
    """2026-07-19: the post-slot grid covers the measured best evening
    hours, inside Waking hours."""
    from src.editorial.editorial_bot import SLOTS
    assert all("04:30" <= clock < "22:00" for clock, _ in SLOTS)
    assert "20:45" in dict(SLOTS)


@pytest.fixture
def draft_fixture(monkeypatch, tmp_path):
    now = datetime(2026, 9, 20, 7, 30, tzinfo=TORONTO)
    clock(monkeypatch, now)
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


def test_eighth_post_needs_exceptional_value(draft_fixture):
    draft, source, review = draft_fixture
    review["exceptional"] = False
    assert not editorial.review_draft(draft, [source], [], exceptional=True)[0]
    review["exceptional"] = True
    assert editorial.review_draft(draft, [source], [], exceptional=True)[0]
    source.update(kind="news", published_at=(hours.now_local() - timedelta(hours=2)).isoformat())
    assert editorial.review_draft(draft, [source], [], exceptional=True)[0]
    review["exceptional"] = False
    assert not editorial.review_draft(draft, [source], [], exceptional=True)[0]


def test_preview_has_no_writes_and_success_consumes_one_slot(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    calls = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: calls.append((text, k)) or True)
    assert editorial.run_editorial_cycle(preview=True)["approved"]
    assert not calls and not os.path.exists(editorial.STATE.path) and not editorial.AUDIT_FILE.exists()
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
    assert not editorial._read_state().get("attempts", {}).get("07:15")
    assert not editorial.AUDIT_FILE.exists()
    monkeypatch.setattr(editorial, "draft_post", lambda *a: draft_fixture[0])
    assert editorial.run_editorial_cycle()["approved"]
    assert len(calls) == 1
    assert editorial._read_state()["attempts"]["07:15"] == 1


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


@pytest.mark.parametrize("outcome", [WriteOutcome.REFUSED, WriteOutcome.FAILED, WriteOutcome.DRY_RUN])
def test_a_write_that_sent_nothing_frees_the_slot(monkeypatch, draft_fixture, outcome):
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: outcome)
    editorial.run_editorial_cycle()
    assert not editorial._read_state()["slots"]
    assert not editorial._read_state()["published"]


def test_an_unconfirmed_submit_keeps_the_slot_pending(monkeypatch, draft_fixture):
    """The submit keystroke may have reached X: the slot is never retried
    automatically, the operator checks the profile first."""
    from src.x import twitter_client as tc
    calls = []
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: calls.append(a) or WriteOutcome.UNCONFIRMED)
    editorial.run_editorial_cycle()
    assert editorial._read_state()["slots"]["07:15"] == "pending"
    assert not editorial._read_state()["published"]
    assert editorial.run_editorial_cycle() is None
    assert len(calls) == 1


def test_an_interrupted_submission_keeps_the_slot_pending(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    def ambiguous(*a, **k):
        raise RuntimeError("connection interrupted after submission")
    monkeypatch.setattr(tc, "post_tweet", ambiguous)
    with pytest.raises(RuntimeError):
        editorial.run_editorial_cycle()
    assert editorial._read_state()["slots"]["07:15"] == "pending"
    assert editorial.run_editorial_cycle() is None


def test_source_dates_and_domains_are_checked():
    assert editorial._stamp("Sun, 20 Sep 2026 10:00:00 +0200").hour == 8
    assert editorial._stamp("2026-09-20T10:00:00") is None
    assert not editorial._trusted("https://huggingface.co.evil.example/guide")
    assert not editorial._trusted("http://huggingface.co/guide")
    assert editorial._trusted("https://huggingface.co/docs/transformers")
    assert editorial._trusted("https://mistral.ai/news")
    assert editorial._trusted("https://replicate.com/blog")
    assert editorial._trusted("https://the-decoder.com/artificial-intelligence-news/")
    assert editorial._trusted("https://arxiv.org/abs/2609.00001")


def test_source_pool_keeps_more_fresh_news_before_evergreen(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)

    def fake_fetch(url):
        if url.startswith("https://feed"):
            idx = int(url.rsplit("/", 1)[-1])
            published = (now - timedelta(hours=idx)).strftime("%a, %d %b %Y %H:%M:%S +0000")
            return f"""<?xml version="1.0"?><rss><channel><item>
                <title>AI model launch {idx}</title>
                <link>https://mistral.ai/news/launch-{idx}</link>
                <pubDate>{published}</pubDate>
            </item></channel></rss>"""
        return " ".join(["Fresh AI launch detail with a concrete model update."] * 40)

    monkeypatch.setattr(editorial, "FEEDS", tuple((f"Feed {i}", f"https://feed/{i}") for i in range(10)))
    monkeypatch.setattr(editorial, "_fetch", fake_fetch)

    sources = editorial.collect_sources({"published": []}, now)
    news = [source for source in sources if source["kind"] == "news"]
    assert len(news) == 5
    assert all(source["url"].startswith("https://mistral.ai/news/launch-") for source in news)
    assert {source["url"] for source in sources} <= {f"https://mistral.ai/news/launch-{i}" for i in range(8)}


def test_article_extraction_prioritizes_content_over_navigation():
    html = '<main><div>menu menu menu</div><div class="prose-doc relative"><p>Useful AI facts here.</p></div></main>'
    assert editorial._plain(html) == "Useful AI facts here."


def test_profile_surfaces_force_capable_provider():
    """Profile generators must pass force_provider=PROFILE_LLM_PROVIDER so
    profile/reply routing can be changed independently from AI_CLI."""
    import inspect
    from src.editorial import editorial_bot

    assert "force_provider=config.PROFILE_LLM_PROVIDER" in inspect.getsource(editorial_bot._json_call), \
        "the editorial generator must force the profile provider"

    from src.core import config
    # Default is Ollama, env-overridable to Codex/Gemini when needed.
    assert config.PROFILE_LLM_PROVIDER in ("ollama", "codex", "gemini", None) or \
        isinstance(config.PROFILE_LLM_PROVIDER, str)


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
