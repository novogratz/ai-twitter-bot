"""src/core/pattern_tags and src/core/pillar_tags."""
from src.core import pattern_tags


def test_pattern_tag_stripped():
    cleaned, pid = pattern_tags.extract_pattern("Take here.\n[PATTERN: METAPHOR]")
    assert "[PATTERN" not in cleaned.upper()
    assert pid == "METAPHOR"


def test_pillar_classifier_buckets():
    from src.core.pillar_tags import classify
    assert classify("Your portfolio isn't down. It's processing trauma. Sit with it.") == "other"
    assert classify("Saylor buys more bitcoin while the AI agents trade against him.") == "other"
    assert classify("OpenAI ships a new model and the GPU bill doubles overnight.") == "ai_news_take"
    assert classify("Group session: what's the most you've ever panic-sold?") == "other"
    # Explicit signals beat text heuristics.
    assert classify("anything", action_type="quote_gif") == "other"
    assert classify("anything", source="GIF/this is fine") == "other"
    assert classify("Honest take on markets today.", source="QUESTION") == "other"
    assert classify("") == "other"


def test_si_wording_uses_the_existing_topic_metric_and_smileys_are_reactions():
    from src.core.pillar_tags import classify
    assert classify("SI agents need repeatable evaluations.") == "ai_news_take"
    assert classify("🙂") == "meme_reaction"
    assert classify("Bittensor SI staking yields are up.") == "other"
