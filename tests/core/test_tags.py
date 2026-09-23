"""src/core/pattern_tags and src/core/pillar_tags."""
import pytest

from src.core import pattern_tags

pytestmark = pytest.mark.usefixtures("isolate_dedup")


def test_pattern_tag_stripped():
    cleaned, pid = pattern_tags.extract_pattern("Take here.\n[PATTERN: METAPHOR]")
    assert "[PATTERN" not in cleaned.upper()
    assert pid == "METAPHOR"


def test_pillar_classifier_buckets():
    from src.core.pillar_tags import classify
    assert classify("Your portfolio isn't down. It's processing trauma. Sit with it.") == "market_trauma"
    assert classify("Saylor buys more bitcoin while the AI agents trade against him.") == "ai_vs_btc"
    assert classify("OpenAI ships a new model and the GPU bill doubles overnight.") == "ai_news_take"
    assert classify("Group session: what's the most you've ever panic-sold?") == "reply_bait"
    # Explicit signals beat text heuristics.
    assert classify("anything", action_type="quote_gif") == "meme_reaction"
    assert classify("anything", source="GIF/this is fine") == "meme_reaction"
    assert classify("Honest take on markets today.", source="QUESTION") == "reply_bait"
    assert classify("") == "other"
