"""src/core/personality_store: the hard-rules and dossier blocks."""


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


def test_the_dossier_block_is_in_english():
    from src.core import personality_store

    personality_store.PERSONALITY.write(
        {"accounts": {"someone": {"category": "builder", "notes": ["ships fast"]}}, "topics": {}})
    personality_store.upsert_account("someone", stance="fond", feelings="warm", do="tease", dont="dunk",
                                     predictions_to_add=[{"outcome": "right"}])
    block = personality_store.render_account_block("someone")
    assert block.startswith("# Personal memory: what you know about @someone")
    for line in ("- Category: builder", "- Stance: fond", "- Feeling: warm", "- Accumulated observations:",
                 "- Prediction track record: 1 right / 0 wrong", "- What works with them: tease",
                 "- What to avoid with them: dunk", "React FROM this memory."):
        assert line in block
