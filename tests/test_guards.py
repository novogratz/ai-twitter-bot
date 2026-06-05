"""Safety-net tests for the pure-logic guard modules.

These exist so AGENTIC code pushes (daily auto-improve runs, future Claude
sessions) have a deterministic gate: if a change breaks the dedup, the price
gate, the pattern scrubber, or the unwrap pipeline, the suite fails before
the push ships. No Safari, no LLM — runs in <5s.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src import content_guard as cg
from src import pattern_tags
from src.llm_client import unwrap_text, contains_post_unsafe_leak


@pytest.fixture(autouse=True)
def isolate_dedup(monkeypatch, tmp_path):
    """Each test gets an empty dedup corpus (no real tweet_history bleed)."""
    monkeypatch.setattr(cg, "_HISTORY_FILE", str(tmp_path / "none.json"))
    cg._RECENT_NORM.clear()
    yield
    cg._RECENT_NORM.clear()


# --- dedup v2 -------------------------------------------------------------

def test_dedup_catches_same_thesis_different_words():
    cg.note_posted("Everyone watches GPU supply. The real bottleneck is the power bill")
    assert cg.is_duplicate(
        "Everyone is tracking GPU supply. The real bottleneck is the power bill. "
        "You are buying silicon; you are renting electricity."
    )


def test_dedup_catches_same_story_window():
    cg.note_posted(
        "Anthropic raised at a valuation that assumes AGI is a utility bill. "
        "The bottleneck is not compute."
    )
    assert cg.is_duplicate(
        "Anthropic raises another round at a valuation higher than its cumulative revenue."
    )


def test_dedup_allows_different_stories():
    cg.note_posted(
        "Nvidia ships Blackwell GB300 racks to South Korea. Samsung and SK Hynix "
        "just became the new memory oligopoly."
    )
    assert not cg.is_duplicate(
        "OpenAI signs a 10GW datacenter deal in Texas. Sam Altman now buys "
        "electricity like other CEOs buy ad slots."
    )


def test_dedup_header_scaffolding_is_not_similarity():
    cg.note_posted(
        "🔎 The Decode Daily #97. AI\n\nData centers are consuming 1,000 TWh by 2026."
    )
    assert not cg.is_duplicate(
        "🔎 The Decode Daily #98. Bitcoin\n\nBitcoin and ether ETFs snap a record "
        "multi-billion outflow streak. Wall Street finally blinked."
    )


def test_dedup_exact_repost_blocked():
    text = "The market did not betray you. It just does not know you yet."
    cg.note_posted(text)
    assert cg.is_duplicate(text)


# --- price-target gate ------------------------------------------------------

def test_price_gate_blocks_near_term_target():
    assert cg.has_near_term_price_target("$RKLB to $40 by friday, trust me")


def test_price_gate_allows_normal_news():
    assert not cg.has_near_term_price_target(
        "Anthropic raised $13B this year at a $350B valuation."
    )
    assert not cg.has_near_term_price_target(
        "Multi-year thesis: $NVDA datacenter revenue compounds through 2030."
    )


# --- language detection ------------------------------------------------------

def test_language_detection():
    lang, conf = cg.detect_language("Le marché est dans une bulle, c'est évident pour tout le monde.")
    assert lang == "fr"
    lang, conf = cg.detect_language("The market is in a bubble and everyone is pretending otherwise.")
    assert lang == "en"


# --- lazy-reply gate ---------------------------------------------------------

def test_lazy_reply_rejected():
    ok, reason = cg.validate("great post", kind="reply")
    assert not ok


def test_substantive_reply_passes():
    ok, reason = cg.validate(
        "datacenter is 88% of revenue now — that fear you feel is just concentration risk wearing a hoodie",
        kind="reply",
    )
    assert ok


# --- pattern tag scrubbing -----------------------------------------------------

def test_pattern_tag_stripped():
    cleaned, pid = pattern_tags.extract_pattern("Take here.\n[PATTERN: METAPHOR]")
    assert "[PATTERN" not in cleaned.upper()
    assert pid == "METAPHOR"


def test_bare_pattern_tag_scrubbed_at_chokepoint():
    from src.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("CAPES DON'T SPIN COMPUTERS. WIRES DO.\n\n[RENAME]")
    assert "[RENAME]" not in out
    assert "WIRES DO." in out


def test_legit_brackets_survive_scrub():
    from src.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("Normal tweet with [brackets] kept and RENAME mid-sentence")
    assert "[brackets]" in out
    assert "RENAME" in out


# --- llm unwrap --------------------------------------------------------------

def test_structured_output_json_array_survives():
    arr = json.dumps([{"tweet_url": "https://x.com/a/status/1", "reply": "calm take"}])
    assert unwrap_text(arr, structured_output=True).startswith("[")


def test_unstructured_json_array_blocked():
    arr = json.dumps([{"type": "step_start", "sessionID": "x"}])
    assert unwrap_text(arr) == ""


def test_plain_text_passes_unwrap():
    assert unwrap_text("just a tweet") == "just a tweet"


def test_post_unsafe_leak_detection():
    assert contains_post_unsafe_leak('{"type":"step_start","x":1}')
    assert not contains_post_unsafe_leak("a normal tweet about GPUs")


# --- scrape timestamp regression (the 2-day retweet collapse) -----------------

def test_scrape_age_uses_timestamp_field():
    from datetime import datetime, timedelta, timezone
    from src.retweet_bot import _scrape_age_hours
    fresh = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    assert _scrape_age_hours({"timestamp": fresh}) < 4
    assert _scrape_age_hours({"timestamp": ""}) > 100_000  # unknown = stale


# --- history idempotency -------------------------------------------------------

def test_save_tweet_idempotent(monkeypatch, tmp_path):
    import src.history as history
    import src.config as config
    hist_file = str(tmp_path / "hist.json")
    monkeypatch.setattr(history, "HISTORY_FILE", hist_file)
    history.save_tweet("same text")
    history.save_tweet("same text")
    assert len(history.load_history()) == 1
