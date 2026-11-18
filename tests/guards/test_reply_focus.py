"""Discovery hints guide review without certifying evidence or creative quality."""
import pytest

from src.core.reply_context import source_text
from src.guards import reply_focus


@pytest.mark.parametrize("text,priority", [
    ("Why does our LLM retrieval miss exact document names after chunking?", 0),
    ("We compared LLM inference batching at the same latency budget and measured throughput.", 0),
    ("My SI short film concept: a robot librarian lends people the memories they forgot.", 0),
    ("New AI inference benchmark results from the latest model release today.", 1),
    ("Reply YES for the guide to this LLM inference workflow.", 2),
    ("This is incredible!", 2),
])
def test_contextual_leads_precede_keywords_and_bait(settings_override, text, priority):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    assert reply_focus.discovery_priority(text) == priority


def test_quoted_research_cannot_turn_a_thin_wrapper_into_a_contribution(settings_override):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    text = source_text({"text": "This changes everything!", "quoted_text":
                        "We tested LLM retrieval on a held-out dataset. Why does recall drop after chunking?"})
    assert reply_focus.parent_refusal(text)
    assert reply_focus.discovery_priority(text) == 2


def test_a_substantive_outer_post_keeps_attributed_quote_context(settings_override):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    text = source_text({"text": "Why does this LLM retrieval experiment use the same documents for tuning and evaluation?",
                        "quoted_text": "Our measured recall increased after prompt tuning."})
    assert not reply_focus.parent_refusal(text)
    assert reply_focus.discovery_priority(text) == 0
    assert "Our measured recall" in text


def test_other_accounts_keep_their_existing_source_screen(settings_override):
    settings_override(REPLY_DISCUSSIONS_ONLY=False)
    assert not reply_focus.parent_refusal("This is incredible!")
    assert reply_focus.discovery_priority("This is incredible!") == 1
