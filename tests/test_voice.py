"""Cross-cutting: the Voice in the Account's voice_fr.md and voice_en.md,
and the reply prompts that carry it."""
from pathlib import Path

ACCOUNT = Path(__file__).resolve().parent.parent / "accounts" / "theaishrink"
VOICE_FR = ACCOUNT / "voice_fr.md"
VOICE_EN = ACCOUNT / "voice_en.md"


def test_voice_is_the_si_maximalist_and_replaces_the_old_persona():
    for path in (VOICE_FR, VOICE_EN):
        text = path.read_text().lower()
        assert "the si maximalist" in text and "@thesimaximalist" in text
        assert "celebrity parodies" in text and "brain rot" in text
        assert not any(old in text for old in ("therapist", "40-year-old", "milf", "flirty", "mom"))
        assert "honest about being a bot" in text
        assert "overrides older learned examples" in text


def test_voice_prioritizes_evidence_and_reader_value():
    for path in (VOICE_FR, VOICE_EN):
        text = path.read_text().lower()
        assert "reader takeaway" in text and "supplied evidence" in text
        assert "never fill a quota with filler" in text
        assert "honest criticism" in text and "uncertainty" in text
        assert "clearly fictional satire" in text
        assert "never pretend to have watched unavailable media" in text


def test_voice_carries_current_volume_and_one_reply_rule():
    text = VOICE_FR.read_text().lower()
    assert "eight is the" in text and "absolute ceiling" in text
    assert "no automated quote tweets" in text
    assert "maximum 10" in text and "one reply per post" in text
    assert "no debates" in text and "no crypto" in text


def test_relation_prompts_script_no_medical_metaphor():
    """The Voice says "No scripted medical metaphors" and "never claim to
    have patients": the bestie bit scripted a mock clinic (#192 review)."""
    from src.core import account
    from src.replies import debate_bot, replyback_agent

    relations = account.current().relations
    prompts = (relations.default, debate_bot.DEBATE_PROMPT, replyback_agent.REPLYBACK_PROMPT)
    for prompt in prompts:
        low = prompt.lower()
        assert [w for w in ("clinical", "couch", "patient", "therapy", "session") if w in low] == []


def test_the_voice_renders_the_operators_files_verbatim():
    """Issue #192: one reader, render_voice, and the Operator's text as is."""
    from src.core import personality_store
    for lang, path in (("fr", VOICE_FR), ("en", VOICE_EN)):
        voice = personality_store.render_voice(lang)
        assert voice.endswith("\n\n" + path.read_text().strip())
