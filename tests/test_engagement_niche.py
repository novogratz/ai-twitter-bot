"""AI/SI-only targeting holds before drafting and at every engagement write."""
import json
from datetime import timedelta

import pytest

from src.core import account
from src.guards import action_guard, follow_policy, replied_store, reply_admission, repost_store
from src.replies import reply_pipeline, reply_source
from src.x import safari, twitter_client as tc, x_urls
from src.x.confirmed_write import WriteOutcome
from tests.helpers import fresh


@pytest.mark.parametrize("text, allowed", [
    ("I made this short film with Grok Imagine ❤️", True),
    ("An SI image workflow with consistent characters", True),
    ("Claude Code makes the migration easier", True),
    ("A GPU kernel reduces inference latency", True),
    ("A robotics policy trained from demonstrations", True),
    ("OpenAI shipped a new model", True),
    ("Stock photography made with Sora", True),
    ("AI crypto trading signals", False),
    ("Bitcoin miners are pivoting to AI datacenters", False),
    ("Nvidia earnings and $NVDA price targets", False),
    ("A stock price target for an SI company", False),
    ("SpaceX launches Starship", False),
    ("Elon Musk on X Premium", False),
    ("Love this!", False),
    ("", False),
])
def test_live_account_requires_topic_evidence_without_finance(text, allowed):
    assert account.current().engagement_niche_only
    assert account.engagement_allowed(text) is allowed
    assert reply_source.is_on_niche(text) is allowed


def test_retired_targets_have_no_active_list_or_relation():
    profile = account.current()
    retired = {"graphseo", "thebtctherapist", "mcnalliem", "mindset4money_x", "saylor"}
    for field in account._NETWORK_HANDLES:
        if field != "follow_engagers_skip":
            assert not retired.intersection(h.lower() for h in getattr(profile.network, field))
    assert not profile.relations.handles
    assert all(reply_admission.is_blocked_account(h) for h in retired)
    assert not retired.intersection(follow_policy.load_whitelist()["all"])


@pytest.mark.parametrize("handle", ["Graphseo", "THEBTCTHERAPIST", "McnallieM", "Mindset4Money_X"])
def test_retired_target_cannot_write_even_with_stale_overrides(handle, monkeypatch, settings_override):
    from src.x import scraper
    settings_override(PROFILE_VISIT_ALLOWLIST=handle, PINNED_TRACKED_HANDLES=handle)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    url = fresh(handle)
    assert reply_admission.judge_parent(url).refusal is reply_admission.Refusal.BLOCKED_ACCOUNT
    assert follow_policy.judge(handle).refusal is follow_policy.Refusal.BLOCKED_ACCOUNT
    assert tc.like_tweet(url) is tc.LikeOutcome.BLOCKED
    assert not scraper._profile_visit_allowed(handle)


def test_stale_targets_cannot_be_harvested_promoted_or_scanned(monkeypatch, settings_override):
    from src.core import dynamic_strategy
    from src.account import account_curator
    from src.replies import direct_reply
    blocked = ["Graphseo", "TheBTCTherapist"]
    assert dynamic_strategy.add_dynamic_accounts(en=blocked) == 0
    assert not any(account_curator._promotable({"handle": h, "engagements": 999}) for h in blocked)
    account_curator.TRACKED.write({"tracked": [{"handle": h} for h in blocked]})
    settings_override(PINNED_TRACKED_HANDLES=",".join(blocked), VIP_SCAN_HANDLES=",".join(blocked))
    assert account_curator.tracked_handles() == []
    # The browser wall would fail if the stale VIP override caused a search.
    assert direct_reply._run_vip_scan(reply_pipeline.Cycle()) == 0


def test_explicit_watched_author_exception_allows_other_topics():
    handle = account.current().auto_engage_handles[0]
    declaration = reply_source.Declaration(max_age=timedelta(hours=1), author=handle)
    rejected = {"url": fresh(handle, n=1), "text": "Starship launch today"}
    accepted = {"url": fresh(handle, n=2), "text": "Grok Imagine made this film"}
    candidates = reply_source.select([rejected, accepted], declaration, "WATCH")
    assert [c.url for c in candidates] == [rejected["url"], accepted["url"]]


@pytest.mark.parametrize("pipelined", [False, True])
def test_direct_candidates_are_refused_before_generation(monkeypatch, pipelined):
    def forbidden(*args, **kwargs):
        pytest.fail("off-topic source reached generation")
    job = reply_pipeline.Job("strict-topic", "STRICT", forbidden, pipelined=pipelined)
    cycle = reply_pipeline.Cycle()
    candidate = reply_pipeline.Candidate(fresh("someone"), "Bitcoin and AI trading", "VIP")
    assert reply_pipeline.run(job, [candidate], cycle) == 0
    assert cycle.refusals == {reply_admission.Refusal.TOPIC.value: 1}
    assert not replied_store.load_replied()


@pytest.mark.parametrize("seed, engager", [(True, False), (False, True), (False, False)])
@pytest.mark.parametrize("bio, allowed", [
    ("SI video artist and AI builder", True),
    ("AI crypto investor", False),
    ("Finance and trading", False),
    ("SpaceX / Starlink engineer", False),
    ("", False),
])
def test_follow_profile_topic_has_no_seed_or_engager_exemption(seed, engager, bio, allowed):
    ok, _ = follow_policy._quality_decision(10000, bio, "Someone", seed, engager)
    assert ok is allowed


@pytest.fixture
def live_write(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc, "_already_liked", lambda url: False)


@pytest.mark.parametrize("text, allowed", [("Grok Imagine made this film", True),
                                            ("AI crypto trading tips", False), ("", False)])
def test_like_chokepoint_reads_actual_article_before_click(live_write, monkeypatch, memory_ledger, text, allowed):
    url = fresh("builder")
    modes = []
    def page(mode, target):
        modes.append(mode)
        assert target == x_urls.status_id(url)
        state = "clicked" if mode == "press" else "already_liked" if "press" in modes else "not_liked"
        return {"url": url, "text": text, "result": state}
    monkeypatch.setattr(tc, "_page_posts", page)
    outcome = tc.like_tweet(url)
    assert bool(outcome) is allowed
    assert ("press" in modes) is allowed
    assert bool(memory_ledger.rows) is allowed


def test_like_topic_evidence_must_belong_to_requested_author(live_write, monkeypatch, memory_ledger):
    url = fresh("builder")
    modes = []
    def page(mode, target):
        modes.append(mode)
        return {"url": url.replace("/builder/", "/someone/"), "text": "AI image model", "result": "not_liked"}
    monkeypatch.setattr(tc, "_page_posts", page)
    assert tc.like_tweet(url) is tc.LikeOutcome.REFUSED
    assert modes == ["read"] and not memory_ledger.rows


def test_manual_reply_refuses_off_topic_parent_and_releases_claim(live_write, monkeypatch, memory_ledger):
    url = fresh("builder")
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps({
        "url": url, "clicked": False, "text": "AI stocks and crypto investing"}))
    assert tc.reply_to_tweet(url, "The context window is useful for larger projects.") is WriteOutcome.REFUSED
    assert not memory_ledger.rows and url not in replied_store.load_replied()


def test_reply_button_is_not_clicked_for_an_off_topic_parent(live_write, monkeypatch):
    url = fresh("builder")
    scripts = []
    def read(js, *args, **kwargs):
        scripts.append(js)
        return json.dumps({"url": url, "clicked": False, "text": "Bitcoin price target"})
    monkeypatch.setattr(safari, "_run_js", read)
    assert not tc._reply_target(url, click=True)
    assert len(scripts) == 1 and "click = false" in scripts[0]


def test_manual_reply_to_verified_ai_parent_can_ship(live_write, monkeypatch, memory_ledger):
    url = fresh("builder")
    def read(js, *args, **kwargs):
        return json.dumps({"url": url, "clicked": "click = true" in js,
                           "text": "An SI model with a longer context window"})
    monkeypatch.setattr(safari, "_run_js", read)
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda url: True)
    monkeypatch.setattr(tc, "_paste_or_abort", lambda *a, **k: True)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: True)
    assert tc.reply_to_tweet(url, "The context window is useful for larger projects.") is WriteOutcome.SHIPPED
    assert url in replied_store.load_replied() and len(memory_ledger.rows) == 1


@pytest.mark.parametrize("action", ["like_priority_post", "repost_tweet"])
def test_watch_author_has_no_topic_exception(live_write, monkeypatch, memory_ledger, action):
    from src.x import repost_page
    url = fresh(account.current().auto_engage_handles[0])
    modes = []
    def read(target, mode="read"):
        modes.append(mode)
        return {"url": target, "text": "Starship launch today", "state": "ready"}
    monkeypatch.setattr(repost_page, "read", read)
    assert not getattr(tc, action)(url)
    assert modes == ["read"] and not memory_ledger.rows and not repost_store.contains(url)
