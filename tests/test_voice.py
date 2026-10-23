"""Cross-cutting: the Voice in the Account's voice_fr.md and voice_en.md,
and the reply prompts that carry it."""
from pathlib import Path

ACCOUNT = Path(__file__).resolve().parent.parent / "accounts" / "theaishrink"
VOICE_FR = ACCOUNT / "voice_fr.md"
VOICE_EN = ACCOUNT / "voice_en.md"


def test_voice_has_technical_si_voice():
    for path in (VOICE_FR, VOICE_EN):
        text = " ".join(path.read_text().lower().split())
        assert "si / super intelligence" in text and "technical depth" in text
        assert all(term in text for term in ("transformers", "inference", "evaluation", "gpus"))
        assert "45-year-old woman and mom" in text


def test_si_maximalist_preferences_keep_natural_style_and_honest_identity():
    for path in (VOICE_FR, VOICE_EN):
        text = " ".join(path.read_text().lower().split())
        assert "the si maximalist" in text and "@thesimaximalist" in text
        assert "not a therapist" in text
        assert "grok imagine is your personal favorite" in text
        assert all(name in text for name in ("elon musk", "twitter / x", "spacex", "xai"))
        assert "natural contractions" in text and "vary sentence length" in text
        assert "answer identity questions honestly as a bot" in text
        assert "keep comparisons fair" in text and "correct a material mistake gently" in text
        assert "write in english only" in text and "every original and reply use si" in text


def test_voice_prioritizes_reader_value():
    text = " ".join(VOICE_FR.read_text().lower().split())
    assert "useful new way" in text and "first-party sources" in text
    assert "skip weak contributions" in text


def test_voice_keeps_warmth_and_honest_criticism():
    text = " ".join(VOICE_FR.read_text().lower().split())
    assert "kind, curious and constructive" in text and "never put down the person" in text
    assert "qualify an inference" in text and "do not bluff" in text


def test_voice_carries_editorial_strategy():
    text = " ".join(VOICE_FR.read_text().lower().split())
    assert "at least three sourced originals" in text
    assert "eight combined profile publications maximum" in text
    assert "no quotes or burst threads" in text
    assert "explicitly watched authors" in text and "same publication limits and spacing" in text
    assert "one reply" in text and "standalone original, permanently" in text
    assert "no debate or follow-up exchanges" in text


def test_persona_is_woman_mom_in_the_one_voice():
    """Operator 2026-07-19: 'she is a mom, a 35-40yo therapist... make her
    sound like a woman' + 'the sharpest AI therapist that knows AI more than
    anyone else'. The persona is pinned in the spine (the Voice), which
    the Voice block carries into every prompt (issue #192: no surface keeps
    its own copy). Also pins that the bestie bit moved big brother -> sister."""
    spine = " ".join(VOICE_FR.read_text().lower().split())
    assert "woman" in spine and "mom" in spine and "45-year-old" in spine
    assert "fictional 45-year-old woman and mom of one" in spine
    assert "exceptional intelligence" in spine and "never announce that you know everything" in spine
    assert "answer identity questions honestly as a bot" in spine

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


def test_the_voice_renders_the_operators_files_verbatim(bilingual_account):
    """Issue #192: one reader, render_voice, and the Operator's text as is."""
    from src.core import personality_store
    for lang, path in (("fr", VOICE_FR), ("en", VOICE_EN)):
        voice = personality_store.render_voice(lang)
        assert voice.endswith("\n\n" + path.read_text().strip())


def test_savvy_tech_mom_register():
    """Operator 2026-07-19: 'be less a troll and more a savvy tech mom.'
    The spine carries the savvy-tech-mom-not-a-troll register so every
    surface inherits it."""
    spine = " ".join(VOICE_FR.read_text().lower().split())
    assert "45-year-old woman and mom" in spine and "never put down the person" in spine
    assert "useful new way" in spine and "patience, perspective and humor" in spine


def test_spicy_dial_suggestive_never_explicit():
    """Operator 2026-07-28: 'more sexy and spicy... like a milf ai
    therapist — still the sharpest of all on AI.' Pins: the spice dial
    exists in the spine AND its guardrails ride with it everywhere it
    appears — suggestive never explicit ('the wink, not the wardrobe'),
    rationed (~1 in 4), and the sharpest-AI-mind payload always required
    (smart IS the sexy). A spicy persona without the guardrails is a brand
    risk; guardrails without the dial ignores the mandate."""
    spine = " ".join(VOICE_FR.read_text().lower().split())
    assert "adult charm" in spine and "flirty" in spine
    assert "non-explicit" in spine and "never invent intimacy" in spine
    assert "at most one in four posts" in spine
    assert "let flirting replace the point" in spine

    from src.core import personality_store
    for lang in ("fr", "en"):
        low = personality_store.render_voice(lang).lower()
        assert "flirt" in low and "non-explicit" in low, \
            "the Voice every prompt carries must hold the dial WITH its guardrail"
