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


# --- hot_quote slot consumption (the 4-slot burn bug) -------------------------

def test_hot_quote_preserves_slot_on_chokepoint_skip(monkeypatch, tmp_path):
    """quote_tweet() returns False on dup/spacing skip — the hot_quote bot
    MUST NOT mark the slot 'done' or burn the candidate URL, otherwise the
    highest-signal 4x/day surface silently disappears when dedup catches a
    near-miss. Witnessed 2026-06-05 (2 of 2 hot_quote slots burned before
    the fix)."""
    from src import hot_quote_bot as hqb

    state_file = tmp_path / "hot_quote_state.json"
    quoted_file = tmp_path / "quoted.json"
    monkeypatch.setattr(hqb, "STATE_FILE", str(state_file))
    monkeypatch.setattr(hqb, "QUOTED_FILE", str(quoted_file))

    monkeypatch.setattr(hqb, "_load_signal_items", lambda: [
        {"title": "Topic A", "summary": "hint A"},
        {"title": "Topic B", "summary": "hint B"},
    ])
    monkeypatch.setattr(hqb, "_search_best_tweet", lambda topic: {
        "author": "elonmusk",
        "text": "AI is the future",
        "likes": 9000,
        "url": f"https://x.com/elonmusk/status/{abs(hash(topic)) % 10**18}",
    })
    monkeypatch.setattr(hqb, "_generate_quote", lambda a, t, h: "calm take on AI")

    calls = []

    def fake_quote(url, comment):
        calls.append(url)
        return False  # simulate dedup / spacing skip at the chokepoint

    monkeypatch.setattr(hqb, "quote_tweet", fake_quote)

    hqb.run_hot_quote_cycle()

    # Both topics tried, both skipped — slot NOT consumed, URLs NOT burned.
    assert len(calls) == 2, "both topics should be tried after a skip"
    assert not state_file.exists() or "last_slot" not in json.loads(state_file.read_text())
    assert not quoted_file.exists() or json.loads(quoted_file.read_text()) == []


def test_hot_quote_consumes_slot_on_successful_post(monkeypatch, tmp_path):
    from src import hot_quote_bot as hqb

    state_file = tmp_path / "hot_quote_state.json"
    quoted_file = tmp_path / "quoted.json"
    monkeypatch.setattr(hqb, "STATE_FILE", str(state_file))
    monkeypatch.setattr(hqb, "QUOTED_FILE", str(quoted_file))

    monkeypatch.setattr(hqb, "_load_signal_items", lambda: [
        {"title": "Topic A", "summary": "hint A"},
    ])
    url = "https://x.com/elonmusk/status/1"
    monkeypatch.setattr(hqb, "_search_best_tweet", lambda topic: {
        "author": "elonmusk", "text": "AI is the future", "likes": 9000, "url": url,
    })
    monkeypatch.setattr(hqb, "_generate_quote", lambda a, t, h: "calm take on AI")
    monkeypatch.setattr(hqb, "quote_tweet", lambda u, c: True)
    monkeypatch.setattr(hqb, "log_reply", lambda *a, **k: None)

    hqb.run_hot_quote_cycle()

    state = json.loads(state_file.read_text())
    assert state.get("last_slot")
    assert url in json.loads(quoted_file.read_text())


# --- truncation guard (the "botched ChatGPT paste" callout, 2026-06-05) -------

def test_smart_trim_ends_on_sentence():
    from src.humanizer import smart_trim
    long = ("jensen vend les pelles. les vrais gagnants d'internet n'ont pas tous misé "
            "sur Cisco en 2000 — ils ont construit des boîtes dessus quand le reste du "
            "marché cherchait encore comment épeler \"e-commerce\". la vraie question "
            "n'est pas quelle action acheter mais quel produit construire dessus.")
    out = smart_trim(long, 220)
    assert len(out) <= 220
    assert out.endswith((".", "!", "?", "…"))  # never a dangling fragment


def test_smart_trim_short_text_untouched():
    from src.humanizer import smart_trim
    assert smart_trim("short take", 220) == "short take"


def test_validate_rejects_truncated_reply():
    ok, reason = cg.validate(
        "les vrais gagnants n'ont pas tous misé sur Cisco en 2000, ils ont construit des boîtes dessus. la vraie question n",
        kind="reply",
    )
    assert not ok and "truncat" in reason


def test_validate_rejects_overlong_reply():
    ok, reason = cg.validate("a sharp take " * 30, kind="reply")
    assert not ok and "too long" in reason


def test_validate_allows_casual_unpunctuated_ending():
    ok, _ = cg.validate("screenshot this. we'll talk about it in 6 months", kind="reply")
    assert ok


# --- one reply per tweet, EVER (double-reply incident, 2026-06-05) -------------

def test_reply_chokepoint_blocks_second_reply(monkeypatch, tmp_path):
    """Two reply bots racing on the same tweet: the second write MUST be
    refused at the chokepoint regardless of which bot it came from."""
    import src.reply_bot as rb
    import src.twitter_client as tc
    from src import action_guard, config

    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(action_guard, "can_post", lambda action: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(a))

    url = "https://x.com/Graphseo/status/1234567890123456789"
    reply = "the spelling-mistake signal lasts exactly one fine-tune cycle. enjoy it while it works"
    tc.reply_to_tweet(url, reply)
    tc.reply_to_tweet(url, reply + " v2")          # same tweet, second bot
    tc.reply_to_tweet(url + "?s=20", reply + " v3")  # same tweet, different URL form

    assert len(recorded) == 1  # exactly ONE reply ever reached the write


# --- human-typo injection for @Graphseo (operator mandate 2026-06-05) ----------

def test_inject_human_typo_exactly_one_adjacent_char():
    import random
    from src.humanizer import inject_human_typo, _KEY_NEIGHBORS
    text = "le signal des fautes va marcher exactement un cycle de finetuning pas plus"
    out = inject_human_typo(text, rng=random.Random(42))
    assert out != text and len(out) == len(text)
    diffs = [(a, b) for a, b in zip(text, out) if a != b]
    assert len(diffs) == 1                       # exactly ONE character changed
    orig, typo = diffs[0]
    assert typo in _KEY_NEIGHBORS[orig]          # and it's keyboard-adjacent


def test_inject_human_typo_skips_unsafe_words():
    from src.humanizer import inject_human_typo
    # only mentions/URLs/short words -> unchanged
    text = "@Graphseo yes https://x.com/a $NVDA ok"
    assert inject_human_typo(text) == text


# --- GIF tag pipeline (operator 2026-06-05: funny GIFs on posts/quotes) --------

def test_extract_gif_query():
    from src.humanizer import extract_gif_query
    clean, q = extract_gif_query("the couch is open.\n\n[GIF: this is fine]")
    assert q == "this is fine" and "[GIF" not in clean and "couch" in clean
    clean2, q2 = extract_gif_query("no tag here")
    assert q2 == "" and clean2 == "no tag here"


def test_gif_tag_scrubbed_at_chokepoint():
    from src.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("take here\n[GIF: kermit panic]")
    assert "[GIF" not in out and "take here" in out


# --- monetization mandate gates (2026-06-05 PM) ---------------------------------

def test_post_urls_stripped():
    from src.twitter_client import _strip_post_urls
    out = _strip_post_urls("Big take here.\n\nhttps://cnbc.com/article/xyz")
    assert "http" not in out and "Big take here." in out


def test_hashtags_stripped_at_chokepoint():
    from src.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("the market needs therapy #Bitcoin #AI")
    assert "#" not in out and "therapy" in out


def test_review_mode_queues_instead_of_posting(monkeypatch, tmp_path):
    import json, os
    import src.twitter_client as tc
    from src import action_guard
    monkeypatch.setenv("REVIEW_MODE", "1")
    import src.config as config
    monkeypatch.setattr(config, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(action_guard, "can_post", lambda a: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(a))
    tc.post_tweet("a sponsor-clean original take about the market needing a therapist today")
    qpath = os.path.join(str(tmp_path), "review_queue.json")
    assert os.path.exists(qpath)
    q = json.load(open(qpath))
    assert len(q) == 1 and q[0]["kind"] == "post"
    assert recorded == []  # nothing published


def test_niche_excludes_space_now():
    from src.retweet_bot import _is_on_niche
    assert not _is_on_niche("Beautiful photo of the lunar surface from the Artemis mission astronauts")
    assert _is_on_niche("Nvidia datacenter revenue is 88% of the company now")


# --- engine-health false-collapse on disabled surfaces (2026-06-06) -------------

def test_engine_health_skips_disabled_surface(monkeypatch, tmp_path):
    """MAX_RETWEETS_PER_DAY=0 (monetization mandate) disables bare retweets.
    Comparing today's forced-0 against a multi-day pre-mandate baseline must
    NOT fire a 'collapsed' alert — the surface is intentionally OFF, not
    failing. Without this guard the self-heal launches every cycle on a
    deliberately-disabled engine and burns the Claude cooldown.
    """
    import os
    import csv
    from src import engine_health_bot as ehb

    log_path = tmp_path / "engagement_log.csv"
    alerts_path = tmp_path / "engine_health_alerts.json"
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    monkeypatch.setattr(ehb, "ALERTS_FILE", str(alerts_path))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")  # never spawn the emergency script
    monkeypatch.setenv("MAX_RETWEETS_PER_DAY", "0")  # mandate: retweets OFF

    from datetime import date, timedelta
    rows = [["timestamp", "type", "text", "target_url"]]
    for i in range(1, 8):
        d = (date.today() - timedelta(days=i)).isoformat()
        for _ in range(50):
            rows.append([f"{d}T00:00:00", "retweet", "x", "y"])
    with open(log_path, "w") as f:
        csv.writer(f).writerows(rows)

    ehb.run_engine_health_cycle()
    assert not alerts_path.exists(), "disabled surface must not trigger a collapse alert"


def test_engine_health_still_alerts_active_surface(monkeypatch, tmp_path):
    """Mirror of the above: when the cap is positive but today's count is 0
    against a large baseline, the alert MUST still fire. Guards against the
    fix over-suppressing."""
    import os
    import csv
    from src import engine_health_bot as ehb

    log_path = tmp_path / "engagement_log.csv"
    alerts_path = tmp_path / "engine_health_alerts.json"
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    monkeypatch.setattr(ehb, "ALERTS_FILE", str(alerts_path))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")
    monkeypatch.setenv("MAX_REPLIES_PER_DAY", "100")  # surface is ON

    from datetime import date, timedelta
    rows = [["timestamp", "type", "text", "target_url"]]
    for i in range(1, 8):
        d = (date.today() - timedelta(days=i)).isoformat()
        for _ in range(50):
            rows.append([f"{d}T00:00:00", "reply", "x", "y"])
    with open(log_path, "w") as f:
        csv.writer(f).writerows(rows)

    ehb.run_engine_health_cycle()
    assert alerts_path.exists()
    import json as _json
    alerts = _json.load(open(alerts_path))
    flat = " ".join(a for entry in alerts for a in entry.get("alerts", []))
    assert "reply collapsed" in flat


def test_engine_health_quote_disabled_only_if_all_caps_zero(monkeypatch, tmp_path):
    """quote is governed by MAX_QUOTES_PER_DAY AND MAX_QUOTE_REPOSTS_PER_DAY.
    If either is positive, quote is still ON and a 0-count should alert."""
    import csv
    from src import engine_health_bot as ehb

    log_path = tmp_path / "engagement_log.csv"
    alerts_path = tmp_path / "engine_health_alerts.json"
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    monkeypatch.setattr(ehb, "ALERTS_FILE", str(alerts_path))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")
    monkeypatch.setenv("MAX_QUOTES_PER_DAY", "0")
    monkeypatch.setenv("MAX_QUOTE_REPOSTS_PER_DAY", "6")  # the other path still on

    from datetime import date, timedelta
    rows = [["timestamp", "type", "text", "target_url"]]
    for i in range(1, 8):
        d = (date.today() - timedelta(days=i)).isoformat()
        for _ in range(20):
            rows.append([f"{d}T00:00:00", "quote", "x", "y"])
    with open(log_path, "w") as f:
        csv.writer(f).writerows(rows)

    ehb.run_engine_health_cycle()
    assert alerts_path.exists(), "quote must still alert when only ONE of its caps is zero"
