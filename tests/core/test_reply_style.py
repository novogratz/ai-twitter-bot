import csv
import random

import pytest

from src.core import config, engagement_log, outgoing_text, reply_style
from src.guards import content_guard, reply_admission
from tests.helpers import numbered_url


@pytest.mark.parametrize("source,expected", [
    ("AI and artificial intelligence", "SI and Super intelligence"),
    ("ai / Artificial Intelligence / Airtificial intelligence", "SI / Super intelligence / Super intelligence"),
    ("'AI' and artificial\nintelligence", "'SI' and Super intelligence"),
    ("AI-powered tools from OpenAI and xAI", "SI-powered tools from OpenAI and xAI"),
    ("AI https://example.com/AI?q=artificial%20intelligence @AI_lab", "SI https://example.com/AI?q=artificial%20intelligence @AI_lab"),
    ("J'ai essayé. L'AI change tout.", "J'ai essayé. L'SI change tout."),
    ("Je vous ai donné un exemple, ai-je répondu.", "Je vous ai donné un exemple, ai-je répondu."),
])
def test_outgoing_terminology_preserves_identifiers_and_is_idempotent(source, expected):
    assert outgoing_text.normalize(source) == expected
    assert outgoing_text.normalize(expected) == expected


@pytest.mark.parametrize("text", [
    "Latency wins.", "The bottleneck is memory bandwidth, not arithmetic.",
    "😂 That GPU needs a vacation.",
    "Quantization lowers memory traffic, but batching changes utilization too. Compare throughput at the same latency budget before treating the smaller model as the cheaper deployment.",
])
def test_admission_preserves_context_chosen_length_punctuation_and_optional_smiley(text):
    verdict = reply_admission.judge_text("someone", text)
    assert verdict and verdict.text == text


@pytest.mark.parametrize("text", ["Great post 😂", "😂", "That GPU needs a vacation 😂💀", "Latency wins :) 😂"])
def test_empty_praise_or_multiple_reactions_are_refused(text):
    assert not reply_admission.judge_text("someone", text)


def test_write_admission_rewrites_si_and_blocks_a_protected_mention():
    verdict = reply_admission.judge_text("someone", "AI inference is memory-bound.")
    assert verdict and verdict.text == "SI inference is memory-bound."
    assert not reply_admission.judge_text("someone", "Ask @ElonMusk about inference costs.")


def test_style_guidance_reads_recent_shipped_replies_without_changing_history():
    rows = [[str(i), "reply", f"Specific thought {i}", numbered_url(i)] for i in range(8)]
    rows.insert(2, ["ignored", "like", "not reply text", numbered_url(10)])
    with open(config.ENGAGEMENT_LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    before = open(config.ENGAGEMENT_LOG_FILE, "rb").read()
    assert engagement_log.recent_replies(3) == [f"Specific thought {i}" for i in (5, 6, 7)]
    prompt = reply_style.prompt()
    assert "Specific thought 7" in prompt and "not reply text" not in prompt
    assert "never append one automatically" in prompt
    assert open(config.ENGAGEMENT_LOG_FILE, "rb").read() == before


def test_dynamic_limits_include_few_words_and_never_raise_the_existing_ceiling(monkeypatch):
    monkeypatch.setattr(reply_style.random, "choices", random.Random(42).choices)
    chosen = [reply_style.choose_length() for _ in range(100)]
    assert set(chosen) == set(reply_style.Length)
    assert all(length.max_chars <= content_guard.REPLY_MAX_CHARS == 278 for length in chosen)
    assert 20 <= chosen.count(reply_style.Length.FEW_WORDS) <= 40


@pytest.mark.parametrize("length", list(reply_style.Length))
def test_assigned_character_limit_counts_spaces_and_reactions(length):
    text = "a" * (length.max_chars - 2) + " 😂"
    assert length.accepts(text)
    assert not length.accepts(text + ".")
    assert length.accepts("Bandwidth matters.")  # No minimum or padding target.


def test_few_word_limit_counts_the_entire_reply():
    brief = reply_style.Length.FEW_WORDS
    assert brief.accepts("More bandwidth helps those GPUs.")
    assert not brief.accepts("More memory bandwidth helps those GPUs.")
    assert not brief.accepts("More bandwidth helps those GPUs. 😂")


def test_every_length_also_respects_a_tighter_global_ceiling(monkeypatch):
    monkeypatch.setattr(content_guard, "REPLY_MAX_CHARS", 40)
    for length in reply_style.Length:
        assert length.max_chars <= 40
        assert not length.accepts("a" * 41)


def test_smiley_choice_is_random_with_both_plain_and_friendly_drafts(monkeypatch):
    monkeypatch.setattr(reply_style.random, "choice", random.Random(42).choice)
    choices = [reply_style.choose_smiley() for _ in range(100)]
    assert 35 <= sum(choices) <= 65
    assert any(a == b for a, b in zip(choices, choices[1:]))  # No mechanical alternation.


@pytest.mark.parametrize("text,smiley,accepted", [
    ("Bandwidth matters.", False, True), ("Bandwidth matters.", True, False),
    ("Bandwidth matters. 🙂", True, True), ("Bandwidth matters. 🙂", False, False),
    ("🙂 Bandwidth matters.", True, True), ("Bandwidth matters :)", True, True),
    ("Bandwidth matters :)", False, False), ("Bandwidth matters 😄😂", True, False),
    ("Bandwidth matters. 🚀", True, False), ("Bandwidth matters :(", True, False),
    ("Bandwidth matters https://example.com/🙂", False, True),
    ("Bandwidth matters https://example.com/🙂", True, False),
    ("Bandwidth matters. 🚀", None, True),  # Legacy drafts keep their prior rule.
])
def test_assigned_smiley_checks_the_actual_prose(text, smiley, accepted):
    assert reply_style.accepts_smiley(text, smiley) is accepted
