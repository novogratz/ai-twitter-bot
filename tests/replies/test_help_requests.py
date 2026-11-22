from collections import Counter
from datetime import timedelta
import pytest

from src.core import account
from src.guards import active_hours, reply_intent, review_store
from src.replies import help_requests, reply_pipeline
from src.x import x_urls


@pytest.fixture
def mode(settings_override, monkeypatch):
    settings_override(REPLY_INVITED_ONLY=True, REPLY_REVIEW_ONLY=False, MAX_REPLIES_PER_DAY=250,
                      REPLY_PUBLIC_REQUESTS=True, REPLY_DAILY_TARGET_MIN=250, REPLY_DAILY_TARGET_MAX=250)
    monkeypatch.setattr(help_requests, "_poll_count", 0)
    monkeypatch.setattr(help_requests, "_public_cursor", 0)
    from src.replies import candidate_buffer
    monkeypatch.setattr(candidate_buffer.time, "time", lambda: active_hours.now_local().timestamp())
    real_age = x_urls.age
    monkeypatch.setattr(x_urls, "age", lambda url, now=None: real_age(url, now or active_hours.now_local()))
    monkeypatch.setattr(help_requests, "_buffer", help_requests.Buffer(
        allow_leading_mention=True, max_age=timedelta(hours=24)))


def source(author="builder", n=0, **changes):
    now = active_hours.now_local() - timedelta(hours=1)
    sid = (int(now.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22 | n
    return {"url": f"https://x.com/{author}/status/{sid}",
            "text": f"@{account.current().handle} how do I debug my AI agent's tool loop?",
            "is_reply": True, "has_reply_context": False, **changes}


def test_discovery_accepts_direct_standalone_request_but_not_nested_quotes_or_mentions(mode):
    rows = [source(), source(n=1, has_reply_context=True), source(n=2, conversation_id="12"),
            source(n=3, text="An AI demo", quoted_text=source()["text"]),
            source(n=4, text="How do I debug my AI agent?"),
            source(n=5, has_reply_context=None), source(n=6, in_reply_to_status_id="12")]
    found = help_requests.candidates(rows)
    assert [item.url for item in found] == [rows[0]["url"]]
    assert found[0].text == rows[0]["text"]


def test_nested_complaint_is_recorded_before_reply_selection(mode):
    complaint = source(has_reply_context=True, text=f"@{account.current().handle} do not contact me.")
    assert help_requests.candidates([complaint, source(n=1)]) == []
    assert review_store.opted_out("builder")


def test_public_search_covers_latest_and_top_with_one_reply_budget(mode, monkeypatch, memory_ledger):
    reads, sends = [], []
    def read(query, **kwargs):
        reads.append((query, kwargs))
        return [source()]
    def run(job, candidates, cycle, **kwargs):
        sends.append((candidates, kwargs))
        return 1
    monkeypatch.setattr(help_requests, "scrape_x_search", read)
    monkeypatch.setattr(reply_pipeline, "run", run)
    assert help_requests.run_help_cycle() == 1
    since = (active_hours.now_local() - timedelta(hours=24)).date().isoformat()
    query = account.current().searches.help_requests[0] + f" since:{since}"
    assert reads == [(query, dict(tab=tab, max_tweets=40, text_limit=16000, scroll_passes=8))
                     for tab in ("latest", "top")]
    assert len(sends) == 1
    assert len(sends[0][0]) == 1  # the same status on two tabs is still one source
    assert sends[0][1] == dict(max_generations=3, max_shipped=1, ordinary_priority=True)


def test_uninvited_candidate_never_reaches_model_or_publisher(mode, monkeypatch, memory_ledger):
    monkeypatch.setattr(reply_pipeline.reply_generator, "generate", lambda *a, **k: pytest.fail("generated unsolicited reply"))
    monkeypatch.setattr(reply_pipeline.twitter_client, "reply_to_tweet", lambda *a, **k: pytest.fail("sent unsolicited reply"))
    row = source(text="My new AI agent demo looks great.")
    candidate = reply_pipeline.Candidate(row["url"], row["text"], "OTHER-JOB")
    assert reply_pipeline.run(help_requests.JOB, [candidate], reply_pipeline.Cycle()) == 0


def test_spacing_still_observes_opt_outs_without_generating(mode, monkeypatch, memory_ledger):
    from src.guards import action_guard
    action_guard.record(action_guard.REPLY, source("previous")["url"])
    monkeypatch.setattr(help_requests, "scrape_x_search", lambda *a, **k: [source(
        has_reply_context=True, text=f"@{account.current().handle} leave me alone.")])
    monkeypatch.setattr(reply_pipeline, "run", lambda *a, **k: pytest.fail("drafted during spacing hold"))
    assert help_requests.run_help_cycle() == 0
    assert review_store.opted_out("builder")


def test_near_boundary_draft_waits_until_four_minute_spacing_before_send(mode, monkeypatch, memory_ledger, settings_override):
    from src.guards import action_guard
    from src.replies.reply_generator import Generation, Outcome
    from src.x.confirmed_write import WriteOutcome
    settings_override(MIN_SECONDS_BETWEEN_REPLIES=8, REPLY_JITTER_SECONDS=0)
    start = active_hours.now_local()
    current = [start]
    monkeypatch.setattr(active_hours, "now_local", lambda: current[0])
    monkeypatch.setattr(action_guard, "now_local", lambda: current[0])
    memory_ledger.append(action_guard.REPLY, source("previous")["url"], False, start - timedelta(seconds=150))
    row = source(text="How do I debug my AI agent's repeated tool calls?", is_reply=False)
    monkeypatch.setattr(help_requests, "scrape_x_search", lambda *a, **k: [row])
    monkeypatch.setattr(reply_pipeline.twitter_client, "read_reply_source", lambda url: row)
    monkeypatch.setattr(reply_pipeline.reply_generator, "generate", lambda *a, **k: Generation(
        Outcome.WRITTEN, "en", "Limit the number of tool calls and log the arguments for each call to identify the loop."))
    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)
    monkeypatch.setattr(reply_pipeline, "_sleep", sleep)
    sent = []
    def publish(url, text, **kwargs):
        assert kwargs["expected_text"] == row["text"]
        assert action_guard.can_post(action_guard.REPLY)[0]
        sent.append(current[0])
        return WriteOutcome.SHIPPED
    monkeypatch.setattr(reply_pipeline.twitter_client, "reply_to_tweet", publish)
    assert help_requests.run_help_cycle() == 1
    assert sent == [start + timedelta(seconds=90)]


def test_advisory_target_never_generates_without_an_invitation(mode, monkeypatch, memory_ledger):
    monkeypatch.setattr(help_requests, "scrape_x_search", lambda *a, **k: [source(
        text="My new AI agent demo looks great.", is_reply=False)])
    monkeypatch.setattr(reply_pipeline.reply_generator, "generate", lambda *a, **k: pytest.fail("target generated filler"))
    assert help_requests.run_help_cycle() == 0


def test_reaching_daily_cap_still_observes_opt_outs_but_never_drafts(mode, monkeypatch, memory_ledger):
    from src.guards import action_guard
    for n in range(250):
        memory_ledger.append(action_guard.REPLY, source(f"previous{n}", n)["url"], False,
                             active_hours.now_local() - timedelta(hours=1))
    monkeypatch.setattr(help_requests, "scrape_x_search", lambda *a, **k: [source(
        text=f"@{account.current().handle} leave me alone.", has_reply_context=True)])
    monkeypatch.setattr(reply_pipeline, "run", lambda *a, **k: pytest.fail("daily cap still generated a draft"))
    assert help_requests.run_help_cycle() == 0
    assert review_store.opted_out("builder")


def test_public_query_rotation_keeps_every_fourth_turn_for_mentions(mode):
    pool = account.current().searches.help_requests
    queries = [help_requests.discovery_query()[0] for _ in range(8)]
    mention = f"@{account.current().handle} -filter:retweets"
    assert queries == [pool[0], pool[1], pool[2], mention,
                       pool[3 % len(pool)], pool[4 % len(pool)], pool[5 % len(pool)], mention]


def test_disabling_public_mode_keeps_mentions_only(mode, settings_override):
    settings_override(REPLY_PUBLIC_REQUESTS=False)
    assert help_requests.discovery_query()[0] == f"@{account.current().handle} -filter:retweets"
    assert help_requests.candidates([source(text="How do I debug my AI agent?", is_reply=False)]) == []


def test_discovery_logs_reasons_and_accepts_public_roots(mode, monkeypatch, memory_ledger, caplog):
    rows = [source(text="How do I debug my AI agent?", is_reply=False),
            source(n=1, has_reply_context=True),
            source(n=2, text="An AI demo", is_reply=False),
            source(author=account.current().handle, n=3)]
    reasons = Counter()
    assert [item.url for item in help_requests.candidates(rows, reasons=reasons)] == [rows[0]["url"]]
    assert reasons == {"nested reply": 1, "own post": 1,
                       "no explicit request for technical help or creative feedback": 1}
    monkeypatch.setattr(help_requests, "scrape_x_search", lambda *a, **k: rows)
    monkeypatch.setattr(reply_pipeline, "run", lambda *a, **k: 0)
    with caplog.at_level("INFO"):
        assert help_requests.run_help_cycle() == 0
    assert "4 sources, 1 request candidates, 1 buffered" in caplog.text
    assert "nested reply" in caplog.text
    assert "0 confirmed Replies" in caplog.text


def test_mention_turn_stays_one_shallow_read(mode):
    query = f"@{account.current().handle} -filter:retweets"
    assert help_requests.discovery_reads(query, "mentions and no-contact requests") == [
        (query, dict(tab="latest", max_tweets=20, text_limit=16000, scroll_passes=1))]


def test_unused_request_survives_an_empty_search_and_declined_work_leaves_queue(mode, monkeypatch, memory_ledger):
    row = source(text="How do I debug my AI agent?", is_reply=False)
    rows = [row]
    monkeypatch.setattr(help_requests, "scrape_x_search", lambda *a, **k: list(rows))
    offered = []
    def run(job, candidates, cycle, **kwargs):
        offered.append([c.url for c in candidates])
        if len(offered) == 2:
            cycle.completed.add(row["url"])
        return 0
    monkeypatch.setattr(reply_pipeline, "run", run)
    assert help_requests.run_help_cycle() == 0
    rows.clear()
    assert help_requests.run_help_cycle() == 0
    assert offered == [[row["url"]], [row["url"]]]
    assert help_requests._buffer.pending() == []


def test_buffer_expiry_is_not_extended_by_rediscovery(mode, monkeypatch, settings_override):
    import time
    settings_override(REPLY_CANDIDATE_BUFFER_TTL_SECONDS=120)
    now = time.time()
    rows = help_requests.candidates([source(is_reply=False, text="How do I debug my AI agent?")])
    help_requests._buffer.offer(rows, max_age=timedelta(hours=24))
    expiry = help_requests._buffer.pending()[0].expires_at
    monkeypatch.setattr(time, "time", lambda: now + 60)
    help_requests._buffer.offer(rows, max_age=timedelta(hours=24))
    assert help_requests._buffer.pending()[0].expires_at == expiry
    monkeypatch.setattr(time, "time", lambda: now + 121)
    assert help_requests._buffer.pending() == []
