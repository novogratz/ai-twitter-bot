"""The live Account answers an original once, never a conversation continuation."""
from datetime import timedelta

import pytest

from src.guards.reply_admission import Refusal, judge_parent
from src.replies import reply_pipeline as rp, reply_source
from tests.helpers import fresh


@pytest.mark.parametrize("pipelined", [False, True])
@pytest.mark.parametrize("options,text,debate", [
    ({"is_reply": True}, "A reply without a visible mention", False),
    ({"context": "Our own original"}, "An answer to our original", False),
    ({}, "@someone a comment", False),
    ({}, "Another turn in a debate", True),
])
def test_continuations_are_refused_before_generation_and_write(
        chokepoint, options, text, debate, pipelined):
    candidate = rp.Candidate(fresh("someone"), text, "TEST", **options)
    job = rp.Job("single_reply", "TEST", reply_call=lambda _: pytest.fail("generated a follow-up"),
                 debate_turn=debate, pipelined=pipelined)
    cycle = rp.Cycle()
    assert rp.run(job, [candidate], cycle) == 0
    assert cycle.refusals == {Refusal.CONVERSATION.value: 1}
    assert not chokepoint.calls


@pytest.mark.parametrize("metadata", [
    {"is_reply": True}, {"in_reply_to_status_id": "12"},
    {"in_reply_to_tweet_id": "12"}, {"conversation_id": "12"},
])
def test_source_cannot_opt_out_of_the_accounts_standalone_policy(metadata):
    posts = [{"url": fresh("someone"), "text": "A nested SI observation", **metadata}]
    assert reply_source.select(posts, reply_source.Declaration(max_age=timedelta(hours=1)), "TEST") == []


def test_manual_follow_up_jobs_stop_before_reads_or_side_effects(monkeypatch, settings_override):
    from src.replies import debate_bot, first_hour_babysitter, notify_bot
    from src.x import scraper

    def forbidden(*args, **kwargs):
        pytest.fail("a disabled conversation job did work")

    settings_override(ENABLE_DEBATES=True, DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY=4)
    monkeypatch.setattr(scraper, "scrape_mentions", forbidden)
    monkeypatch.setattr(notify_bot, "scrape_own_tweet_and_replies", forbidden)
    monkeypatch.setattr(notify_bot, "_reciprocate_engagers", forbidden)
    monkeypatch.setattr(first_hour_babysitter, "_latest_post_age_minutes", forbidden)
    debate_bot.run_debate_cycle()
    notify_bot.run_replyback_cycle()
    first_hour_babysitter.run_babysit_cycle()


def test_separate_originals_from_the_same_author_are_still_eligible():
    from src.guards import replied_store
    first, second = fresh("someone", n=1), fresh("someone", n=2)
    replied_store.claim(first)
    assert judge_parent(first).refusal is Refusal.ALREADY_REPLIED
    assert judge_parent(second)
