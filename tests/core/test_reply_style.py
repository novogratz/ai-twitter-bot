import csv

import pytest

from src.core import config, engagement_log, outgoing_text, reply_style
from src.guards import reply_admission
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
    verdict = reply_admission.judge_reply(numbered_url(900), text)
    assert verdict and verdict.text == text


@pytest.mark.parametrize("text", ["Great post 😂", "😂", "That GPU needs a vacation 😂💀", "Latency wins :) 😂"])
def test_empty_praise_or_multiple_reactions_are_refused(text):
    assert not reply_admission.judge_reply(numbered_url(901), text)


def test_write_admission_rewrites_si_and_blocks_a_protected_mention():
    verdict = reply_admission.judge_reply(numbered_url(902), "AI inference is memory-bound.")
    assert verdict and verdict.text == "SI inference is memory-bound."
    assert not reply_admission.judge_reply(numbered_url(903), "Ask @ElonMusk about inference costs.")


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
