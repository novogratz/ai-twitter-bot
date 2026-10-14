"""Cross-cutting: an Account on another domain runs on the same engine (#208).

accounts/example/ is a fictitious home vegetable gardener, with no Relation:
`main.py --dry-run` with BOT_ACCOUNT=example lists its jobs and its ceilings,
without a browser or a model, and its state is state/example/. The dry run of
theaishrink keeps the jobs and ceilings it had before the refactor of #187,
frozen below from commit 9748c36d.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from src.core import account, settings, state_store

ROOT = Path(__file__).resolve().parent.parent

# `main.py --dry-run` at 9748c36d, before #187, with no .env: every key it
# printed. Since then the dry run adds the keys of NEW_KEYS.
PRE_187 = {
    "timezone": "America/Toronto",
    "active": "04:30–23:30",
    "min_target_posts": 3,
    "target_posts": 6,
    "max_profile_posts": 8,
    "replies": "unlimited",
    "quotes": 0,
    "reposts": 0,
    "slots": [
        ["05:00", "Priority: the AI update worth understanding this morning"],
        ["07:15", "A useful AI workflow with a concrete first step"],
        ["09:30", "Priority: an AI article or model update with a sharp consequence"],
        ["10:00", "Trending: the AI topic X is talking about right now, told from a trusted source"],
        ["11:45", "An AI concept explained through a clear example"],
        ["13:00", "Trending: the AI topic X is talking about right now, told from a trusted source"],
        ["14:00", "A model or tool update and what changes for its users"],
        ["15:00", "Trending: the AI topic X is talking about right now, told from a trusted source"],
        ["16:15", "Priority: an evidence-backed take on an AI tradeoff"],
        ["18:30", "A practical AI idea worth saving or sharing"],
        ["20:45", "Optional: an exceptional fresh AI update or unusually useful source"],
    ],
    "trend_slots": ["10:00", "13:00", "15:00"],
    "startup_post": "every start in waking hours, restarts included",
    "jobs": [
        "editorial_job", "direct_reply_job", "feed_sweep_job", "early_bird_job", "replyback_job",
        "debate_job", "mega_watch_job", "babysit_job", "notify_job", "engage_job", "followback_job",
        "follow_engagers_job", "like_job", "pin_job", "session_refresh_job", "follower_tracker_job",
        "reach_report_job",
    ],
}
# The values the code at 9748c36d used with no .env, for each setting that
# has a bound today: its os.environ.get defaults and config constants.
PRE_187_BOUNDED = {
    "MAX_ORIGINALS_PER_DAY": 8, "MIN_SECONDS_BETWEEN_POSTS": 1200, "POST_JITTER_SECONDS": 0,
    "MIN_SECONDS_BETWEEN_REPLIES": 8, "REPLY_JITTER_SECONDS": 7, "FOLLOW_TOTAL_CAP": 300,
    "MAX_FOLLOWS_PER_DAY": 20, "BAN_SHORT_TERM_PRICE_TARGETS": True,
    "DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY": 4, "DUP_JACCARD_THRESHOLD": 0.45,
    "DUP_CONTAINMENT_THRESHOLD": 0.6, "DUP_SHARED_BIGRAMS": 3, "DUP_TOPIC_WINDOW_HOURS": 24.0,
    "DUP_TOPIC_SHARED_WORDS": 3, "DUP_TEXT_WINDOW_HOURS": 48.0, "REPLY_MIN_CHARS": 25,
    "LIKE_BOT_PER_CYCLE": 10, "LIKE_BOT_DAILY_CAP": 500, "FOLLOWBACK_CAP": 8,
    "FOLLOW_ENGAGERS_PER_DAY": 10, "FOLLOW_ENGAGERS_PER_CYCLE": 2,
}
# #189 lists the providers and fallbacks it cannot run, #201 the bounded
# settings and the values brought back to a bound.
NEW_KEYS = {"unknown_llm_providers", "ignored_llm_fallbacks", "bounded_settings", "settings_warnings"}


@pytest.fixture
def dry_run(monkeypatch, tmp_path, unwalled, capsys):
    """`dry_run(environ)`: settings loaded afresh from an empty .env and
    `environ`, then `main.py --dry-run`, its JSON returned. The project
    root is a temporary folder; a model call fails the test."""
    import main
    from src.core import llm_client
    from tests.helpers import FakeAdapter

    shutil.copytree(ROOT / "accounts" / "example", Path(account.ACCOUNTS_DIR) / "example")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(state_store, "PROJECT_ROOT", str(project))
    monkeypatch.setattr(state_store, "LEGACY_DIR", str(project))
    monkeypatch.setattr(state_store, "root", unwalled["state_root"])
    calls = []
    monkeypatch.setattr(llm_client, "ADAPTERS", {name: FakeAdapter(name, calls) for name in llm_client.ADAPTERS})
    monkeypatch.setattr(settings, "_values", None)
    monkeypatch.setattr(settings, "_warnings", [])
    env_file = tmp_path / ".env"
    env_file.write_text("")

    def run(environ):
        settings.load(env_file=str(env_file), environ=dict(environ))
        monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
        main.main()
        assert calls == [], "the dry run called a model"
        return json.loads(capsys.readouterr().out)
    run.project = project
    return run


def test_theaishrink_keeps_the_jobs_and_ceilings_it_had_before_187(dry_run):
    shown = dry_run({})
    assert set(shown) == set(PRE_187) | NEW_KEYS
    assert {key: shown[key] for key in PRE_187} == PRE_187
    assert {name: bound["value"] for name, bound in shown["bounded_settings"].items()} == PRE_187_BOUNDED
    assert shown["settings_warnings"] == []


def test_the_example_account_lists_its_jobs_and_ceilings(dry_run):
    project = dry_run.project
    # theaishrink's state, unreadable: the example Account never reads it.
    theirs = project / "state" / "theaishrink"
    theirs.mkdir(parents=True)
    (theirs / "action_ledger.json").write_text("not json")

    shown = dry_run({"BOT_ACCOUNT": "example"})

    assert account.current().name == "example"
    assert settings.get("BOT_HANDLE") == "ExampleGardener"
    assert shown["jobs"] == PRE_187["jobs"]
    assert shown["trend_slots"] == ["10:00", "15:00"]
    assert [clock for clock, _ in shown["slots"]] == ["06:30", "09:00", "10:00", "12:30", "15:00",
                                                     "17:30", "19:45"]
    assert all("AI" not in angle.split() for _, angle in shown["slots"])
    # Its [limits] lowers the day's ceiling to 4, and the targets under it.
    assert (shown["min_target_posts"], shown["target_posts"], shown["max_profile_posts"]) == (3, 4, 4)
    bounded = {name: bound["value"] for name, bound in shown["bounded_settings"].items()}
    assert bounded == {**PRE_187_BOUNDED, "MAX_ORIGINALS_PER_DAY": 4, "MAX_FOLLOWS_PER_DAY": 5,
                       "LIKE_BOT_DAILY_CAP": 100}
    assert shown["settings_warnings"] == []
    assert state_store.root() == str(project / "state" / "example")
    assert os.listdir(project / "state") == ["theaishrink"]
    assert os.listdir(theirs) == ["action_ledger.json"]
    assert (theirs / "action_ledger.json").read_text() == "not json"


def test_the_example_account_has_no_relation_and_names_no_real_account(monkeypatch, unwalled):
    monkeypatch.setattr(account, "ACCOUNTS_DIR", unwalled["accounts_dir"])
    monkeypatch.setattr(account, "_loaded", {})
    example = account.load("example")
    assert example.relations.handles == {} and example.relations.default is None
    net = example.network
    assert all(getattr(net, field) == () for field in net.__dataclass_fields__)
    assert example.limits == {"MAX_ORIGINALS_PER_DAY": 4, "MAX_FOLLOWS_PER_DAY": 5,
                              "LIKE_BOT_DAILY_CAP": 100}
    assert example.niche.post.search("Sowing tomato seedlings in the greenhouse")
    assert not example.niche.post.search("OpenAI shipped a new reasoning model")
    assert not example.relevance.topic.search("OpenAI shipped a new reasoning model")


def test_the_example_operator_files_read(monkeypatch, settings_override):
    from src.guards import follow_policy, respect_list

    monkeypatch.setattr(account, "_loaded", {})
    shutil.copytree(ROOT / "accounts" / "example", Path(account.ACCOUNTS_DIR) / "example")
    settings_override(BOT_ACCOUNT="example")
    assert account.current().name == "example"
    assert respect_list.RESPECT.read() == {"handles": {}}
    wl = follow_policy.load_whitelist()
    assert wl["all"] == set()
    for name in ("whitelist.json", "respect_list.json", "following_baseline.json"):
        json.loads((ROOT / "accounts" / "example" / name).read_text())


def test_the_example_ceiling_holds_at_runtime(monkeypatch, settings_override):
    """The dry run's ceiling is the one the editorial job enforces."""
    from src.core import config
    from src.editorial import editorial_bot
    from src.guards import action_guard

    monkeypatch.setattr(account, "_loaded", {})
    shutil.copytree(ROOT / "accounts" / "example", Path(account.ACCOUNTS_DIR) / "example")
    settings_override(BOT_ACCOUNT="example", MAX_ORIGINALS_PER_DAY=4)
    monkeypatch.setattr(action_guard, "profile_count_today", lambda: 0)
    assert config.posts_ceiling() == 4 and config.post_targets() == (3, 4)
    now = editorial_bot._local()
    state = {"date": now.date().isoformat(), "published": [],
             "slots": {clock: "published" for clock in ("06:30", "09:00", "10:00", "12:30")}}
    assert editorial_bot._pending_refusal(state, now) == (
        "daily ceiling reached with pending submissions (4/4)")


def _words(text):
    return set(re.findall(r"\w+", text))


def test_the_example_prompts_name_its_domain(monkeypatch, settings_override):
    """The prompts and the trending searches take the Account's domain: the
    gardener's Originals, review, Trending posts and Replies never say AI."""
    from types import SimpleNamespace
    from src.core import llm_client
    from src.editorial import editorial_bot, trending
    from src.replies import direct_reply, reply_generator
    from src.x import scraper

    monkeypatch.setattr(account, "_loaded", {})
    shutil.copytree(ROOT / "accounts" / "example", Path(account.ACCOUNTS_DIR) / "example")
    settings_override(BOT_ACCOUNT="example")
    prompts = []
    monkeypatch.setattr(editorial_bot, "_json_call",
                        lambda prompt, label, profile: prompts.append(prompt) or {"reason": "no"})
    monkeypatch.setattr(reply_generator, "run_llm", lambda prompt, model, **kw: prompts.append(prompt) or
                        SimpleNamespace(status=llm_client.LLMStatus.ANSWERED, returncode=0,
                                        stdout="SKIP", stderr="", provider="p", model="m"))
    body = "Mulch keeps the soil moist through a dry summer week in the vegetable patch. " * 6
    source = dict(id="0", title="Mulch", url="https://www.rhs.org.uk/mulch", publisher="RHS",
                  published_at="", kind="news", body=body)
    posts = [dict(text="Sowing tomato seedlings", likes=90, views=900, age_minutes=30,
                  likes_per_minute=3.0)] * 3
    trend = next(slot for slot in editorial_bot.slots() if slot.trend)
    editorial_bot.draft_post(trend, [source], [], "", posts)
    draft = dict(source_id="0", text="Mulch keeps the soil moist through a dry week, so lay it "
                 "after rain and water less often in the vegetable patch.",
                 angle="a", takeaway="t", evidence_ids=["0"])
    editorial_bot.review_draft(draft, [source], [], trending=posts)
    reply_generator.generate(direct_reply.reply_call("someone"), author="someone",
                             text="My raised bed tomatoes split after the rain")
    assert len(prompts) == 3
    draft_prompt, review_prompt, reply_prompt = prompts
    assert "Write ONE original gardening post" in draft_prompt
    assert "fastest-rising gardening posts" in draft_prompt
    assert "strict independent gardening editor" in review_prompt
    assert "stable gardening knowledge" in reply_prompt
    assert all("AI" not in _words(prompt) for prompt in prompts)

    queries = []
    monkeypatch.setattr(scraper, "scrape_x_search", lambda query, **kw: queries.append(query) or [])
    trending.collect_trending_posts(trend)
    assert queries == list(account.current().searches.trending)
    assert all("AI" not in _words(query) for query in queries)
