"""src/core/pattern_tags and src/core/pillar_tags."""
from src.core import pattern_tags


def test_pattern_tag_stripped():
    cleaned, pid = pattern_tags.extract_pattern("Take here.\n[PATTERN: METAPHOR]")
    assert "[PATTERN" not in cleaned.upper()
    assert pid == "METAPHOR"


def test_new_pillars_match_the_current_scope_without_reusing_retired_tags():
    from src.core.pillar_tags import ACTIVE_PILLARS, classify
    assert classify("Your portfolio is processing trauma.") == "other"
    assert classify("Grok Imagine generated this short video.") == "ai_video"
    assert classify("SI brainrot has eaten the entire timeline.") == "si_brainrot"
    assert classify("A fictional AI celebrity parody in a generated clip.") == "celebrity_parody"
    assert classify("OpenAI ships a new model and the GPU bill doubles.") == "ai_news_take"
    assert classify("anything", action_type="quote_gif") == "meme_reaction"
    assert classify("anything", source="GIF/this is fine") == "meme_reaction"
    assert classify("") == "other"
    assert not {"market_trauma", "ai_vs_btc", "reply_bait"} & ACTIVE_PILLARS
