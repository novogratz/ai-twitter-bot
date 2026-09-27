"""Cross-cutting: the Voice in the Account's voice_fr.md and voice_en.md,
and the reply prompts that carry it."""
import re
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
    for path in (VOICE_FR, VOICE_EN):
        text = path.read_text().lower()
        assert "something useful" in text and "lead with the detail that matters" in text
        assert "never invent a source or number" in text


def test_voice_keeps_warmth_and_honest_criticism():
    text = VOICE_FR.read_text().lower()
    assert "kind and hopeful" in text and "never cruel" in text
    assert "honest criticism" in text and "uncertainty" in text


def test_voice_carries_no_publishing_policy():
    """Operator 2026-09-27: the Voice opens every Reply prompt, where the
    hours, the daily ceiling and the reach target help nothing, and the two
    files disagreed on the ceiling (seven, eight). The engine enforces the
    policy and docs/EDITORIAL_POLICY.md states it; the Voice says who writes."""
    for path in (VOICE_FR, VOICE_EN):
        text = path.read_text().lower()
        assert [w for w in ("publishing policy", "ceiling", "per day", "toronto", "500,000")
                if w in text] == [], path.name
        # The one line of the policy block the Operator kept.
        assert "skip a weak story; never fill a quota with filler." in text


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


def test_the_graphseo_relation_stays_on_ai_without_a_formula():
    """Operator 2026-09-27: his prompt still bridged to "AI/Space/Investment",
    the old niche, imposed "THE FORMULA — non-negotiable" ending on a
    punchline or a question, and its examples carried unsourced figures."""
    from src.core import account

    low = account.current().relations.get("Graphseo").prompt.lower()
    assert [w for w in ("space", "investment", "formula", "non-negotiable", "punchline", "their shit")
            if w in low] == []
    assert re.findall(r"\b(?!100%)\d+ ?%", low) == [], "an example figure the model would copy"
    assert "ai" in low.split() and "do not invent" in low


def test_no_relation_prompt_forces_a_hook():
    """Operator 2026-09-27: "First 6 words must hook" is the forced formula
    the Voice rules out, and "never the same angle twice in a row" asks the
    model for Replies it never sees."""
    from src.core import account

    relations = account.current().relations
    for prompt in (relations.default, *(r.prompt for r in relations.handles.values() if r.prompt)):
        low = prompt.lower()
        assert [w for w in ("must hook", "twice in a row") if w in low] == []
