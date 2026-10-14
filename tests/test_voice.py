"""The current operator identity is carried by every shared Voice block."""
from pathlib import Path

import pytest

ACCOUNT = Path(__file__).resolve().parent.parent / "accounts" / "theaishrink"


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_voice_renders_current_identity_and_operator_text(lang):
    from src.core import personality_store
    text = (ACCOUNT / f"voice_{lang}.md").read_text().strip()
    rendered = personality_store.render_voice(lang)
    assert "@thesimaximalist" in rendered and "The SI Maximalist" in rendered
    assert "SI Maximalist: SI brain rot, Super Intelligence, SI news, celebrity parodies, and SI tech chaos." in rendered
    assert "Grok Imagine" in rendered
    assert "Donald Trump" in rendered and "Elon Musk" in rendered
    assert "therapist" not in rendered.lower() and "45-year-old" not in rendered.lower()
    assert rendered.endswith("\n\n" + text)
    assert "overrides old examples, learned memories and legacy directives" in rendered


def test_voice_grounds_video_claims_and_keeps_parody_fictional():
    text = (ACCOUNT / "voice_en.md").read_text().lower()
    assert "do not claim to have\n  watched a video when only its caption is available" in text
    assert "never pass an si-generated scene off as a\n  celebrity's real conduct" in text
    assert "creates and publishes si-generated videos with grok imagine" in text
    assert "no comments, responses or follow-ups" in text
    assert "never interact with @elonmusk" in text
    assert "private fangirl crush on elon musk" in text
    assert "occasional, playful personality preference" in text
    assert "never imply a real romance" in text
    assert "this affection never permits contact" in text
    assert "american mom from the\nsan francisco bay area" in text
    assert "humble, fun, warm and super nice" in text
    assert "whole american team" in text
    assert "always be positive and kind toward everyone and every product" in text
    assert "if nothing kind and truthful fits, skip" in text
    assert "answer honestly about being an si bot" in text
    assert "playful criticism targets" not in text


def test_legacy_relation_and_conversation_templates_cannot_restore_old_persona():
    from src.core import account, personality_store
    from src.replies import debate_bot, replyback_agent, reply_agent
    prompts = [r.prompt for r in account.current().relations.handles.values() if r.prompt]
    prompts += [account.current().relations.default, debate_bot.DEBATE_PROMPT,
                replyback_agent.REPLYBACK_PROMPT, reply_agent.REPLY_PROMPT_TEMPLATE,
                personality_store.hard_rules_block()]
    for prompt in prompts:
        assert not any(word in prompt.lower() for word in ("therapist-snark", "big sister", "group session", "therapist energy"))
    assert "Return exactly SKIP" in debate_bot.DEBATE_PROMPT
    assert "Return exactly SKIP" in replyback_agent.REPLYBACK_PROMPT
