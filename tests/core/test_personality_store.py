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
