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


@pytest.fixture
def no_startup(monkeypatch):
    monkeypatch.setattr(editorial, "_startup_opened_at", None)
    monkeypatch.setattr(editorial, "_trend_cache", {})


def test_startup_window_opens_on_every_waking_start(no_startup):
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


def test_startup_post_goes_before_an_open_slot(no_startup):
    at = datetime(2026, 9, 20, 10, 20, tzinfo=TORONTO)
    assert editorial.next_slot(at, {})[0] == "10:00"
    editorial.open_startup_window(at)
    assert editorial.next_slot(at, {})[0] == "startup@10:20:00"


TRENDING = [dict(text=f"AI model story {i}", likes=100, views=1000, age_minutes=60,
                 likes_per_minute=1.6) for i in range(5)]


@pytest.fixture
def trend_fixture(monkeypatch, draft_fixture, no_startup):
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


def test_trending_posts_are_fresh_ranked_anonymous_and_cached(monkeypatch, no_startup):
    from src.core import config
    from src.x import scraper
    from tests.helpers import fresh
    monkeypatch.setattr(config, "BLOCKLIST", {"blockedguy"})
    def tweet(handle, minutes, likes, text, n):
        return dict(url=fresh(handle, minutes, n), text=text, likes=likes, views=likes * 10)
    # (age in minutes, likes): likes per minute 10, 6, 4, 3, 2, 1. The
    # fastest is not the newest, and the order below is shuffled.
    speed = [(300, 3000), (100, 600), (200, 800), (50, 150), (30, 60), (20, 20)]
    good = [tweet(f"writer{i}", speed[i][0], speed[i][1], f"New AI model {i} from @lab https://t.co/x", i)
            for i in (3, 5, 0, 4, 1, 2)]
    noise = [
        tweet(config.BOT_HANDLE, 30, 900, "Our AI model take", 10),
        tweet("blockedguy", 30, 900, "An AI model rant", 11),
        tweet("oldtimer", 30 * 60, 9000, "Old AI model news", 12),
        tweet("replier", 30, 900, "@someone the AI model is fine", 13),
        tweet("shill", 30, 900, "AI agent token airdrop today", 14),
        tweet("chef", 30, 900, "A great pasta recipe", 15),
    ]
    searches = []
    def search(query, **k):
        searches.append((query, k))
        return good + noise
    monkeypatch.setattr(scraper, "scrape_x_search", search)
    now = datetime.now(TORONTO)
    posts = editorial.collect_trending_posts(("10:00", "x"), now)
    assert [p["text"] for p in posts] == [f"New AI model {i} from" for i in range(5)]
    assert all(k["tab"] == "top" and k["text_limit"] > 200 for _, k in searches)
    assert len(searches) == len(editorial.TREND_QUERIES)
    assert editorial.collect_trending_posts(("10:00", "x"), now) == posts
    assert len(searches) == len(editorial.TREND_QUERIES)


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
             "pending_sources": {"2026-09-20/startup@11:10:00": "https://openai.com/launch"}}
    assert editorial.collect_sources(state, now) == []


def test_pending_source_is_released_only_when_nothing_was_sent(monkeypatch, draft_fixture):
    from src.x import twitter_client as tc
    url = draft_fixture[1]["url"]
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.FAILED)
    editorial.run_editorial_cycle()
    assert editorial._read_state()["pending_sources"] == {}
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.UNCONFIRMED)
    editorial.run_editorial_cycle()
    assert editorial._read_state()["pending_sources"] == {"2026-09-20/07:15": url}
    # Kept across the day reset, and not overwritten by tomorrow's 07:15:
    # the post may be live.
    clock(monkeypatch, datetime(2026, 9, 21, 7, 30, tzinfo=TORONTO))
    monkeypatch.setattr(tc, "post_tweet", lambda *a, **k: WriteOutcome.FAILED)
    seen = []
    source = draft_fixture[1]
    monkeypatch.setattr(editorial, "collect_sources",
                        lambda state, *a, **k: seen.append(dict(state.get("pending_sources", {}))) or [source])
    editorial.run_editorial_cycle()
    assert seen == [{"2026-09-20/07:15": url}]
    assert editorial._read_state()["pending_sources"] == {"2026-09-20/07:15": url}


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
