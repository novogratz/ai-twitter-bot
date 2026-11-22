from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import threading

import pytest

from src.core import account, settings
from src.core.state_errors import StateUnreadable
from src.guards import active_hours, reply_admission, replied_store, reply_budget
from src.replies import review
from src.replies.reply_generator import Generation, Outcome
from src.x import confirmed_write, twitter_client, x_urls


@pytest.fixture
def mode(settings_override, monkeypatch):
    settings_override(REPLY_REVIEW_ONLY=True, REPLY_REVIEW_DAILY_LIMIT=20, MAX_REPLIES_PER_DAY=0)
    monkeypatch.setattr(active_hours, "_STOP", threading.Event())


def source(author="builder", n=0, *, text=None, hours=1):
    now = active_hours.now_local()
    sid = str((int((now - timedelta(hours=hours)).timestamp() * 1000) - 1288834974657) << 22 | n)
    return {"url": f"https://x.com/{author}/status/{sid}",
            "text": text or "How can I reduce GPU memory use for an AI language model with long prompts?",
            "observed_at": now.isoformat(), "is_reply": False}


@pytest.fixture
def generation(monkeypatch):
    calls = []
    def generate(call, **kwargs):
        calls.append(kwargs)
        return Generation(Outcome.WRITTEN, "en",
                          f"Try a batch size of {len(calls)} first. Reducing concurrent requests reduces the memory needed for the key and value cache; weights still need to fit separately.",
                          "test", "fixture")
    monkeypatch.setattr(review.reply_generator, "generate", generate)
    return calls


def test_real_help_requests_rank_before_popularity_and_rhetorical_promotion():
    assert review.priority("How do I debug an AI agent that keeps calling the same tool?") == 0
    assert review.priority("Can I run this language model on my GPU?") == 0
    assert review.priority("Looking for advice on AI model evaluation") == 0
    assert review.priority("How can I test whether the AI evaluators agree? Thoughts?") == 0
    assert review.priority("My AI demo has a million views") == 1
    assert review.priority("How can AI change everything? Comment yes to get my course") == 1


def test_drafts_create_no_publication_claims_and_questions_go_first(mode, generation):
    announcement = source("announcer", 1, text="The open source AI model now supports offline inference.")
    question = source("asker", 2)
    assert review.import_sources([announcement, question])["added"] == 2
    result = review.prepare()
    assert result["drafts_created"] == 2 and result["published"] == 0
    assert generation[0]["author"] == "asker"
    assert reply_budget.entries() == {}
    assert not replied_store.load_replied()
    from src.guards import action_guard
    assert action_guard._ledger().count(action_guard.REPLY, active_hours.now_local().date()) == 0
    report = Path(review.REPORT).read_text()
    assert "Open original post" in report and "Proposed reply" in report
    assert "not consent to an automated reply" in report
    assert not any(row.get("receipt") for row in review.entries()["items"].values())


def test_restart_dismissal_and_concurrent_passes_do_not_refill_daily_cap(mode, generation, settings_override):
    settings_override(REPLY_REVIEW_DAILY_LIMIT=2)
    review.import_sources([source(f"builder{n}", n) for n in range(4)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: review.prepare(), range(2)))
    assert sum(row["drafts_created"] for row in results) == 2
    rows = review.entries()["items"]
    first = next(sid for sid, row in rows.items() if row["status"] == "draft")
    review.decide(first, "dismissed")
    assert review.prepare()["drafts_created"] == 0
    assert len(generation) == 2
    assert "2/2" in Path(review.REPORT).read_text()


def test_one_selected_draft_per_author_per_day(mode, generation):
    review.import_sources([source(n=1), source(n=2)])
    assert review.prepare()["drafts_created"] == 1
    assert len(generation) == 1


def test_stale_unknown_standalone_and_duplicate_sources_are_rejected(mode):
    valid = source()
    result = review.import_sources([valid, valid, source("old", 2, hours=25),
                                    {**source("unknown", 3), "is_reply": None}])
    assert result["added"] == 1
    assert sum(result["refused"].values()) == 3


def test_opt_out_dismisses_pending_and_blocks_legacy_admission(mode, generation, settings_override):
    post = source()
    review.import_sources([post])
    review.prepare()
    review.opt_out("@BUILDER")
    assert review.entries()["items"][x_urls.status_id(post["url"])]["status"] == "dismissed"
    settings_override(REPLY_REVIEW_ONLY=False)
    assert reply_admission.judge_parent(source(n=99)["url"]).refusal is reply_admission.Refusal.OPT_OUT
    assert review.import_sources([source(n=99)])["added"] == 0


@pytest.mark.parametrize("wording", ["No bots please.", "AI bots, don't reply.", "I don't want automated replies.",
                                    "Please stop replying to me.", "Do not contact me."])
def test_source_opt_out_survives_future_posts(mode, wording):
    assert review.import_sources([source(text="How can I fix my AI agent? " + wording)])["added"] == 0
    assert review.opted_out("builder")
    assert review.import_sources([source(n=3)])["added"] == 0


def test_existing_permanent_and_uncertain_history_remain_authoritative(mode):
    post = source()
    replied_store.save_replied([post["url"]])
    assert review.import_sources([post])["added"] == 0
    other = source("other", 2)
    reply_budget.STATE.write({x_urls.status_id(other["url"]): {
        "target": other["url"], "submitted_at": active_hours.now_local().isoformat(), "status": "pending"}})
    assert review.import_sources([other])["added"] == 0


def test_generic_duplicate_and_model_skips_create_no_drafts(mode, monkeypatch):
    posts = [source(f"builder{n}", n) for n in range(3)]
    review.import_sources(posts)
    monkeypatch.setattr(review.reply_generator, "generate", lambda *a, **k: Generation(Outcome.WRITTEN, "en", "Amazing!"))
    assert review.prepare()["drafts_created"] == 0
    assert all(row["status"] == "skipped" for row in review.entries()["items"].values())


def test_stop_during_generation_does_not_save_draft(mode, monkeypatch):
    review.import_sources([source()])
    def interrupted(*a, **k):
        active_hours.request_stop()
        return Generation(Outcome.WRITTEN, "en", "Reducing the context window reduces the memory needed for the key and value cache.")
    monkeypatch.setattr(review.reply_generator, "generate", interrupted)
    assert review.prepare()["drafts_created"] == 0
    assert all(row["status"] == "source" for row in review.entries()["items"].values())


def test_corrupt_queue_fails_closed_without_replacing_it(mode):
    review.QUEUE.write({"version": 1, "items": {"bad": {"status": "draft"}}})
    before = Path(review.QUEUE.path).read_bytes()
    with pytest.raises(StateUnreadable):
        review.prepare()
    assert Path(review.QUEUE.path).read_bytes() == before


def test_manual_post_report_is_not_a_verified_receipt(mode, generation, settings_override):
    post = source()
    review.import_sources([post])
    review.prepare()
    sid = x_urls.status_id(post["url"])
    receipt = source(account.current().handle, 99)["url"]
    review.decide(sid, "reported_posted", receipt=receipt)
    assert reply_budget.entries() == {} and not replied_store.load_replied()
    settings_override(REPLY_REVIEW_ONLY=False)
    assert reply_admission.judge_parent(post["url"]).refusal is reply_admission.Refusal.MANUAL_REVIEW


@pytest.mark.parametrize("enum", [confirmed_write.WriteOutcome, twitter_client.LikeOutcome, twitter_client.FollowOutcome])
@pytest.mark.parametrize("dry", [True, False])
def test_review_refuses_all_shared_writes_before_browser_or_ledger(mode, monkeypatch, settings_override, enum, dry):
    settings_override(DRY_RUN=dry)
    def forbidden(*args, **kwargs):
        raise AssertionError("Review mode reached a browser, claim, ledger or send")
    result = confirmed_write.run("TEST", enum, would=forbidden, rows=forbidden,
                                 steps=forbidden, before_lock=(confirmed_write.DRY_RUN_EXIT,))
    assert result is enum.REFUSED


def test_review_scheduler_has_no_jobs_even_with_all_features_enabled(mode, settings_override):
    from main import build_scheduler
    from src.video import config
    settings_override(VIDEO_ENABLED=True, VIDEO_LIVE=True, NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True,
                      MEME_REPOST_ENABLED=True)
    assert build_scheduler(startup_publications=True).get_jobs() == []
    assert not config.live()


def test_empty_queue_exports_clear_next_step(mode):
    assert review.prepare()["drafts_created"] == 0
    assert "No current drafts ready" in Path(review.REPORT).read_text()


def test_normal_start_in_review_mode_cannot_reach_live_startup(mode, monkeypatch, capsys):
    import sys
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "--startup-publications"])
    def forbidden(*args, **kwargs):
        pytest.fail("Review start reached the scheduler or publisher")
    monkeypatch.setattr(main, "build_scheduler", forbidden)
    monkeypatch.setattr(main, "_request_startup_video", forbidden)
    monkeypatch.setattr(main, "_request_startup_news", forbidden)
    monkeypatch.setattr(main.signal, "signal", lambda *args: None)
    main.main()
    assert '"published": 0' in capsys.readouterr().out


def test_dry_run_cannot_import_sources_or_generate_drafts(mode, monkeypatch):
    import sys
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run", "--reply-review", "prepare"])
    monkeypatch.setattr(review, "prepare", lambda: pytest.fail("dry run generated drafts"))
    with pytest.raises(SystemExit) as stopped:
        main.main()
    assert stopped.value.code == 2


def test_duplicate_draft_text_is_not_selected_twice(mode, monkeypatch):
    review.import_sources([source("builder1", 1), source("builder2", 2)])
    monkeypatch.setattr(review.reply_generator, "generate", lambda *a, **k: Generation(
        Outcome.WRITTEN, "en", "Reducing the context length reduces the memory needed for the key and value cache during inference."))
    assert review.prepare()["drafts_created"] == 1
    assert "repeated wording" in next(row["reason"] for row in review.entries()["items"].values() if row["status"] == "skipped")


def test_next_toronto_day_gets_new_capacity_without_resetting_history(mode, generation, settings_override, monkeypatch):
    settings_override(REPLY_REVIEW_DAILY_LIMIT=1)
    review.import_sources([source("builder1", 1)])
    assert review.prepare()["drafts_created"] == 1
    tomorrow = active_hours.now_local() + timedelta(days=1)
    monkeypatch.setattr(active_hours, "now_local", lambda: tomorrow)
    review.import_sources([source("builder2", 2)])
    assert review.prepare()["drafts_created"] == 1
    assert len(review.entries()["items"]) == 2


def followup(author="builder", n=10):
    original = source("creator", n, text="How do I keep a character consistent in my AI music video?", hours=3)
    prior = source(account.current().handle, n + 1, text="Keep the reference image fixed when comparing camera moves.", hours=2)
    return {**source(author, n + 2, text=f"@{account.current().handle} Does the same reference help with longer AI video shots?"),
            "is_reply": True, "thread": {"root_url": original["url"], "root_text": original["text"],
                "own_reply_url": prior["url"], "own_reply_text": prior["text"], "in_reply_to_url": prior["url"]}}


def test_complete_external_followups_are_manual_drafts_without_reopening_the_original(mode, generation):
    post = source(n=1)
    response = followup()
    assert review.import_sources([post, response])["added"] == 2
    assert review.prepare()["drafts_created"] == 2
    rows = review.entries()["items"]
    assert rows[x_urls.status_id(response["url"])]["thread_evidence"] == "operator-supplied context"
    assert response["thread"]["root_url"] not in replied_store.load_replied()
    assert not reply_budget.entries()
    assert "Conversation context" in review._CALL.template
    context = next(call["context"] for call in generation if call["text"].find("longer AI") != -1)
    assert response["thread"]["own_reply_text"] in context
    report = Path(review.REPORT).read_text()
    assert "confirm this relationship in X" in report and "not a verified publication receipt" in report
    assert review.import_sources([response])["added"] == 0


@pytest.mark.parametrize("case", ["missing", "own_root", "other_parent", "missing_text", "wrong_order"])
def test_incomplete_or_inconsistent_followup_snapshots_refuse(mode, case):
    post = followup()
    if case == "missing":
        del post["thread"]
    elif case == "own_root":
        post["thread"]["root_url"] = post["thread"]["own_reply_url"]
    elif case == "other_parent":
        post["thread"]["in_reply_to_url"] = source("stranger", 22)["url"]
    elif case == "missing_text":
        post["thread"]["own_reply_text"] = ""
    elif case == "wrong_order":
        post["thread"]["own_reply_url"] = source(account.current().handle, 22, hours=.5)["url"]
        post["thread"]["in_reply_to_url"] = post["thread"]["own_reply_url"]
    assert review.import_sources([post])["added"] == 0


def test_four_sessions_are_bounded_and_dismissals_do_not_refill_them(mode, generation, settings_override, monkeypatch):
    from tests.helpers import TORONTO, clock
    now = datetime(2026, 11, 20, 5, 1, tzinfo=TORONTO)
    clock(monkeypatch, now)
    settings_override(REPLY_REVIEW_DAILY_LIMIT=80, REPLY_MANUAL_DISCOVERY=True)
    assert review.import_sources([source(f"builder{n}", n) for n in range(90)])["added"] == 90
    for hour in (5, 10, 15, 20):
        clock(monkeypatch, now.replace(hour=hour))
        assert review.prepare()["drafts_created"] == 20
        assert review.prepare()["drafts_created"] == 0
    rows = review.entries()["items"]
    selected = [sid for sid, row in rows.items() if row["status"] == "draft"]
    assert len(selected) == 80
    review.decide(selected[0], "dismissed")
    assert review.prepare()["drafts_created"] == 0
    assert len(generation) == 80
    assert "60–80" in Path(review.REPORT).read_text()


def test_failed_generations_consume_session_attempts_without_becoming_drafts(mode, monkeypatch, settings_override):
    settings_override(REPLY_REVIEW_DAILY_LIMIT=80)
    review.import_sources([source(f"builder{n}", n) for n in range(30)])
    calls = []
    monkeypatch.setattr(review.reply_generator, "generate", lambda *a, **k: calls.append(k) or Generation(Outcome.FAILED, "en"))
    assert review.prepare()["generation_attempts"] == 20
    assert review.prepare()["generation_attempts"] == 0
    assert len(calls) == 20 and not any(row.get("draft") for row in review.entries()["items"].values())


def test_discovery_reads_exact_sources_and_cannot_send(mode, generation, settings_override, monkeypatch):
    from src.x import scraper
    settings_override(REPLY_MANUAL_DISCOVERY=True, REPLY_MANUAL_ORDINARY=True)
    monkeypatch.setenv("DRY_RUN", "0")
    candidates = [source("builder", 2, text="Short AI preview"), source("elonmusk", 3)]
    queries, reads = [], []
    def search(query, **kwargs):
        queries.append((query, kwargs))
        return candidates
    monkeypatch.setattr(scraper, "scrape_x_search", search)
    full = "How do I evaluate a new AI video model when several outputs change identity?"
    monkeypatch.setattr(twitter_client, "read_reply_source", lambda url: reads.append(url) or dict(url=url, text=full))
    monkeypatch.setattr(twitter_client, "reply_to_tweet", lambda *a, **k: pytest.fail("manual discovery tried to send"))
    result = review.discover_and_prepare()
    assert result["drafts_created"] == 1 and result["published"] == 0
    assert reads == [candidates[0]["url"]]
    assert full in generation[0]["text"]
    assert len(queries) == 4 and queries[0][1]["tab"] == "top"
    assert all(kwargs["max_tweets"] == 20 and kwargs["scroll_passes"] == 1 for _, kwargs in queries)
    review.discover_and_prepare()
    assert len(queries) == 4
    assert not replied_store.load_replied() and not reply_budget.entries()


@pytest.mark.parametrize("enabled,dry", [(False, False), (True, True)])
def test_discovery_requires_explicit_flag_and_never_runs_in_dry_run(mode, settings_override, monkeypatch, enabled, dry):
    from src.x import scraper
    settings_override(REPLY_MANUAL_DISCOVERY=enabled)
    monkeypatch.setenv("DRY_RUN", "1" if dry else "0")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: pytest.fail("disabled discovery reached Safari"))
    assert review.discover_and_prepare()["discovery"] == "disabled"
    assert not review.entries().get("sessions")


def test_discovery_rejects_a_full_source_from_another_url(mode, settings_override, monkeypatch):
    from src.x import scraper
    settings_override(REPLY_MANUAL_DISCOVERY=True)
    monkeypatch.setenv("DRY_RUN", "0")
    candidate = source()
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: [candidate])
    monkeypatch.setattr(twitter_client, "read_reply_source", lambda url: source("wrong", 7))
    monkeypatch.setattr(review.reply_generator, "generate", lambda *a, **k: pytest.fail("drafted a changed source"))
    assert review.discover_and_prepare()["drafts_created"] == 0


def test_metrics_are_self_reported_totals_separate_from_actual_receipts(mode, generation):
    import csv
    from src.core import config
    post = source()
    review.import_sources([post])
    review.prepare()
    own = source(account.current().handle, 22)["url"]
    review.decide(x_urls.status_id(post["url"]), "reported_posted", receipt=own)
    day = active_hours.today_iso()
    review.record_metrics(day, meaningful_responses=3, reply_views=120, minutes=40.5)
    review.record_metrics(day, reply_views=150)  # set a daily total; do not double count
    result = review.metrics_report()
    assert result["operator_reported_totals"]["reply_views"] == 150
    assert result["operator_reported_totals"]["attributable_follows"] is None
    assert result["operator_reported_posts"] == 1 and result["confirmed_own_receipts"] == 0
    assert not reply_budget.entries() and not replied_store.load_replied()
    with open(config.ENGAGEMENT_LOG_FILE, "w", newline="") as handle:
        csv.writer(handle).writerow([active_hours.now_local().isoformat(), "reply", "An existing confirmed reply.",
                                    post["url"], "SOURCE", "", "", "provider", "model", own])
    assert review.metrics_report()["confirmed_own_receipts"] == 1
    review.export_report()
    assert "Operator-reported totals are unverified" in Path(review.REPORT).read_text()


@pytest.mark.parametrize("metric,value", [("reply_views", -1), ("meaningful_responses", True),
                                         ("minutes", float("nan")), ("minutes", 1441), ("unknown", 1)])
def test_invalid_metrics_refuse_without_changing_history(mode, metric, value):
    before = review.entries()
    with pytest.raises(ValueError):
        review.record_metrics(active_hours.today_iso(), **{metric: value})
    assert review.entries() == before


_THREAD_DOM = r"""
const input = JSON.parse(process.argv[1]);
const articles = input.articles.map(spec => {
  const a = {innerText:(spec.reply ? 'Replying to @someone\n' : '') + spec.text};
  const node = (values, quoted=false) => ({...values, closest: selector => selector === 'article' ? a : (quoted ? {} : null)});
  const link = url => node({pathname:new URL(url).pathname, querySelector: () => ({})});
  a.querySelectorAll = selector => selector === 'a[href]' ? [link(spec.url)] :
    selector === '[data-testid="tweet-text-show-more-link"]' ? (spec.truncated ? [node({})] : []) :
    selector === '[data-testid="tweetText"]' ? [node({innerText:spec.text})] : [];
  return a;
});
global.document = {querySelector: () => ({getAttribute: () => '/' + input.owner}),
  querySelectorAll: selector => selector === 'main article' ? articles : []};
global.location = {href:input.page};
process.stdout.write(eval(input.script));
"""


@pytest.mark.parametrize("case", ["valid", "other_parent", "missing_root", "root_reply", "truncated", "wrong_page", "wrong_owner"])
def test_manual_thread_reader_requires_complete_visible_external_sequence(mode, monkeypatch, case):
    import json
    import shutil
    import subprocess
    import time
    from src.x import safari
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the read-only DOM fixture")
    post = followup()
    thread = post["thread"]
    articles = [dict(url=thread["root_url"], text=thread["root_text"], reply=False),
                dict(url=thread["own_reply_url"], text=thread["own_reply_text"], reply=True),
                dict(url=post["url"], text=post["text"], reply=True)]
    page, owner = post["url"], account.current().handle
    if case == "other_parent":
        articles[1]["url"] = source("stranger", hours=2)["url"]
    elif case == "missing_root":
        articles.pop(0)
    elif case == "root_reply":
        articles[0]["reply"] = True
    elif case == "truncated":
        articles[2]["truncated"] = True
    elif case == "wrong_page":
        page = source("stranger")["url"]
    elif case == "wrong_owner":
        owner = "stranger"
    def execute(script, *args, **kwargs):
        result = subprocess.run([node, "-e", _THREAD_DOM, json.dumps(dict(script=script, articles=articles, page=page, owner=owner))],
                                capture_output=True, text=True, check=True)
        return result.stdout
    monkeypatch.setattr(time, "sleep", lambda *a: None)
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", execute)
    result = review._read_thread(post["url"])
    assert bool(result) is (case == "valid")
    if result:
        assert result["thread"] == thread


def test_metric_cli_records_totals_without_publication(mode, capsys):
    review.main(["metrics", "--meaningful-responses", "4", "--repeat-interactions", "2", "--minutes", "37.5"])
    output = capsys.readouterr().out
    assert '"meaningful_responses": 4' in output and '"minutes": 37.5' in output
    assert '"confirmed_own_receipts": 0' in output
    assert not reply_budget.entries() and not replied_store.load_replied()


def test_metrics_outside_fourteen_days_stay_in_history_but_out_of_report(mode):
    older = (active_hours.now_local().date() - timedelta(days=14)).isoformat()
    review.record_metrics(older, reply_views=5000)
    review.record_metrics(active_hours.today_iso(), reply_views=30)
    assert review.metrics_report()["operator_reported_totals"]["reply_views"] == 30
    assert older in review.entries()["reported_metrics"]


@pytest.fixture
def boosted_manual(mode, settings_override, monkeypatch):
    from tests.helpers import TORONTO, clock
    now = datetime(2026, 11, 20, 5, 1, tzinfo=TORONTO)
    clock(monkeypatch, now)
    settings_override(REPLY_WORKLOAD_BOOST_START_DATE="2026-11-20", REPLY_WORKLOAD_BOOST_DAYS=4,
                      REPLY_WORKLOAD_BOOST_TARGET=200, REPLY_REVIEW_DAILY_LIMIT=80,
                      REPLY_MANUAL_DISCOVERY=True, REPLY_MANUAL_ORDINARY=True,
                      REPLY_REVIEW_ONLY=False, MAX_REPLIES_PER_DAY=80,
                      REPLY_DAILY_TARGET_MIN=60, REPLY_DAILY_TARGET_MAX=80)
    return now


def test_boost_reserves_watched_slots_and_reverts_without_resetting_sessions(boosted_manual, generation, monkeypatch):
    from tests.helpers import clock
    assert review.planning_capacity()["manual_draft_limit"] == 197
    review.import_sources([source(f"builder{n}", n) for n in range(210)])
    created = []
    for hour in (5, 10, 15, 20):
        clock(monkeypatch, boosted_manual.replace(hour=hour))
        created.append(review.prepare()["drafts_created"])
    assert created == [50, 50, 50, 47]
    assert review.prepare()["drafts_created"] == 0 and len(generation) == 197
    report = Path(review.REPORT).read_text()
    assert "up to 200" in report and "2026-11-24 without a restart" in report
    assert "197, after 0 known automatic submissions and 3 reserved" in report
    clock(monkeypatch, boosted_manual.replace(day=24))
    plan = review.planning_capacity()
    assert plan["manual_draft_limit"] == 77 and plan["session_limit"] == 20
    assert len(review.entries()["items"]) == 210  # historical 50-attempt sessions remain readable


def test_planning_counts_known_automatic_submissions_and_only_remaining_watched_reserve(boosted_manual):
    old = source("ordinary", 1)
    watched = source("elonmusk", 2)
    reply_budget.STATE.write({x_urls.status_id(post["url"]): {
        "target": post["url"], "submitted_at": active_hours.now_local().isoformat(), "status": "pending"}
        for post in (old, watched)})
    plan = review.planning_capacity()
    assert plan["known_automatic_submissions"] == 2
    assert plan["remaining_watched_reserve"] == 2
    assert plan["manual_draft_limit"] == 196


def test_boost_discovery_has_eight_query_and_eighty_source_bounds(boosted_manual, generation, monkeypatch):
    from src.x import scraper
    monkeypatch.setenv("DRY_RUN", "0")
    queries, reads = [], []
    def search(query, **kwargs):
        offset = len(queries) * 20
        queries.append(query)
        return [source(f"builder{n}", n) for n in range(offset, offset + 20)]
    monkeypatch.setattr(scraper, "scrape_x_search", search)
    monkeypatch.setattr(twitter_client, "read_reply_source", lambda url: reads.append(url) or
                        dict(url=url, text="How can I reduce GPU memory use for an AI language model with long prompts?"))
    result = review.discover_and_prepare()
    assert len(queries) == 8 and len(reads) == 80
    assert result["drafts_created"] == result["generation_attempts"] == 50
    assert any(query in account.current().searches.artist_videos for query in queries)
    assert any(query in account.current().searches.help_requests for query in queries)
    assert not reply_budget.entries() and not replied_store.load_replied()
