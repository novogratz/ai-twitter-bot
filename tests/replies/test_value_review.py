"""Useful content must be independently reviewed before any browser write."""
import json
from datetime import timedelta

import pytest

from src.core import humanizer
from src.core.llm_client import LLMResult
from src.guards import active_hours, reply_admission, reply_budget, replied_store, reply_value
from src.replies import reply_pipeline as rp
from src.x import twitter_client as tc
from tests.helpers import clock, fresh
from tests.replies.fakes import EXHAUSTED, logged
from tests.replies.test_reply_pipeline import job, run

PARENT = "Our LLM benchmark improved after prompt tuning. How should we check for overfitting?"
REPLY = "Keep a held-out set untouched during prompt tuning; compare gains there before trusting the benchmark lift."


def decision(**changes):
    return {**{key: True for key in reply_value.FLAGS}, "kind": "practical_test",
            "parent_anchor": "How should we check for overfitting?", "contribution": REPLY,
            "reason": "A held-out comparison tests whether tuning gains generalize.", **changes}


@pytest.fixture
def reviewer(monkeypatch):
    calls = []
    def review(prompt, model, **options):
        import threading
        assert tc.safari._safari_lock._lock._owner != threading.get_ident(), "model review held Safari"
        calls.append((prompt, options))
        return LLMResult(0, json.dumps(decision()), "")
    monkeypatch.setattr(reply_value, "run_llm", review)
    return calls


def test_review_binds_exact_reply_and_actual_parent(reviewer):
    url = fresh("researcher")
    approval, _ = reply_value.review(url, PARENT, REPLY)
    assert approval.matches_reply(url, REPLY)
    assert not approval.matches_reply(fresh("other"), REPLY)
    assert not approval.matches_reply(url, REPLY + " Amazing!")
    assert approval.matches_parent(PARENT.replace(". ", ".\n"))
    assert not approval.matches_parent(PARENT.replace("improved", "collapsed"))
    assert reviewer[0][1]["allowed_tools"] == ()


@pytest.mark.parametrize("change", [
    {"adds_value": False}, {"substantive_parent": False}, {"grounded": False},
    {"distinct_from_recent": False}, {"specific_to_parent": False}, {"natural": False}, {"adds_value": "true"},
    {"kind": "none"}, {"parent_anchor": "fabricated source evidence"},
    {"contribution": "I ran this experiment myself"}, {"parent_anchor": "   "},
])
def test_failed_flags_or_invented_evidence_never_approve(monkeypatch, change):
    monkeypatch.setattr(reply_value, "run_llm", lambda *a, **kw: LLMResult(0, json.dumps(decision(**change)), ""))
    assert reply_value.review(fresh("researcher"), PARENT, REPLY)[0] is None


@pytest.mark.parametrize("result", [LLMResult(0, "{}", ""), LLMResult(0, "yes", ""),
                                   LLMResult(124, "", "timeout"), EXHAUSTED])
def test_unavailable_or_invalid_review_holds_without_fallback(monkeypatch, result):
    monkeypatch.setattr(reply_value, "run_llm", lambda *a, **kw: result)
    assert reply_value.review(fresh("researcher"), PARENT, REPLY)[0] is None


def test_pipeline_sends_and_logs_only_reviewed_bytes(settings_override, reviewer, chokepoint, monkeypatch):
    settings_override(REPLY_DISCUSSIONS_ONLY=True, HUMAN_TYPO_HANDLES="researcher")
    monkeypatch.setattr(humanizer, "casualize", lambda text: pytest.fail("random human texture"))
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: pytest.fail("manufactured typo"))
    url = fresh("researcher")
    assert run(job(), [rp.Candidate(url, PARENT, "test", reply=REPLY)]) == 1
    sent = chokepoint.calls[0]
    assert sent.value_review.matches_reply(url, sent.text)
    assert sent.text == logged()[0].text == REPLY
    assert json.loads(reviewer[0][0].split("INPUT_JSON:\n")[1])["reply"] == sent.text


def test_rejected_value_never_calls_browser_or_claims_parent(settings_override, monkeypatch, chokepoint):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    monkeypatch.setattr(reply_value, "run_llm", lambda *a, **kw: LLMResult(0, json.dumps(
        decision(adds_value=False, contribution="The real test is production.")), ""))
    url = fresh("researcher")
    assert run(job(), [rp.Candidate(url, PARENT, "test", reply="The real test is production.")]) == 0
    assert not chokepoint.calls and not logged()
    assert url not in replied_store.load_replied() and reply_budget.used_today() == 0


def test_parent_expiring_during_review_never_reaches_browser(settings_override, monkeypatch, chokepoint):
    settings_override(REPLY_DISCUSSIONS_ONLY=True, REPLY_MAX_AGE_SECONDS=1800)
    now = active_hours.now_local()
    url = fresh("researcher")
    def slow_review(*a, **kw):
        clock(monkeypatch, now + timedelta(minutes=31))
        return LLMResult(0, json.dumps(decision()), "")
    monkeypatch.setattr(reply_value, "run_llm", slow_review)
    assert run(job(), [rp.Candidate(url, PARENT, "test", reply=REPLY)]) == 0
    assert not chokepoint.calls and url not in replied_store.load_replied()


def test_direct_caller_without_review_refused_before_browser(settings_override):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    url = fresh("researcher")
    assert tc.reply_to_tweet(url, REPLY) is tc.WriteOutcome.REFUSED
    assert url not in replied_store.load_replied() and reply_budget.used_today() == 0


def test_final_admission_rejects_changed_wording(settings_override, reviewer):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    url = fresh("researcher")
    approval, _ = reply_value.review(url, PARENT, REPLY)
    assert reply_admission.judge_reply(url, REPLY, value_review=approval)
    assert not reply_admission.judge_reply(url, REPLY + " Amazing!", value_review=approval)


def test_previous_policy_approval_and_missing_specificity_check_cannot_publish(settings_override, reviewer, monkeypatch):
    from dataclasses import replace
    settings_override(REPLY_DISCUSSIONS_ONLY=True, MAX_REPLIES_PER_DAY=1400)
    url = fresh("researcher")
    approval, _ = reply_value.review(url, PARENT, REPLY)
    old = replace(approval, policy="substantive-and-creative-reply-v1")
    assert not old.matches_parent(PARENT)
    assert not reply_admission.judge_reply(url, REPLY, value_review=old)
    old_decision = decision()
    del old_decision["specific_to_parent"]
    monkeypatch.setattr(reply_value, "run_llm", lambda *a, **kw: LLMResult(0, json.dumps(old_decision), ""))
    assert reply_value.review(url, PARENT, REPLY)[0] is None


def test_live_parent_must_match_review_before_like_or_composition(settings_override, reviewer, monkeypatch):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    url = fresh("researcher")
    approval, _ = reply_value.review(url, PARENT, REPLY)
    def observed(text):
        monkeypatch.setattr(tc.safari, "_run_js", lambda *a, **kw: json.dumps(
            {"url": url, "text": text, "clicked": False}))
    observed(PARENT)
    assert tc._reply_target(url, value_review=approval)
    observed(PARENT.replace("improved", "collapsed"))
    assert not tc._reply_target(url, value_review=approval)
    assert not tc._reply_target(url, click=True, value_review=approval)


def test_generation_retains_qualifying_context_after_short_preview(settings_override, llm, reviewer, chokepoint):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    text = PARENT + " " + "Context about the experiment. " * 10 + "Our held-out set was also used during tuning."
    llm.default = REPLY
    run(job(), [rp.Candidate(fresh("researcher"), text, "test")])
    assert "Our held-out set was also used during tuning." in llm.prompts[0]


@pytest.mark.parametrize("parent,reply,anchor", [
    ("My AI satire: two robots promise to replace the writer, then argue about who owns the deadline.",
     "They automated the writing and kept the office politics.", "argue about who owns the deadline"),
    ("My AI short film concept: a city runs on borrowed time; every clock stops when the courier finally sleeps.",
     "Even the clocks need her to take a nap. That's a wonderfully unfair job.",
     "every clock stops when the courier finally sleeps"),
])
@pytest.mark.parametrize("failed_flag", ["substantive_parent", "no_unseen_claims", "specific_to_parent"])
def test_standout_creative_reaction_still_needs_quality_evidence_and_specificity(
        settings_override, monkeypatch, chokepoint, parent, reply, anchor, failed_flag):
    settings_override(REPLY_DISCUSSIONS_ONLY=True, MAX_REPLIES_PER_DAY=1400,
                      REPLY_DAILY_TARGET_MIN=1400, REPLY_DAILY_TARGET_MAX=1400)
    result = decision(kind="creative_reaction", parent_anchor=anchor,
                      contribution=reply, reason="A playful extension of the supplied satire concept.")
    monkeypatch.setattr(reply_value, "run_llm", lambda *a, **kw: LLMResult(0, json.dumps(result), ""))
    assert run(job(), [rp.Candidate(fresh("artist"), parent, "test", reply=reply)]) == 1
    result[failed_flag] = False
    assert run(job(), [rp.Candidate(fresh("artist", n=1), parent, "test", reply=reply)]) == 0
    assert len(chokepoint.calls) == 1


def test_quote_context_must_also_match_the_review(settings_override, monkeypatch):
    from src.replies.reply_source import source_text
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    url = fresh("researcher")
    source = {"text": PARENT, "quoted_text": "AI benchmark methodology and dataset split."}
    approval = reply_value.Approval(url, reply_value._digest(reply_value._source(source_text(source))),
                                    reply_value._digest(REPLY))
    monkeypatch.setattr(tc.safari, "_run_js", lambda *a, **kw: json.dumps(
        {"url": url, **source, "clicked": False}))
    assert tc._reply_target(url, value_review=approval)
    source["quoted_text"] = "A different dataset and result."
    assert not tc._reply_target(url, value_review=approval)
