"""Cross-cutting: the Voice in the Account's voice_fr.md and voice_en.md,
and the reply prompts that carry it."""
from pathlib import Path

ACCOUNT = Path(__file__).resolve().parent.parent / "accounts" / "theaishrink"
VOICE_FR = ACCOUNT / "voice_fr.md"
VOICE_EN = ACCOUNT / "voice_en.md"


def test_voice_has_ai_fan_voice():
    for path in (VOICE_FR, VOICE_EN):
        text = path.read_text().lower()
        assert "obsessed with ai" in text and "excited" in text
        assert "45-year-old woman and mom" in text


def test_voice_prioritizes_reader_value():
    text = VOICE_FR.read_text().lower()
    assert "reader takeaway" in text and "source" in text
    assert "never fill a quota with filler" in text


def test_voice_keeps_warmth_and_honest_criticism():
    text = VOICE_FR.read_text().lower()
    assert "kind and hopeful" in text and "never cruel" in text
    assert "honest criticism" in text and "uncertainty" in text


def test_voice_carries_editorial_strategy():
    text = VOICE_FR.read_text().lower()
    assert "at least three original ai posts" in text
    assert "eight is the absolute ceiling" in text
    assert "no automated quote tweets" in text
    assert "replies remain uncapped" in text


def test_persona_is_woman_mom_in_the_one_voice():
    """Operator 2026-07-19: 'she is a mom, a 35-40yo therapist... make her
    sound like a woman' + 'the sharpest AI therapist that knows AI more than
    anyone else'. The persona is pinned in the spine (the Voice), which
    the Voice block carries into every prompt (issue #192: no surface keeps
    its own copy). Also pins that the bestie bit moved big brother -> sister."""
    spine = VOICE_FR.read_text().lower()
    assert "woman" in spine and "mom" in spine and "45-year-old" in spine
    assert "sharpest ai mind" in spine
    assert "bro" in spine  # the no-bro-speak rule is stated

    from src.core import account
    bestie_prompt = account.current().relations.get("TheBTCTherapist").prompt.lower()
    assert "big sister" in bestie_prompt and "big brother" not in bestie_prompt


def test_relation_prompts_script_no_medical_metaphor():
    """The Voice says "No scripted medical metaphors" and "never claim to
    have patients": the bestie bit scripted a mock clinic (#192 review)."""
    from src.core import account
    from src.replies import debate_bot, replyback_agent

    relations = account.current().relations
    prompts = (relations.get("TheBTCTherapist").prompt, relations.default, relations.get("Graphseo").prompt,
               debate_bot.DEBATE_PROMPT, replyback_agent.REPLYBACK_PROMPT)
    for prompt in prompts:
        low = prompt.lower()
        assert [w for w in ("clinical", "couch", "patient", "therapy", "session") if w in low] == []


def test_the_voice_renders_the_operators_files_verbatim():
    """Issue #192: one reader, render_voice, and the Operator's text as is."""
    from src.core import personality_store
    for lang, path in (("fr", VOICE_FR), ("en", VOICE_EN)):
        voice = personality_store.render_voice(lang)
        assert voice.endswith("\n\n" + path.read_text().strip())


def test_savvy_tech_mom_register():
    """Operator 2026-07-19: 'be less a troll and more a savvy tech mom.'
    The spine carries the savvy-tech-mom-not-a-troll register so every
    surface inherits it."""
    spine = VOICE_FR.read_text().lower()
    assert "45-year-old woman and mom" in spine and "never cruel" in spine
    assert "something useful" in spine, "helpful register must be stated"


def test_spicy_dial_suggestive_never_explicit():
    """Operator 2026-07-28: 'more sexy and spicy... like a milf ai
    therapist — still the sharpest of all on AI.' Pins: the spice dial
    exists in the spine AND its guardrails ride with it everywhere it
    appears — suggestive never explicit ('the wink, not the wardrobe'),
    rationed (~1 in 4), and the sharpest-AI-mind payload always required
    (smart IS the sexy). A spicy persona without the guardrails is a brand
    risk; guardrails without the dial ignores the mandate."""
    spine = VOICE_FR.read_text().lower()
    assert "spicy dial" in spine and ("flirty" in spine or "flirt" in spine)
    assert "never explicit" in spine and "the wink, not the wardrobe" in spine
    assert "1 post in 4" in spine or "1 in 4" in spine, "spice must be rationed"
    assert "smart is the sexy" in spine, "authority must ride with the heat"

    from src.core import personality_store
    for lang in ("fr", "en"):
        low = personality_store.render_voice(lang).lower()
        assert "flirt" in low and "never explicit" in low, \
            "the Voice every prompt carries must hold the dial WITH its guardrail"
