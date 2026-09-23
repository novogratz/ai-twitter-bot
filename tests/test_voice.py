"""Cross-cutting: the voice in core_identity.md and the reply prompts that
carry it."""
import pytest

pytestmark = pytest.mark.usefixtures("isolate_dedup")


def test_core_identity_has_ai_fan_voice():
    from pathlib import Path
    for path in ("core_identity.md", "core_identity_en.md"):
        text = Path(path).read_text().lower()
        assert "obsessed with ai" in text and "excited" in text
        assert "45-year-old woman and mom" in text


def test_core_identity_prioritizes_reader_value():
    from pathlib import Path
    text = Path("core_identity.md").read_text().lower()
    assert "reader takeaway" in text and "source" in text
    assert "never fill a quota with filler" in text


def test_core_identity_keeps_warmth_and_honest_criticism():
    from pathlib import Path
    text = Path("core_identity.md").read_text().lower()
    assert "kind and hopeful" in text and "never cruel" in text
    assert "honest criticism" in text and "uncertainty" in text


def test_core_identity_carries_editorial_strategy():
    from pathlib import Path
    text = Path("core_identity.md").read_text().lower()
    assert "at least three original ai posts" in text
    assert "eight is the absolute ceiling" in text
    assert "no automated quote tweets" in text
    assert "replies remain uncapped" in text


def test_persona_is_woman_mom_therapist_across_surfaces():
    """Operator 2026-07-19: 'she is a mom, a 35-40yo therapist... make her
    sound like a woman' + 'the sharpest AI therapist that knows AI more than
    anyone else'. The persona must be pinned in the spine (core_identity,
    injected into every prompt) AND in the per-surface prompt openers that
    define their own identity — so no surface drifts back to the neutral/
    male voice. Also pins that the bestie bit moved big brother -> sister."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spine = open(os.path.join(root, "core_identity.md")).read().lower()
    assert "woman" in spine and "mom" in spine and "45-year-old" in spine
    assert "sharpest ai mind" in spine
    assert "bro" in spine  # the no-bro-speak rule is stated

    from src.replies import direct_reply
    assert "a woman, 45" in direct_reply.REPLY_PROMPT.lower()
    assert "mom" in direct_reply.REPLY_PROMPT.lower()
    bestie_prompt = direct_reply.BESTIE_REPLY_PROMPT.lower()
    assert "big sister" in bestie_prompt and "big brother" not in bestie_prompt


def test_savvy_tech_mom_register():
    """Operator 2026-07-19: 'be less a troll and more a savvy tech mom.'
    The spine carries the savvy-tech-mom-not-a-troll register so every
    surface inherits it."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spine = open(os.path.join(root, "core_identity.md")).read().lower()
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
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spine = open(os.path.join(root, "core_identity.md")).read().lower()
    assert "spicy dial" in spine and ("flirty" in spine or "flirt" in spine)
    assert "never explicit" in spine and "the wink, not the wardrobe" in spine
    assert "1 post in 4" in spine or "1 in 4" in spine, "spice must be rationed"
    assert "smart is the sexy" in spine, "authority must ride with the heat"

    from src.replies import direct_reply
    low = direct_reply.REPLY_PROMPT.lower()
    assert "flirt" in low and "never explicit" in low, \
        "surface prompts must carry the dial WITH its guardrail"
