"""src/editorial/editorial_bot: slots, sources, evidence, the separate
review, bounded attempts and ambiguous submissions."""
import json
import os
from datetime import datetime, timedelta

import pytest

from src.guards import active_hours as hours
from src.editorial import editorial_bot as editorial, editorial_schemas as schemas
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, USAGE_LIMIT, clock

# The real model calls, before draft_fixture stubs them.
REAL_JSON_CALL, REAL_DRAFT_POST = editorial._json_call, editorial.draft_post


def test_slots_do_not_catch_up_or_repeat_after_restart():
    at = lambda h, m: datetime(2026, 9, 20, h, m, tzinfo=TORONTO)
    assert editorial.due_slot(at(5, 0), {})[0] == "05:00"
    assert editorial.due_slot(at(5, 45), {}) is None
    assert editorial.due_slot(at(10, 15), {})[0] == "10:00"
    assert editorial.due_slot(at(10, 45), {}) is None
    state = {"date": "2026-09-20", "slots": {"05:00": "published"}}
    assert editorial.due_slot(at(5, 30), state) is None
    state["slots"]["05:00"] = "pending"
    assert editorial.due_slot(at(5, 30), state) is None
    assert editorial.due_slot(at(20, 45), {})[0] == "20:45"
    assert editorial.due_slot(at(21, 29), {})[0] == "20:45"
    assert editorial.due_slot(at(21, 30), {}) is None
    assert editorial.due_slot(at(22, 0), {}) is None
    assert editorial.due_slot(at(23, 0), {}) is None
    assert editorial.due_slot(at(23, 30), {}) is None


def test_evening_slots_stay_inside_waking_hours():
    """2026-07-19: the post-slot grid covers the measured best evening
    hours, inside Waking hours. Moving bedtime to 23:30 on 2026-09-23
    added no slot: 20:45 stays the last one, the exceptional one."""
    from src.editorial.editorial_bot import SLOTS
    wake, bedtime = f"{hours.WAKE:%H:%M}", f"{hours.BEDTIME:%H:%M}"
    assert all(wake <= clock < bedtime for clock, _ in SLOTS)
    assert max(clock for clock, _ in SLOTS) == "20:45"


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
    monkeypatch.setattr(tc, "post_tweet", lambda text: calls.append(text) or True)
    assert editorial.run_editorial_cycle(preview=True)["approved"]
    assert not calls and not os.path.exists(editorial.STATE.path) and not editorial.AUDIT_FILE.exists()
    assert editorial.run_editorial_cycle()["approved"]
    assert len(calls) == 1
    assert calls[0].endswith(draft_fixture[1]["url"])
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


@pytest.fixture
def exhausted(monkeypatch, providers):
    """Claude and its Codex fallback both at their usage limit, behind the
    real `_json_call`; nothing may reach X."""
    from src.core import config
    from src.core.llm_client import LLMResult
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: pytest.fail("published without a model answer"))
    monkeypatch.setattr(config, "PROFILE_LLM_PROVIDER", "claude")
    monkeypatch.setattr(editorial, "_json_call", REAL_JSON_CALL)
    providers.claude.answers = [LLMResult(1, "", "Claude AI usage limit reached|1790000000")]
    providers.codex.answers = [LLMResult(1, "", USAGE_LIMIT)]
    return providers


def test_an_exhausted_provider_drafts_nothing_and_spends_no_attempt(monkeypatch, draft_fixture, exhausted):
    """Issue #176: every provider at its usage limit is no Draft."""
    monkeypatch.setattr(editorial, "draft_post", REAL_DRAFT_POST)
    assert editorial.run_editorial_cycle() is None
    assert [name for name, _ in exhausted.calls] == ["claude", "codex"]
    assert not editorial._read_state().get("attempts", {}).get("07:15")
    assert not editorial._read_state().get("published")


def test_an_exhausted_provider_approves_nothing(draft_fixture, exhausted):
    """Issue #176: no review answer is no approval; the Attempt stays spent,
    as for any review that fails."""
    assert editorial.run_editorial_cycle()["approved"] is False
    assert [name for name, _ in exhausted.calls] == ["claude", "codex"]
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


EVIDENCE = ("Chat templates convert conversations into the format expected by the model.",
            "A mismatched template quietly degrades the answers of an instruction tuned model.",
            "The tokenizer applies the chat template before generation starts in the pipeline.")


@pytest.fixture
def editor_source(monkeypatch):
    """A source of three Evidence passages, a Draft citing two of them and
    a full approval, for the real Draft and review calls."""
    from types import SimpleNamespace
    monkeypatch.setenv("CONTENT_LANG_PRIMARY", "en")
    monkeypatch.setattr(editorial.content_guard, "is_duplicate", lambda text: False)
    source = dict(id="0", title="Chat templates", url="https://huggingface.co/docs/transformers/chat_templating",
                  publisher="Hugging Face", body=" ".join(EVIDENCE), kind="knowledge", published_at="")
    draft = dict(source_id="0", text="Your model expects a particular conversation format. Check its chat template before changing your prompts; the wrapper around your words matters too.",
                 angle="format before prompting", takeaway="check the model chat template",
                 evidence_ids=["0", "1"])
    review = {flag: True for flag in schemas.review_flags()} | {"reason": "Grounded and useful"}
    return SimpleNamespace(source=source, draft=draft, review=review)


@pytest.fixture
def editor(monkeypatch, editor_source):
    """editor_source behind a fake model that records every call and answers
    the Draft or the review by label."""
    from types import SimpleNamespace
    from src.core.llm_client import LLMResult
    editor_source.calls = []

    def model(prompt, model, **options):
        editor_source.calls.append(SimpleNamespace(prompt=prompt, model=model, **options))
        answer = editor_source.review if options["label"] == "EDITORIAL_REVIEW" else editor_source.draft
        return LLMResult(0, json.dumps(answer), "")

    monkeypatch.setattr(editorial, "run_llm", model)
    return editor_source


def draft_and_review(editor):
    """The Draft the real generator returns, and the review of it."""
    draft = editorial.draft_post(editorial.SLOTS[0], [editor.source], [])
    return draft, editorial.review_draft(draft, [editor.source], [])


def last_call(editor, label):
    return [call for call in editor.calls if call.label == label][-1]


def test_the_draft_and_the_review_run_on_the_profile_provider(monkeypatch, editor):
    """PROFILE_LLM_PROVIDER routes the Originals apart from AI_CLI, each
    call with its own profile."""
    from src.core import config
    monkeypatch.setattr(config, "PROFILE_LLM_PROVIDER", "gemini")
    assert draft_and_review(editor)[1][0]
    assert [(c.label, c.model, c.force_provider, c.profile) for c in editor.calls] == [
        ("EDITORIAL_DRAFT", config.NEWS_MODEL, "gemini", schemas.draft_profile()),
        ("EDITORIAL_REVIEW", config.NEWS_MODEL, "gemini", schemas.review_profile()),
    ]


def test_a_review_that_falls_back_to_ollama_keeps_the_review_schema(monkeypatch, editor_source):
    """Issue #174: the fallback renames the call "EDITORIAL_REVIEW
    (fallback)". When the label chose the schema, Ollama got the Draft's,
    answered a Draft, and the Editor rejected the Original without a word."""
    import io
    import urllib.request
    from src.core import config, llm_client as llm
    monkeypatch.setattr(config, "PROFILE_LLM_PROVIDER", "claude")
    monkeypatch.setenv("LLM_FALLBACK_CLI", "ollama")
    monkeypatch.delenv("LLM_DISABLE_FALLBACK", raising=False)
    cloud = []
    monkeypatch.setattr(llm, "_run_cmd",
                        lambda cmd, **k: cloud.append(k["label"]) or llm.LLMResult(1, "", "claude down"))
    requests = []

    def ollama(request, timeout=None):
        body = json.loads(request.data)
        requests.append(body)
        # Constrained decoding: the model answers in the shape of its schema.
        shaped = editor_source.review if body["format"] == schemas.review_schema() else editor_source.draft
        return io.BytesIO(json.dumps({"response": json.dumps(shaped)}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", ollama)
    ok, reason, _ = editorial.review_draft(dict(editor_source.draft), [editor_source.source], [])
    assert cloud == ["EDITORIAL_REVIEW"]
    [request] = requests
    assert request["format"] == schemas.review_schema()
    assert request["options"]["temperature"] == schemas.review_profile().temperature == 0.2
    assert ok, reason


def test_the_text_limit_moves_the_schema_the_prompt_and_the_check(monkeypatch, editor):
    assert draft_and_review(editor)[1][0]
    monkeypatch.setattr(schemas, "TEXT_MAX_CHARS", 120)
    _, (ok, reason, _) = draft_and_review(editor)
    draft_call = last_call(editor, "EDITORIAL_DRAFT")
    assert draft_call.profile.schema["properties"]["text"]["maxLength"] == 120
    assert "finish the thought before 120 characters" in draft_call.prompt
    assert not ok and "invalid length" in reason


def test_the_evidence_id_limit_moves_the_schema_the_prompt_and_the_check(monkeypatch, editor):
    assert draft_and_review(editor)[1][0]
    monkeypatch.setattr(schemas, "EVIDENCE_IDS_MAX", 1)
    _, (ok, reason, _) = draft_and_review(editor)
    draft_call = last_call(editor, "EDITORIAL_DRAFT")
    assert draft_call.profile.schema["properties"]["evidence_ids"]["maxItems"] == 1
    assert "Select 1–1 evidence IDs" in draft_call.prompt
    assert (ok, reason) == (False, "invalid source evidence IDs")


def test_the_evidence_passage_limit_moves_the_schema_the_prompt_and_the_check(monkeypatch, editor):
    editor.draft["evidence_ids"] = ["2"]
    assert draft_and_review(editor)[1][0]
    monkeypatch.setattr(schemas, "EVIDENCE_PASSAGES", 2)
    _, (ok, reason, _) = draft_and_review(editor)
    draft_call = last_call(editor, "EDITORIAL_DRAFT")
    assert draft_call.profile.schema["properties"]["evidence_ids"]["items"]["enum"] == ["0", "1"]
    assert EVIDENCE[1] in draft_call.prompt and EVIDENCE[2] not in draft_call.prompt
    assert (ok, reason) == (False, "invalid source evidence IDs")


def test_the_review_fields_move_the_schema_the_prompt_and_the_check(monkeypatch, editor):
    assert draft_and_review(editor)[1][0]
    monkeypatch.setattr(schemas, "APPROVAL_FLAGS", (*schemas.APPROVAL_FLAGS, "concise"))
    _, (ok, _, _) = draft_and_review(editor)
    review_call = last_call(editor, "EDITORIAL_REVIEW")
    assert "concise" in review_call.profile.schema["required"]
    assert review_call.profile.schema["properties"]["concise"] == {"type": "boolean"}
    assert "novel, exceptional, trending, concise" not in review_call.prompt
    assert "novel, concise, exceptional, trending" in review_call.prompt
    assert not ok
    editor.review["concise"] = True
    assert draft_and_review(editor)[1][0]


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


def test_a_spent_slot_does_not_hold_the_overlapping_next_one():
    """09:30 and 10:00 overlap: a published or spent 09:30 frees 10:00."""
    at = datetime(2026, 9, 20, 10, 5, tzinfo=TORONTO)
    assert editorial.due_slot(at, {})[0] == "09:30"
    assert editorial.due_slot(at, {"date": "2026-09-20", "slots": {"09:30": "published"}})[0] == "10:00"
    assert editorial.due_slot(at, {"date": "2026-09-20", "attempts": {"09:30": 3}})[0] == "10:00"
    assert editorial.due_slot(at, {"date": "2026-09-19", "attempts": {"09:30": 3}})[0] == "09:30"


def test_trend_slots_sit_in_the_grid():
    assert editorial.TREND_SLOTS == {"10:00", "13:00", "15:00"}
    assert editorial.TREND_SLOTS <= set(dict(editorial.SLOTS))


def test_startup_window_opens_on_every_waking_start():
    at = lambda h, m: datetime(2026, 9, 20, h, m, tzinfo=TORONTO)
    assert editorial.startup_slot(at(11, 10), {}) is None
    editorial.open_startup_window(at(11, 10))
    key = editorial.startup_key()
    assert key == "startup@11:10:00"
    assert editorial.startup_slot(at(11, 20), {}) == (key, editorial.TREND_PURPOSE)
    assert editorial.startup_slot(at(11, 55), {}) is None
    assert editorial.startup_slot(at(11, 20), {"date": "2026-09-20", "slots": {key: "pending"}}) is None
    assert editorial.startup_slot(at(11, 20), {"date": "2026-09-20", "attempts": {key: 3}}) is None
    # A restart the same day opens a fresh window, even after a published one.
    editorial.open_startup_window(at(11, 30))
    done = {"date": "2026-09-20", "slots": {key: "published"}}
    assert editorial.startup_slot(at(11, 31), done)[0] == "startup@11:30:00"
    # Nothing overnight: the watchdog relaunches at night, and a 04:20 start
    # must not publish at 04:30.
    editorial.open_startup_window(at(4, 20))
    assert editorial.startup_key() is None
    assert editorial.startup_slot(at(4, 35), {}) is None
    assert editorial.next_slot(at(4, 35), {}) is None


def test_startup_post_goes_before_an_open_slot():
    at = datetime(2026, 9, 20, 10, 20, tzinfo=TORONTO)
    assert editorial.next_slot(at, {})[0] == "10:00"
    editorial.open_startup_window(at)
    assert editorial.next_slot(at, {})[0] == "startup@10:20:00"


TRENDING = [dict(text=f"AI model story {i}", likes=100, views=1000, age_minutes=60,
                 likes_per_minute=1.6) for i in range(5)]


@pytest.fixture
def trend_fixture(monkeypatch, draft_fixture):
    draft, source, review = draft_fixture
    source.update(kind="news", published_at="2026-09-20T09:00:00-04:00")
    review["trending"] = True
    calls = dict(sources=[], drafts=[])
    def sources(state, now=None, news_only=False):
        calls["sources"].append(news_only)
        return [source]
    def drafted(*args):
        calls["drafts"].append(args)
        return draft
    monkeypatch.setattr(editorial, "collect_sources", sources)
    monkeypatch.setattr(editorial, "draft_post", drafted)
    monkeypatch.setattr(editorial, "collect_trending_posts", lambda slot, now=None: TRENDING)
    return calls


def test_every_restart_publishes_one_startup_post(monkeypatch, trend_fixture):
    from src.x import twitter_client as tc
    posted = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: posted.append(text) or True)
    clock(monkeypatch, datetime(2026, 9, 20, 11, 10, tzinfo=TORONTO))
    editorial.open_startup_window()
    assert editorial.run_editorial_cycle()["approved"]
    assert len(posted) == 1
    assert trend_fixture["sources"] == [True]
    assert trend_fixture["drafts"][0][4] == TRENDING
    assert editorial._read_state()["slots"]["startup@11:10:00"] == "published"
    assert editorial._read_state()["pending_sources"] == {}
    # Same process: the window is spent.
    assert editorial.run_editorial_cycle() is None
    assert len(posted) == 1
    # A restart publishes again.
    clock(monkeypatch, datetime(2026, 9, 20, 11, 40, tzinfo=TORONTO))
    editorial.open_startup_window()
    assert editorial.run_editorial_cycle()["approved"]
    assert len(posted) == 2


def test_trend_slot_without_enough_trending_posts_spends_no_attempt(monkeypatch, trend_fixture):
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: pytest.fail("posted without a trend"))
    clock(monkeypatch, datetime(2026, 9, 20, 13, 5, tzinfo=TORONTO))
    monkeypatch.setattr(editorial, "collect_trending_posts", lambda slot, now=None: TRENDING[:2])
    assert editorial.run_editorial_cycle() is None
    assert not editorial._read_state().get("attempts", {}).get("13:00")
    assert not trend_fixture["drafts"]


def test_trend_slot_drafts_from_news_only(monkeypatch, trend_fixture):
    from src.x import twitter_client as tc
    posted = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: posted.append(text) or True)
    clock(monkeypatch, datetime(2026, 9, 20, 13, 5, tzinfo=TORONTO))
    assert editorial.run_editorial_cycle()["approved"]
    assert trend_fixture["sources"] == [True]
    assert editorial._read_state()["slots"]["13:00"] == "published"


def test_trend_review_needs_news_no_mention_and_editor_trend_approval(draft_fixture):
    draft, source, review = draft_fixture
    review["trending"] = True
    assert not editorial.review_draft(draft, [source], [], trending=TRENDING)[0]  # knowledge doc
    source.update(kind="news")
    assert editorial.review_draft(draft, [source], [], trending=TRENDING)[0]
    review["trending"] = False
    assert not editorial.review_draft(draft, [source], [], trending=TRENDING)[0]
    assert editorial.review_draft(draft, [source], [])[0]
    review["trending"] = True
    draft["text"] = "@sama " + draft["text"][:200]
    assert not editorial.review_draft(draft, [source], [], trending=TRENDING)[0]


def test_a_restart_after_an_ambiguous_submission_skips_its_source(monkeypatch):
    """A crash mid-submission leaves the Startup post pending under the old
    process key; the next process's Startup post must not reuse the source."""
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    feed = "https://openai.com/news/rss.xml"
    monkeypatch.setattr(editorial, "FEEDS", (("OpenAI", feed),))
    monkeypatch.setattr(editorial, "KNOWLEDGE", ())
    xml = ("<rss><channel><item><title>AI model launch</title><link>https://openai.com/launch</link>"
           "<pubDate>2026-09-20T10:00:00-04:00</pubDate></item></channel></rss>")
    monkeypatch.setattr(editorial, "_fetch", lambda url: xml if url == feed else
                        "<article>" + "A useful AI model update with sourced details. " * 10 + "</article>")
    assert editorial.collect_sources({}, now)
    state = {"date": "2026-09-20", "slots": {"startup@11:10:00": "pending"},
             "pending_sources": {"2026-09-20/startup@11:10:00": dict(
                 url="https://openai.com/launch", text="An AI launch post",
                 ts="2026-09-20T11:10:10-04:00")}}
    assert editorial.collect_sources(state, now) == []


def test_pending_source_is_released_only_when_nothing_was_sent(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    url = draft_fixture[1]["url"]
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.FAILED)
    editorial.run_editorial_cycle()
    assert editorial._read_state()["pending_sources"] == {}
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.UNCONFIRMED)
    editorial.run_editorial_cycle()
    pending = {"2026-09-20/07:15": dict(url=url, text=draft_fixture[0]["text"],
                                        ts="2026-09-20T07:30:00-04:00")}
    assert editorial._read_state()["pending_sources"] == pending
    # Kept across the day reset, and not overwritten by tomorrow's 07:15:
    # the post may be live.
    clock(monkeypatch, datetime(2026, 9, 21, 7, 30, tzinfo=TORONTO))
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.FAILED)
    seen = []
    source = draft_fixture[1]
    monkeypatch.setattr(editorial, "collect_sources",
                        lambda state, *a, **k: seen.append(dict(state.get("pending_sources", {}))) or [source])
    editorial.run_editorial_cycle()
    assert seen == [pending]
    assert editorial._read_state()["pending_sources"] == pending


def test_a_startup_pass_without_a_draft_falls_through_to_the_grid(monkeypatch, trend_fixture):
    """A restart at 05:00 with no usable trend must not hide the 05:00 Slot."""
    from src.x import twitter_client as tc
    posted = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: posted.append(text) or True)
    clock(monkeypatch, datetime(2026, 9, 20, 5, 0, tzinfo=TORONTO))
    editorial.open_startup_window()
    monkeypatch.setattr(editorial, "collect_trending_posts", lambda slot, now=None: [])
    assert editorial.run_editorial_cycle()["slot"] == "05:00"
    assert editorial._read_state()["slots"] == {"05:00": "published"}
    assert trend_fixture["sources"] == [False]
    assert len(posted) == 1


def test_the_startup_window_closes_at_bedtime():
    at = lambda h, m: datetime(2026, 9, 20, h, m, tzinfo=TORONTO)
    editorial.open_startup_window(at(23, 10))
    key = editorial.startup_key()
    assert editorial.startup_slot(at(23, 29), {})[0] == key
    assert not editorial._in_window(key, at(23, 30))
    assert editorial.startup_slot(at(23, 30), {}) is None


def test_a_silent_slot_does_not_hide_the_overlapping_next_one(monkeypatch, trend_fixture):
    """At 10:05, 09:30 yields no Draft: 10:00 gets its pass at once, and a
    pass with two Drafts available still submits once."""
    from src.x import twitter_client as tc
    posted = []
    monkeypatch.setattr(tc, "post_tweet", lambda text, **k: posted.append(text) or True)
    clock(monkeypatch, datetime(2026, 9, 20, 10, 5, tzinfo=TORONTO))
    draft = editorial.draft_post
    monkeypatch.setattr(editorial, "draft_post",
                        lambda slot, *a: {} if slot.clock == "09:30" else draft(slot, *a))
    assert editorial.run_editorial_cycle()["slot"] == "10:00"
    assert editorial._read_state()["slots"] == {"10:00": "published"}
    assert not editorial._read_state()["attempts"].get("09:30")
    monkeypatch.setattr(editorial, "draft_post", draft)
    clock(monkeypatch, datetime(2026, 9, 21, 10, 5, tzinfo=TORONTO))
    assert editorial.run_editorial_cycle()["slot"] == "09:30"
    assert len(posted) == 2


def _unconfirmed_day(monkeypatch, starts):
    """Each start is a process: it opens its Startup post, then runs the
    editorial job every ten minutes until the next start or bedtime. Every
    submission comes back UNCONFIRMED. Returns the submission times."""
    from src.x import twitter_client as tc
    submitted = []
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: submitted.append(hours.now_local())
                        or WriteOutcome.UNCONFIRMED)
    bedtime = datetime(2026, 9, 20, 22, 0, tzinfo=TORONTO)
    for start, end in zip(starts, [*starts[1:], bedtime]):
        clock(monkeypatch, start)
        editorial.open_startup_window()
        at = start + timedelta(seconds=10)
        while at < end:
            clock(monkeypatch, at)
            editorial.run_editorial_cycle()
            at += timedelta(minutes=10)
    return submitted


def _assert_ceiling_and_spacing(submitted):
    from src.core import config
    assert len(submitted) == config.MAX_PROFILE_POSTS_PER_DAY == 8
    gaps = [(b - a).total_seconds() for a, b in zip(submitted, submitted[1:])]
    assert min(gaps) >= 1200


@pytest.mark.parametrize("crash_every", [1, 7, 20])
def test_a_crash_loop_of_unconfirmed_submissions_keeps_the_ceiling_and_spacing(
        monkeypatch, trend_fixture, crash_every):
    """UNCONFIRMED writes no ledger row: without the pending count, every
    restart submitted a Startup post, 63 a day at a crash every 20 minutes."""
    first = datetime(2026, 9, 20, 4, 30, tzinfo=TORONTO)
    starts = [first + timedelta(minutes=crash_every * i)
              for i in range(int(17.5 * 60 / crash_every))]
    _assert_ceiling_and_spacing(_unconfirmed_day(monkeypatch, starts))


def test_one_process_of_unconfirmed_submissions_keeps_the_ceiling_and_spacing(
        monkeypatch, trend_fixture):
    """Eleven Slots and the Startup post, all UNCONFIRMED: 12 submissions
    before pending ones counted."""
    _assert_ceiling_and_spacing(
        _unconfirmed_day(monkeypatch, [datetime(2026, 9, 20, 4, 30, tzinfo=TORONTO)]))


def test_pending_and_checked_submissions_count_toward_ceiling_and_spacing(monkeypatch, memory_ledger):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    entry = lambda ago: dict(url="https://openai.com/x", text="An AI post",
                             ts=(now - ago).isoformat())
    pending = {f"2026-09-20/startup@{h:02d}:00:00": entry(timedelta(hours=1)) for h in range(5, 11)}
    # Yesterday's pending may be live, but it counts toward yesterday.
    pending["2026-09-19/20:45"] = entry(timedelta(hours=15))
    state = {"date": "2026-09-20", "slots": {"11:45": "published"},
             "pending_sources": pending, "published": []}
    memory_ledger.append(editorial.action_guard.POST, "", False, now - timedelta(minutes=30))
    assert editorial._pending_refusal(state, now) == ""  # 1 shipped + 6 pending
    # The operator marked 09:30 published after a check: no ledger row.
    state["slots"]["09:30"] = "published"
    assert "ceiling" in editorial._pending_refusal(state, now)
    # The operator removed its pending_sources entry only.
    state["slots"]["09:30"] = "pending"
    assert "ceiling" in editorial._pending_refusal(state, now)
    del state["slots"]["09:30"]
    pending["2026-09-20/startup@10:00:00"] = entry(timedelta(minutes=19))
    assert "too soon" in editorial._pending_refusal(state, now)
    pending["2026-09-20/startup@10:00:00"] = entry(timedelta(minutes=20))
    assert editorial._pending_refusal(state, now) == ""


def test_a_pending_text_is_a_recent_post_for_the_next_draft_and_review(monkeypatch, draft_fixture,
                                                                       trend_fixture):
    """A restart after an ambiguous Startup post must not tell the same
    story from another article: its text reaches the generator and the
    Editor as a recent post."""
    from src.x import twitter_client as tc
    prompts = []
    monkeypatch.setattr(editorial, "_json_call",
                        lambda prompt, label, profile: prompts.append(prompt) or draft_fixture[2])
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.UNCONFIRMED)
    clock(monkeypatch, datetime(2026, 9, 20, 11, 10, tzinfo=TORONTO))
    editorial.open_startup_window()
    editorial.run_editorial_cycle()
    text = editorial._read_state()["pending_sources"]["2026-09-20/startup@11:10:00"]["text"]
    clock(monkeypatch, datetime(2026, 9, 20, 11, 40, tzinfo=TORONTO))
    editorial.open_startup_window()
    editorial.run_editorial_cycle()
    assert trend_fixture["drafts"][1][2] == [text]
    assert "RECENT: " + json.dumps([text], ensure_ascii=False) in prompts[-1]


def _pending_today(count):
    """`count` pending submissions made hours before draft_fixture's 07:30."""
    return {f"2026-09-20/startup@05:{m:02d}:00": dict(
        url="https://openai.com/x", text="An AI post", ts=f"2026-09-20T05:{m:02d}:10-04:00")
        for m in range(count)}


def test_a_full_day_of_pending_submissions_spends_no_attempt(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: pytest.fail("posted past the ceiling"))
    monkeypatch.setattr(editorial, "draft_post", lambda *a: pytest.fail("drafted past the ceiling"))
    editorial._save_state({"date": "2026-09-20", "slots": {}, "published": [],
                           "pending_sources": _pending_today(8)})
    assert editorial.run_editorial_cycle() is None
    assert not editorial._read_state().get("attempts")


def test_the_pending_count_is_checked_again_right_before_the_submit(monkeypatch, draft_fixture,
                                                                    memory_ledger):
    """A post shipped while the Editor reviewed fills the last place."""
    from src.x import twitter_client as tc
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: pytest.fail("posted past the ceiling"))
    editorial._save_state({"date": "2026-09-20", "slots": {}, "published": [],
                           "pending_sources": _pending_today(7)})
    review = draft_fixture[2]
    def shipped_during_review(prompt, label, profile):
        memory_ledger.append(editorial.action_guard.POST, "", False, hours.now_local())
        return review
    monkeypatch.setattr(editorial, "_json_call", shipped_during_review)
    assert editorial.run_editorial_cycle()["approved"]
    assert "07:15" not in editorial._read_state()["slots"]
