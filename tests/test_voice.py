"""The live Voice carries the current selective, honest expert persona."""
from pathlib import Path

import pytest

ACCOUNT = Path(__file__).resolve().parent.parent / "accounts" / "theaishrink"


@pytest.mark.parametrize("name", ["voice_fr.md", "voice_en.md"])
def test_selective_warm_voice_requires_evidence_and_honest_identity(name):
    text = " ".join((ACCOUNT / name).read_text().lower().split())
    assert "knowledgeable woman" in text and "sharp, thoughtful, nice" in text
    assert "answer identity questions honestly as a bot" in text
    assert "never claim to know everything" in text
    assert "one supported angle" in text and "skip" in text
    assert "empty applause" in text and "unseen craft" in text
    assert all(word in text for word in ("inference", "evaluation", "gpus", "quantization"))
    assert "english only" in text and "substitute si for generic ai" in text
    assert "at most 1,400 replies" in text
    assert "at least eight seconds" in text and "ai videos, art or memes" in text
    assert "cute understatement" in text and "unusually inventive video concept" in text
    assert "only a model name swapped" in text and "never a daily minimum" in text
    assert "at most two replies" in text and "five minutes" in text
    assert "06:00, 09:00, 12:00, 17:00, 21:00" in text
    assert "news and automatic startup posts are disabled" not in text


def test_relation_prompts_script_no_medical_metaphor():
    from src.core import account
    from src.replies import debate_bot, replyback_agent
    for prompt in (account.current().relations.default, debate_bot.DEBATE_PROMPT, replyback_agent.REPLYBACK_PROMPT):
        assert not any(word in prompt.lower() for word in ("clinical", "couch", "patient", "therapy", "session"))


def test_the_voice_renders_the_operators_files_verbatim(bilingual_account):
    from src.core import personality_store
    for lang in ("fr", "en"):
        assert personality_store.render_voice(lang).endswith("\n\n" + (ACCOUNT / f"voice_{lang}.md").read_text().strip())
