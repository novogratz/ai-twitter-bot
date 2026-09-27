"""src/core/personality_store: the hard-rules block."""


def test_positive_only_subjects_in_hard_rules():
    """Operator 2026-06-08: Apple / US government / Trump / Elon Musk must be
    spoken of ONLY positively. The rule must live in the non-overridable
    hard-rules block injected into every generation prompt."""
    from src.core import personality_store as ps
    block = ps.hard_rules_block()  # fresh render (incl. respect list)
    low = block.lower()
    for subj in ("apple", "us government", "trump", "elon musk"):
        assert subj in low, f"positive-only subject {subj!r} missing from hard rules"
    # Must instruct positive-only + override the snark voice.
    assert "positive" in low and ("only" in low or "never criticize" in low)
    assert "override" in low or "overrides" in low


def test_english_text_follows_simplified_technical_english():
    """Operator 2026-09-27: English posts and replies take the form of
    ASD-STE100 Simplified Technical English, while the Voice keeps the tone.
    A hard rule, so every Original and Reply prompt carries it; French text
    keeps its own form."""
    from src.core import personality_store as ps
    block = " ".join(ps.hard_rules_block().split())
    assert "ASD-STE100 Simplified Technical English" in block
    assert "in English" in block and "French text keeps its own form" in block
    assert "The Voice still sets the tone" in block
    # STE forbids what voice_en.md asks for ("Use contractions"): form is STE's.
    assert "no contractions" in block and "this rule wins" in block


def test_hard_rules_name_no_removed_surface():
    """Operator 2026-09-27: the hard rules and the respect list close every
    prompt, and still named the snark voice, hot takes, breakouts, spicy
    takes and quote tweets, all gone; quotes stay at zero."""
    from src.core import personality_store as ps
    low = ps.hard_rules_block().lower()
    removed = ("snark voice", "hot take", "breakout", "spicy take", "quote-tweet", "quote tweet", "or quote")
    assert [w for w in removed if w in low] == []
    assert "original" in low and "reply" in low
