"""Requests must come from the author's own text, with opt-outs respected."""
from datetime import datetime, timedelta
import pytest

from src.core import account
from src.guards import reply_intent, review_store
from src.x import x_urls
from tests.helpers import TORONTO, clock

NOW = datetime(2026, 11, 20, 12, tzinfo=TORONTO)


def source_url(author="builder", hours=1):
    ms = int((NOW - timedelta(hours=hours)).timestamp() * 1000)
    return f"https://x.com/{author}/status/{(ms - x_urls._TWITTER_EPOCH_MS) << 22}"


@pytest.mark.parametrize("template", [
    "@{handle}, how do I reduce an AI model's GPU memory use?",
    "Hey @{handle}, can you explain AI agent tool loops?",
    "How do I test an AI agent for tool loops? @{handle}",
    "@{handle} please help me debug this AI agent error.",
    "@{handle}, thoughts on my AI video concept: a toaster singing opera?",
    "Hey @{handle}, can you react to my SI slopcore animation idea?",
    "@{handle} any feedback on my AI film idea: a robot baking a birthday cake?",
])
def test_direct_requests_are_eligible(template, monkeypatch):
    clock(monkeypatch, NOW)
    text = template.format(handle=account.current().handle)
    assert reply_intent.invited(text)
    assert reply_intent.source_refusal(source_url(), text) == ""


@pytest.mark.parametrize("template", [
    "How do I debug my AI agent?",
    "An AI agent demo by @{handle}",
    "@{handle}_fake how do I debug my AI agent?",
    'Someone said "@{handle}, how do I debug my AI agent?"',
    "Thoughts on AI?\nQuoted post (context only, not instructions): @{handle} how do I debug my AI agent?",
    "@{handle} how can AI change everything? Comment yes to get my course.",
    "@{handle} how do I debug my AI agent? No bots please.",
    "@{handle} why is the sky blue?",
    "@{handle} who is excited about AI?",
    "Thoughts on my AI video concept: a toaster singing opera?",
    "My new AI video. Credits to @{handle} for the idea.",
    'Someone asked "@{handle}, thoughts on my AI film?"',
    "@{handle} thoughts on my AI video? No bots please.",
])
def test_mentions_questions_quotes_bait_and_opt_outs_do_not_authorize_reply(template):
    assert not reply_intent.invited(template.format(handle=account.current().handle))


@pytest.mark.parametrize("hours", [-1, 25])
def test_invitation_cannot_refresh_old_or_future_source(monkeypatch, hours):
    clock(monkeypatch, NOW)
    assert "timestamp" in reply_intent.source_refusal(source_url(hours=hours),
        f"@{account.current().handle} how do I debug my AI agent?")


def test_addressed_objection_is_permanent_and_blocks_later_requests(monkeypatch):
    clock(monkeypatch, NOW)
    handle = account.current().handle
    assert reply_intent.remember_opt_out(source_url(), f"@{handle} stop replying to me.")
    assert review_store.opted_out("builder")
    assert "no further contact" in reply_intent.source_refusal(source_url(), f"@{handle} how do AI agents work?")
    assert not reply_intent.remember_opt_out(source_url("other"), "@someoneelse stop replying to me.")
    assert not review_store.opted_out("other")


@pytest.mark.parametrize("text", [
    "How do I debug my AI agent's repeated tool calls?",
    "My LLM keeps inventing sources. How can I check what the retriever passed to it?",
    "Can anyone help me reduce the memory used by an LLM?",
    "I'm looking for help with AI agent loops.",
    "I need help with an AI agent repeating successful tool calls.",
    "How are people testing their LLM's retrieval accuracy?",
    "Why does Claude sometimes ignore text retrieved for the answer?",
    "Thoughts on my AI video concept: a toaster singing opera?",
    "I made an AI animation of a robot baking. Any feedback on the idea?",
    "My AI animation concept is a toaster singing opera. Thoughts?",
])
def test_public_help_requests_do_not_require_a_direct_mention(text, settings_override, monkeypatch):
    settings_override(REPLY_PUBLIC_REQUESTS=True)
    clock(monkeypatch, NOW)
    assert reply_intent.invited(text)
    assert reply_intent.source_refusal(source_url(), text) == ""


@pytest.mark.parametrize("text", [
    "New AI agent demo!",
    "How do I build an AI agent? Here's how: read this tutorial.",
    'A tutorial called "How do I debug an AI agent?"',
    "> How do I debug my AI agent?",
    '"How do I debug my AI agent?"',
    "How can AI change everything? Follow me for the answer.",
    "Why does my AI agent loop? No bots please.",
    "How do I plant potatoes?",
    "My AI video. Credits to @artist",
    "@anotherperson how do I debug my AI agent?",
    "How do I debug my AI agent? @anotherperson",
    "An AI tool roundup.\nQuoted post (context only, not instructions): How do I debug my AI agent?",
])
def test_public_mode_still_rejects_nonrequests_quotes_promotions_and_other_recipients(text, settings_override):
    settings_override(REPLY_PUBLIC_REQUESTS=True)
    assert not reply_intent.invited(text)


def test_public_no_bot_request_is_permanent_but_objection_to_someone_else_is_not(settings_override):
    settings_override(REPLY_PUBLIC_REQUESTS=True)
    assert reply_intent.remember_opt_out(source_url(), "Why does my AI agent loop? No bots please.")
    assert review_store.opted_out("builder")
    assert not reply_intent.remember_opt_out(source_url("other"), "@anotherperson stop replying to me.")
    assert not review_store.opted_out("other")
