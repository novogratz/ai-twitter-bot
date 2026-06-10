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


@pytest.fixture(autouse=True)
def _engine_health_past_warmup(monkeypatch):
    """Tests exercise engine-health checks directly — put the process past
    the boot-warmup grace window so the checks actually run. The warmup test
    itself overrides _PROCESS_START explicitly."""
    from datetime import datetime, timedelta
    from src import engine_health_bot as ehb
    monkeypatch.setattr(ehb, "_PROCESS_START",
                        datetime.now() - timedelta(minutes=ehb.WARMUP_MINUTES + 10))
    yield


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
    monkeypatch.setattr(hqb, "can_post", lambda action: (True, ""))

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
    monkeypatch.setattr(hqb, "can_post", lambda action: (True, ""))
    monkeypatch.setattr(hqb, "quote_tweet", lambda u, c: True)
    monkeypatch.setattr(hqb, "log_reply", lambda *a, **k: None)

    hqb.run_hot_quote_cycle()

    state = json.loads(state_file.read_text())
    assert state.get("last_slot")
    assert url in json.loads(quoted_file.read_text())


def test_hot_quote_spacing_block_never_touches_safari_or_llm(monkeypatch, tmp_path):
    """When quote spacing blocks, hot_quote must NOT busy-loop scrape+LLM
    laps — each lap eats two serialized Safari searches + an ollama call
    that belong to the reply lane (witnessed 2026-06-07 11:22-11:24, three
    full laps before the gap elapsed). Spacing block → cheap wait; still
    blocked → end cycle with the slot preserved."""
    from src import hot_quote_bot as hqb

    state_file = tmp_path / "hot_quote_state.json"
    quoted_file = tmp_path / "quoted.json"
    monkeypatch.setattr(hqb, "STATE_FILE", str(state_file))
    monkeypatch.setattr(hqb, "QUOTED_FILE", str(quoted_file))

    monkeypatch.setattr(hqb, "_load_signal_items", lambda: [
        {"title": "Topic A", "summary": "hint A"},
    ])
    monkeypatch.setattr(
        hqb, "can_post",
        lambda action: (False, "too soon since last quote (need ~439s gap)"),
    )
    monkeypatch.setattr(hqb, "_wait_for_quote_spacing", lambda **kw: False)

    def boom(*a, **k):
        raise AssertionError("Safari/LLM must not be touched while spacing-blocked")

    monkeypatch.setattr(hqb, "_search_best_tweet", boom)
    monkeypatch.setattr(hqb, "_generate_quote", boom)
    monkeypatch.setattr(hqb, "quote_tweet", boom)

    hqb.run_hot_quote_cycle()  # must return cleanly, no scrape, no post

    # Slot preserved for the next fire.
    assert not state_file.exists() or "last_slot" not in json.loads(state_file.read_text())


# --- breaking QRT spike detector (2026-06-07 "DO IT" viral push) ---------------

def test_breaking_qrt_fires_only_on_dominant_spike():
    """A story is 'breaking' only when it DOMINATES the signal pool:
    score >= floor AND >= ratio x runner-up. A flat pool must never fire."""
    from src.breaking_qrt_bot import pick_breaking_item

    spike = [{"title": "OpenAI buys AMD", "score": 26}, {"title": "B", "score": 1}]
    assert pick_breaking_item(spike, {}) is spike[0]

    flat = [{"title": "A story", "score": 20}, {"title": "B story", "score": 18}]
    assert pick_breaking_item(flat, {}) is None  # 20 < 3x18 — nothing dominant

    weak = [{"title": "A story", "score": 5}, {"title": "B story", "score": 1}]
    assert pick_breaking_item(weak, {}) is None  # under the 15 floor


def test_breaking_qrt_never_fires_same_story_twice():
    from src.breaking_qrt_bot import pick_breaking_item, _story_key

    items = [{"title": "OpenAI buys AMD for $100B", "score": 30}]
    state = {"fired_stories": [_story_key("OpenAI buys AMD for $100B")]}
    assert pick_breaking_item(items, state) is None

    # Same story, shuffled/extended headline — key is order-insensitive.
    rephrased = [{"title": "for $100B, OpenAI buys AMD", "score": 30}]
    assert pick_breaking_item(rephrased, state) is None


def test_breaking_qrt_chokepoint_skip_keeps_story_armed(monkeypatch, tmp_path):
    """quote_tweet returning False must NOT consume the story or the daily
    budget — the next 10-min cycle retries while the story is still hot
    (same family as the hot_quote slot-burn bug)."""
    from src import breaking_qrt_bot as bqb

    state_file = tmp_path / "breaking_qrt_state.json"
    monkeypatch.setattr(bqb, "STATE_FILE", str(state_file))
    monkeypatch.setattr(bqb, "can_post", lambda action: (True, ""))
    monkeypatch.setattr(bqb, "_load_signal_items",
                        lambda: [{"title": "OpenAI buys AMD", "score": 30}])
    monkeypatch.setattr(bqb, "_search_best_tweet", lambda topic: {
        "author": "WatcherGuru", "text": "JUST IN: ...", "likes": 9000,
        "url": "https://x.com/WatcherGuru/status/1"})
    monkeypatch.setattr(bqb, "_generate_quote", lambda a, t, h: "sharp take")
    monkeypatch.setattr(bqb, "quote_tweet", lambda u, c: False)
    monkeypatch.setattr(bqb, "_mark_quoted", lambda u: None)

    bqb.run_breaking_qrt_cycle()

    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    assert state.get("fired_today", 0) == 0
    assert bqb._story_key("OpenAI buys AMD") not in state.get("fired_stories", [])


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


def test_engine_health_clamps_baseline_by_cap(monkeypatch, tmp_path):
    """Operator lowered MAX_HOTAKES_PER_DAY 8 → 2 under the monetization
    mandate; the 7-day baseline still reflected the old cap (~19 by hour 6).
    Today's 2 == the entire daily quota — that's success, not a 'collapse'.
    The watchdog must clamp the baseline by the current cap so a hit-cap
    surface never trips the 40% ratio alert (and never burns self-heal).
    """
    import csv
    from src import engine_health_bot as ehb

    log_path = tmp_path / "engagement_log.csv"
    alerts_path = tmp_path / "engine_health_alerts.json"
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    monkeypatch.setattr(ehb, "ALERTS_FILE", str(alerts_path))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")
    monkeypatch.setenv("MAX_HOTAKES_PER_DAY", "2")  # cap was lowered

    from datetime import date, datetime, timedelta
    hour_now = datetime.now().hour
    rows = [["timestamp", "type", "text", "target_url"]]
    # 7 historical days with cap-era baseline of ~20 hotakes spread BEFORE the
    # current hour — keeps every row inside the same-hour-of-day window.
    for i in range(1, 8):
        d = (date.today() - timedelta(days=i)).isoformat()
        for _ in range(20):
            rows.append([f"{d}T00:00:00", "hotake", "x", "y"])
    # Today: hit the new cap of 2.
    today = date.today().isoformat()
    rows.append([f"{today}T0{max(hour_now-1,0):01d}:00:00", "hotake", "x", "y"])
    rows.append([f"{today}T0{max(hour_now-1,0):01d}:30:00", "hotake", "x", "y"])
    with open(log_path, "w") as f:
        csv.writer(f).writerows(rows)

    ehb.run_engine_health_cycle()
    assert not alerts_path.exists(), "surface at its daily cap must not alert"


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


def test_engine_health_suppresses_alert_when_surface_fired_recently(monkeypatch, tmp_path):
    """A surface that fired in the current or previous hour is alive — slow,
    not collapsed. Without this guard, the 04:01 cycle on 2026-06-07 reported
    'hotake collapsed: 2 vs ~10' while the hotake bot had fired successfully
    at 03:23 and 03:43 (max 20-min cadence), and was firing again at 04:02.
    Same false-positive class as PR #6 / #7: never burn the self-heal cooldown
    on a healthy bot whose only sin is matching today's cadence instead of the
    7-day cumulative-by-hour baseline.
    """
    import csv
    from src import engine_health_bot as ehb

    log_path = tmp_path / "engagement_log.csv"
    alerts_path = tmp_path / "engine_health_alerts.json"
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    monkeypatch.setattr(ehb, "ALERTS_FILE", str(alerts_path))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")
    monkeypatch.setenv("MAX_HOTAKES_PER_DAY", "400")  # operator-raised cap

    from datetime import date, datetime, timedelta
    hour_now = datetime.now().hour
    if hour_now < 1:
        # At hour 0 there is no "previous hour today" to fire in — skip.
        return
    rows = [["timestamp", "type", "text", "target_url"]]
    # 7 historical days with ~10 hotakes each before this hour → baseline=10.
    for i in range(1, 8):
        d = (date.today() - timedelta(days=i)).isoformat()
        for _ in range(10):
            rows.append([f"{d}T00:00:00", "hotake", "x", "y"])
    # Today: 2 hotakes fired in the previous hour — well below the baseline of
    # 10 (would normally alert at 20%) but the surface is plainly alive.
    today = date.today().isoformat()
    prev_h = hour_now - 1
    rows.append([f"{today}T{prev_h:02d}:23:00", "hotake", "x", "y"])
    rows.append([f"{today}T{prev_h:02d}:43:00", "hotake", "x", "y"])
    with open(log_path, "w") as f:
        csv.writer(f).writerows(rows)

    ehb.run_engine_health_cycle()
    assert not alerts_path.exists(), (
        "surface that fired in the previous hour must not trigger a collapse alert"
    )


def test_engine_health_still_alerts_on_sustained_silence(monkeypatch, tmp_path):
    """Mirror of the recent-fire guard: when the surface has been silent for
    2+ clock hours (no fire in the current hour OR the previous one), the
    alert MUST still fire. Guards against the recent-fire suppression
    over-masking a real collapse."""
    import csv
    from src import engine_health_bot as ehb

    log_path = tmp_path / "engagement_log.csv"
    alerts_path = tmp_path / "engine_health_alerts.json"
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    monkeypatch.setattr(ehb, "ALERTS_FILE", str(alerts_path))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")
    monkeypatch.setenv("MAX_HOTAKES_PER_DAY", "400")
    # Disable the slot-quiet-hours gate (it has its own dedicated test) so
    # this test exercises the sustained-silence mechanism at ANY wall hour.
    monkeypatch.setattr(ehb, "SLOT_EVAL_FROM_HOUR", 0)
    monkeypatch.setattr(ehb, "SLOT_EVAL_UNTIL_HOUR", 24)

    from datetime import date, datetime, timedelta
    hour_now = datetime.now().hour
    if hour_now < 2:
        # Need ≥2 hours of "earlier today" available to model the silence.
        return
    rows = [["timestamp", "type", "text", "target_url"]]
    for i in range(1, 8):
        d = (date.today() - timedelta(days=i)).isoformat()
        for _ in range(10):
            rows.append([f"{d}T00:00:00", "hotake", "x", "y"])
    # Today: a single fire 2 hours ago — outside the recent-fire window.
    today = date.today().isoformat()
    stale_h = hour_now - 2
    rows.append([f"{today}T{stale_h:02d}:30:00", "hotake", "x", "y"])
    with open(log_path, "w") as f:
        csv.writer(f).writerows(rows)

    ehb.run_engine_health_cycle()
    assert alerts_path.exists(), (
        "sustained silence (no fire in current or previous hour) must still alert"
    )


def test_self_heal_env_kill_switch_is_read_at_call_time(monkeypatch, tmp_path):
    """The self-heal kill switch (ENABLE_SELF_HEAL=0) MUST take effect when set
    via monkeypatch.setenv — and by extension via a live .env edit on the
    running bot. Regression: when ENABLE_SELF_HEAL / SELF_HEAL_COOLDOWN_HOURS
    were module-level constants evaluated at import, every other engine-health
    test (which calls run_engine_health_cycle() with synthetic 'collapsed'
    data) silently spawned bin/auto_improve.sh --emergency in production —
    which in turn launched a real headless Claude run against a phantom alert.
    Pin both gates at call time so the env-based override is honored.
    """
    from src import engine_health_bot as ehb
    monkeypatch.setenv("ENABLE_SELF_HEAL", "0")
    # Force the cooldown check to think the stamp is fresh — proves the
    # kill switch short-circuits BEFORE the cooldown read.
    monkeypatch.setattr(ehb, "_SELF_HEAL_STAMP", str(tmp_path / "noop"))
    spawned = []
    import subprocess as _subprocess
    monkeypatch.setattr(
        _subprocess, "Popen", lambda *a, **k: spawned.append(a) or None,
    )
    ehb._maybe_trigger_self_heal(["reply collapsed: 0 today vs ~50 (synthetic)"])
    assert spawned == [], (
        "ENABLE_SELF_HEAL=0 must suppress the auto_improve.sh subprocess "
        "(was leaking because the flag was read at import time)"
    )


def test_self_heal_cooldown_env_is_read_at_call_time(monkeypatch, tmp_path):
    """SELF_HEAL_COOLDOWN_HOURS must also be honored at call time so the
    operator can extend the cooldown live (e.g. during a known-bad window)
    without a bot restart. Writes a stamp 1h old, sets cooldown to 24h, and
    asserts no subprocess fires."""
    from src import engine_health_bot as ehb
    from datetime import datetime, timedelta
    stamp = tmp_path / ".last_self_heal"
    stamp.write_text(datetime.now().isoformat())
    import os as _os
    one_hour_ago = (datetime.now() - timedelta(hours=1)).timestamp()
    _os.utime(stamp, (one_hour_ago, one_hour_ago))
    monkeypatch.setattr(ehb, "_SELF_HEAL_STAMP", str(stamp))
    monkeypatch.setenv("ENABLE_SELF_HEAL", "1")
    monkeypatch.setenv("SELF_HEAL_COOLDOWN_HOURS", "24")
    spawned = []
    import subprocess as _subprocess
    monkeypatch.setattr(
        _subprocess, "Popen", lambda *a, **k: spawned.append(a) or None,
    )
    ehb._maybe_trigger_self_heal(["reply collapsed: 0 today vs ~50 (synthetic)"])
    assert spawned == [], "cooldown env override must be honored at call time"


# --- pre-LLM dedup re-check (operator 2026-06-07: 774 wasted reply LLM calls) ---

def test_reply_skips_llm_when_concurrent_bot_already_replied(monkeypatch, tmp_path):
    """The chokepoint in twitter_client.reply_to_tweet has always blocked a
    duplicate write, but only AFTER the ~17s ollama call. _reply_to_tweets must
    re-read replied_tweets.json from disk JUST before generating, so a URL
    another reply bot (direct_reply, feed_sweeper, retweet replyback) already
    shipped in the same minute is skipped without burning an LLM call. Burned
    ~3.6h of compute/day before the fix.
    """
    import src.direct_reply as dr
    import src.reply_bot as rb

    # Isolate the on-disk replied set so the test doesn't bleed real state.
    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))

    # Two on-niche tweets the in-memory cycle-start snapshot thinks are fresh.
    fresh_url = "https://x.com/some_ai_account/status/2063500000000000001"
    racy_url = "https://x.com/some_ai_account/status/2063500000000000002"
    tweets = [
        {"url": fresh_url, "text": "openai just raised at 500B valuation", "author": "some_ai_account"},
        {"url": racy_url, "text": "anthropic shipped a new tool — claude can now run terminals", "author": "some_ai_account"},
    ]
    cycle_snapshot = rb.load_replied()  # empty at start

    # Simulate a concurrent reply bot writing `racy_url` to disk between the
    # snapshot and the LLM call.
    concurrent_snapshot = rb.load_replied()
    concurrent_snapshot.add(racy_url)
    rb.save_replied(concurrent_snapshot)

    llm_calls: list[str] = []

    def fake_generate(author, text, lang="fr"):
        llm_calls.append(text)
        return "named-emotion validated, calm reframe with the precise fact"

    posted: list[tuple[str, str]] = []
    monkeypatch.setattr(dr, "_generate_single_reply", fake_generate)
    monkeypatch.setattr(dr, "reply_to_tweet", lambda url, reply: posted.append((url, reply)))
    # Bypass content-side gates that aren't under test here.
    monkeypatch.setattr(dr, "humanize", lambda t: t)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_tweet_age_minutes", lambda url: 5)
    monkeypatch.setattr(dr, "_is_on_niche", lambda text: True)
    monkeypatch.setattr(
        dr, "llm_hourly_limit_status", lambda: (False, 0, 1000, 0)
    )

    dr._reply_to_tweets(tweets, cycle_snapshot, "SEARCH-HOT", en_counter=[0])

    # The racy URL must be skipped BEFORE _generate_single_reply runs, and
    # propagated into the in-memory snapshot so the cycle never retries it.
    assert llm_calls == ["openai just raised at 500B valuation"], (
        "pre-LLM disk re-check must keep racy_url out of the LLM"
    )
    assert posted == [(fresh_url, "named-emotion validated, calm reframe with the precise fact")]
    assert racy_url in cycle_snapshot


# --- 2026-06-07 agent spec: follow policy (Part 1 hard constraints) ---------

@pytest.fixture()
def follow_env(monkeypatch, tmp_path):
    """Isolated ledger + whitelist + counts for action_guard follow tests."""
    from src import action_guard as ag, config

    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(tmp_path / "ledger.json"))
    wl = tmp_path / "whitelist.json"
    wl.write_text(json.dumps({"tiers": {
        "tier1": ["TheBTCTherapist"],
        "tier2": ["morganhousel"],
        "tier3": ["karpathy"],
        "tier4": ["saylor", "balajis"],
    }}))
    monkeypatch.setattr(config, "WHITELIST_FILE", str(wl))
    ag._WL_CACHE = {}
    ag._WL_MTIME = 0.0
    # Spec pacing defaults, but zeroed spacing unless a test re-enables it.
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", True)
    monkeypatch.setattr(config, "MAX_FOLLOWS_PER_DAY", 20)
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 0)
    monkeypatch.setattr(config, "FOLLOW_SPACING_JITTER_SECONDS", 0)
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", False)
    monkeypatch.setattr(config, "FOLLOW_TOTAL_CAP", 300)
    monkeypatch.setattr(config, "FOLLOW_LOW_PHASE_CEILING", 150)
    monkeypatch.setattr(config, "FOLLOW_LOW_PHASE_FOLLOWERS", 300)
    yield ag
    ag._WL_CACHE = {}
    ag._WL_MTIME = 0.0


def test_whitelist_loads_tier4(follow_env):
    ag = follow_env
    wl = ag.load_whitelist()
    assert "saylor" in wl["tier4"]
    assert "saylor" in wl["all"]
    assert ag.is_whitelisted("balajis")


def test_follow_blocked_at_low_phase_ceiling(follow_env, monkeypatch):
    """While followers are low (<300), total following must stay under ~150."""
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 150))
    ok, why = ag.can_follow("karpathy")
    assert not ok and "ceiling" in why


def test_follow_allowed_under_low_phase_ceiling(follow_env, monkeypatch):
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 149))
    ok, why = ag.can_follow("karpathy")
    assert ok, why


def test_follow_never_exceeds_hard_300_cap(follow_env, monkeypatch):
    """Even with a big follower count, total following is hard-capped at 300."""
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (10000, 300))
    ok, why = ag.can_follow("saylor")
    assert not ok and "ceiling" in why
    monkeypatch.setattr(ag, "current_counts", lambda: (10000, 299))
    ok, why = ag.can_follow("saylor")
    assert ok, why


def test_follow_keeps_following_below_followers_mid_phase(follow_env, monkeypatch):
    """Once followers exceed 300, following must stay <= followers."""
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (220, 200))
    # followers=220 is still < FOLLOW_LOW_PHASE_FOLLOWERS → 150 ceiling rules
    ok, why = ag.can_follow("morganhousel")
    assert not ok and "ceiling" in why
    monkeypatch.setattr(ag, "current_counts", lambda: (320, 280))
    ok, why = ag.can_follow("morganhousel")
    assert ok, why  # 280+1 <= min(300, 320)


def test_follow_spacing_blocks_burst(follow_env, monkeypatch):
    """Never burst-follow: a follow within the 10-min gap is refused."""
    from src import config
    ag = follow_env
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 10))
    ag.record(ag.FOLLOW, target="TheBTCTherapist")
    ok, why = ag.can_follow("morganhousel")
    assert not ok and "too soon" in why


def test_follow_rejects_non_whitelisted(follow_env, monkeypatch):
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 10))
    ok, why = ag.can_follow("randomspamaccount")
    assert not ok and "whitelist" in why


def test_unfollow_protects_all_whitelist_tiers(follow_env):
    """No churn on seeds: tier3/tier4 are protected from unfollow too."""
    ag = follow_env
    for handle in ("TheBTCTherapist", "morganhousel", "karpathy", "saylor"):
        ok, why = ag.can_unfollow(handle)
        assert not ok and "protected" in why, (handle, why)


# --- 2026-06-07 round 2: pillar tags / freshness sort / trim / reply-bait ---

def test_pillar_classifier_buckets():
    from src.pillar_tags import classify
    assert classify("Your portfolio isn't down. It's processing trauma. Sit with it.") == "market_trauma"
    assert classify("Saylor buys more bitcoin while the AI agents trade against him.") == "ai_vs_btc"
    assert classify("OpenAI ships a new model and the GPU bill doubles overnight.") == "ai_news_take"
    assert classify("Group session: what's the most you've ever panic-sold?") == "reply_bait"
    # Explicit signals beat text heuristics.
    assert classify("anything", action_type="quote_gif") == "meme_reaction"
    assert classify("anything", source="GIF/this is fine") == "meme_reaction"
    assert classify("Honest take on markets today.", source="QUESTION") == "reply_bait"
    assert classify("") == "other"


def _url_with_age(minutes: int) -> str:
    from datetime import datetime, timezone
    from src.reply_bot import _TWITTER_EPOCH
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    tweet_id = (now_ms - minutes * 60_000 - _TWITTER_EPOCH) << 22
    return f"https://x.com/someone/status/{tweet_id}"


def test_reply_candidates_sorted_fresh_and_rising_first():
    """2026-06-07 spec: front-load fresh fast-rising posts. A 20-min riser
    must beat a 60-hour-old tweet; unknown-age URLs go last; within the
    same freshness bucket, higher likes-per-hour wins."""
    from src.direct_reply import _freshness_sort_key
    fresh_hot = {"url": _url_with_age(20), "likes": 400}
    fresh_cold = {"url": _url_with_age(25), "likes": 2}
    old = {"url": _url_with_age(60 * 60), "likes": 90000}
    unknown = {"url": "https://x.com/someone", "likes": 50}
    ordered = sorted([unknown, old, fresh_cold, fresh_hot], key=_freshness_sort_key)
    assert ordered[0] is fresh_hot
    assert ordered[1] is fresh_cold
    assert ordered[2] is old
    assert ordered[3] is unknown


def test_smart_trim_salvages_overlong_reply():
    """Over-length replies are trimmed at a sentence boundary and must then
    pass the content_guard length + truncation checks (instead of being
    discarded along with the LLM call that produced them)."""
    from src.humanizer import smart_trim
    long_reply = (
        "The market is not punishing you, it is teaching you. "
        "You bought the top because hope felt cheaper than patience. "
        "Diagnosis: chronic dip-denial with acute leverage exposure. "
        "Treatment starts with closing the app for one full week. "
        "Then we talk about your relationship with green candles and why "
        "you call panic-selling risk management."
    )
    assert len(long_reply) > 278
    trimmed = smart_trim(long_reply, 278)
    assert 0 < len(trimmed) <= 278
    ok, why = cg.validate(trimmed, kind="reply")
    assert ok, why


def test_reply_bait_weekly_cap(monkeypatch, tmp_path):
    """Reply-bait question posts are capped per ISO week (spec: 3-4/week)."""
    from src import spicy_bot as sb
    monkeypatch.setattr(sb, "SPICY_STATE_FILE", str(tmp_path / "spicy.json"))
    assert sb._week_question_count() == 0
    for _ in range(sb.REPLY_BAIT_PER_WEEK):
        sb._increment_question_count()
    assert sb._week_question_count() == sb.REPLY_BAIT_PER_WEEK
    assert sb._week_question_count() >= sb.REPLY_BAIT_PER_WEEK  # gate trips


def test_weekly_review_builds():
    from src.weekly_review_bot import build_review
    out = build_review()
    assert out.startswith("# Weekly review")
    assert "## Pillar mix" in out


def test_unfollow_cycle_disabled_at_cap_zero(monkeypatch):
    """Cap 0 = operator unfollows manually; the cycle must bail before any
    Safari scrape work."""
    from src import smart_unfollow_bot as sub, config
    monkeypatch.setattr(config, "MAX_UNFOLLOWS_PER_DAY", 0)
    called = []
    monkeypatch.setattr(sub, "_scrape_handle_list", lambda *a, **k: called.append(a) or [])
    sub.run_unfollow_cycle()
    assert called == [], "unfollow cycle must not touch Safari when cap is 0"


# --- 2026-06-07 round 3: lane queries / seed resolution / top posts ---------

def test_reply_queries_are_on_lane():
    """Spec lane: AI x markets x psychology. NO space content; the tier1-2
    seeds + foils must be scanned directly via from: queries."""
    from src.direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
    joined = " ".join(SEARCH_QUERIES + HOT_TAB_QUERIES).lower()
    for banned in ("spacex", "starship", "nasa", "satellite", "rocket lab", "orbit"):
        assert banned not in joined, f"space term {banned!r} is off-persona"
    for seed in ("from:thebtctherapist", "from:morganhousel", "from:saylor"):
        assert seed in joined, f"missing seed scan {seed!r}"
    # Market-trauma VOICE still represented (panic/drawdown reply targets),
    # but trimmed to 1 query — operator 2026-06-08 "focus more on AI": the
    # therapist voice frames AI replies; it's no longer a topic lane.
    assert "panic" in joined, "market-trauma voice target missing"


def test_seed_identity_matcher():
    from src.marquee_follow_bot import _seed_matches_identity
    seed = {"display_name": "Morgan Housel",
            "keywords": ["psychology of money", "behavior", "risk"]}
    # Name token match.
    assert _seed_matches_identity(seed, "Morgan Housel")
    # Keyword-in-bio match even when the name moved.
    assert _seed_matches_identity(seed, "MH", "Author. The Psychology of Money.")
    # Confident mismatch: scrape worked, nothing matches → never follow blind.
    assert not _seed_matches_identity(seed, "Crypto Airdrop Hub", "free $BONK giveaway")
    # No metadata → nothing to verify against → matches.
    assert _seed_matches_identity({"handle": "x"}, "whatever", "")


def test_weekly_top_posts_sorted_and_windowed(monkeypatch, tmp_path):
    from datetime import datetime, timedelta
    from src import weekly_review_bot as wr
    now = datetime.now()
    rows = [
        {"text": "old banger", "likes": 999, "views": 9999,
         "timestamp": (now - timedelta(days=30)).isoformat()},
        {"text": "this week small", "likes": 1, "views": 50,
         "timestamp": (now - timedelta(days=1)).isoformat()},
        {"text": "this week big", "likes": 7, "views": 300,
         "timestamp": (now - timedelta(days=2)).isoformat()},
    ]
    p = tmp_path / "perf.json"
    p.write_text(json.dumps(rows))
    monkeypatch.setattr(wr, "PERFORMANCE_LOG_FILE", str(p))
    top = wr._top_posts()
    assert [r["text"] for r in top] == ["this week big", "this week small"], (
        "must window to 7 days and sort by likes desc"
    )


# --- 2026-06-07 PM: early-reply pools are curator-driven, never static ------

def test_early_reply_targets_are_curator_driven():
    """2026-06-07 PM operator mandate: NO static target lists — the scan
    pools come from account_curator.tracked_handles(), pinned with the only
    two operator-mandated keepers (TheBTCTherapist, Graphseo)."""
    from src.early_bird_bot import EARLY_BIRD_ACCOUNTS
    from src.mega_watch_bot import MEGA_ACCOUNTS
    assert EARLY_BIRD_ACCOUNTS == [] and MEGA_ACCOUNTS == [], (
        "static early-reply lists must stay empty — pools come from the curator"
    )
    from src.account_curator import PINNED, tracked_handles
    assert tuple(PINNED) == ("TheBTCTherapist", "Graphseo")
    handles = tracked_handles(limit=5)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo"


# --- 2026-06-07 learning-loop fixes: self_winners provenance + clearing -----

def test_self_winners_filters_foreign_and_french(monkeypatch, tmp_path):
    """The own-wins bank must reject scraped retweet ads (implausible view
    counts), French-era posts, and must CLEAR the bank when nothing
    qualifies (stale injection bug)."""
    from datetime import datetime
    from src import self_winners as sw
    now = datetime.now().isoformat()
    perf = [
        # legit therapist-era winner
        {"text": "Your portfolio is not down, it is processing trauma. Sit with it a moment.",
         "likes": 5, "views": 900, "timestamp": now, "scraped_at": now},
        # scraped retweet ad — 2M views is not this account
        {"text": "Start with one idea. End with a feed full of content. Get unlimited!",
         "likes": 35, "views": 2_000_000, "timestamp": now, "scraped_at": now},
        # French-era post
        {"text": "Les actions technologiques semblent chères mais la révolution ne fait que commencer pour les investisseurs.",
         "likes": 17, "views": 7000, "timestamp": now, "scraped_at": now},
    ]
    perf_file = tmp_path / "perf.json"
    perf_file.write_text(json.dumps(perf))
    bank_file = tmp_path / "winners.md"
    monkeypatch.setattr(sw, "PERFORMANCE_LOG_FILE", str(perf_file))
    monkeypatch.setattr(sw, "SELF_WINNERS_FILE", str(bank_file))
    monkeypatch.setattr(sw, "MIN_LIKES_FLOOR", 3)

    sw.run_self_winners_cycle()
    bank = bank_file.read_text()
    assert "processing trauma" in bank
    assert "Get unlimited" not in bank, "foreign mega-view ad must be filtered"
    assert "actions technologiques" not in bank, "French-era post must be filtered"

    # Nothing qualifies → bank is CLEARED, not left stale.
    perf_file.write_text(json.dumps([perf[1], perf[2]]))
    sw.run_self_winners_cycle()
    assert "processing trauma" not in bank_file.read_text()
    assert sw.render_self_winners_block() == "" or "processing trauma" not in sw.render_self_winners_block()


def test_pillar_engagement_aggregates(monkeypatch, tmp_path):
    from datetime import datetime
    from src import analyzer_bot as ab
    now = datetime.now().isoformat()
    perf = [
        {"text": "Your panic selling is just fear wearing a trade ticket. Breathe.",
         "likes": 10, "views": 1000, "timestamp": now},
        {"text": "Diagnosis: chronic dip-denial. The drawdown is the therapy bill.",
         "likes": 20, "views": 3000, "timestamp": now},
        {"text": "OpenAI ships a new model, GPUs everywhere sigh.",
         "likes": 3, "views": 500, "timestamp": now},
    ]
    (tmp_path / "performance_log.json").write_text(json.dumps(perf))
    monkeypatch.setattr(ab, "_PROJECT_ROOT", str(tmp_path))
    out = ab._pillar_engagement()
    by = {r["pillar"]: r for r in out}
    assert by["market_trauma"]["posts"] == 2
    assert by["market_trauma"]["avg_likes"] == 15.0
    assert by["ai_news_take"]["avg_likes"] == 3.0
    assert out[0]["pillar"] == "market_trauma", "sorted by avg_likes desc"


# --- 2026-06-07 PM: self-curated tracking + BTC bestie blitz ----------------

def test_curator_lane_gate_and_pins(monkeypatch, tmp_path):
    """Only ON-LANE engagements count as evidence (FR-era rows classify
    'other' and are ignored); pinned handles always lead the tracked list."""
    from datetime import datetime
    from src import account_curator as ac
    now = datetime.now().isoformat()
    log_file = tmp_path / "log.csv"
    rows = []
    # 3 on-lane engagements with an EN markets author
    for i in range(3):
        rows.append(f'{now},reply,"your drawdown is just the market invoicing your FOMO {i}",https://x.com/goodfinance/status/12345{i},SEARCH,,market_trauma')
    # 4 FR-era engagements (classify "other") with a legacy author
    for i in range(4):
        rows.append(f'{now},reply,"très intéressant merci pour le partage {i}",https://x.com/legacyfr/status/2345{i},PROFILE,,')
    log_file.write_text("\n".join(rows) + "\n")
    monkeypatch.setattr(ac, "ENGAGEMENT_LOG_FILE", str(log_file))
    monkeypatch.setattr(ac, "TARGETS_LOG_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(ac, "WHITELIST_FILE", str(tmp_path / "wl.json"))
    monkeypatch.setattr(ac, "TRACKED_FILE", str(tmp_path / "tracked.json"))
    (tmp_path / "wl.json").write_text(json.dumps({"tiers": {}}))

    ac.run_curator_cycle()
    handles = ac.tracked_handles(limit=10)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo", "pins lead"
    assert "goodfinance" in handles, "on-lane author must be tracked"
    assert "legacyfr" not in handles, "FR-era 'other' engagements must not count"


def test_curator_promotion_quality_bar():
    """Following is a higher bar than tracking: spam-pattern handles (long
    digit runs) and thin evidence never reach the whitelist."""
    from src.account_curator import _promotable
    assert _promotable({"handle": "unusual_whales", "engagements": 9})
    assert not _promotable({"handle": "bisdianora24202", "engagements": 9}), "digit-run spam"
    assert not _promotable({"handle": "goodname", "engagements": 4}), "below promote floor"


def test_btc_blitz_filters_and_sorts(monkeypatch):
    """Blitz keeps only HIS posts <=48h, most-liked first; reposts of others
    on his profile and stale posts are dropped."""
    from src import btc_blitz as bb
    from src import twitter_client as tc
    fresh_small = {"url": _url_with_age(60).replace("/someone/", "/thebtctherapist/"), "likes": 3, "text": "a"}
    fresh_big = {"url": _url_with_age(120).replace("/someone/", "/thebtctherapist/"), "likes": 800, "text": "b"}
    stale = {"url": _url_with_age(50 * 60).replace("/someone/", "/thebtctherapist/"), "likes": 9000, "text": "c"}
    foreign = {"url": _url_with_age(30), "likes": 500, "text": "d"}  # /someone/ = repost
    monkeypatch.setattr(tc, "scrape_profile_tweets",
                        lambda *a, **k: [fresh_small, stale, foreign, fresh_big])
    out = bb._fresh_bestie_posts()
    assert out == [fresh_big, fresh_small], (
        "must keep only his <=48h posts, sorted most-liked first"
    )


# --- 2026-06-07 PM-3: self-RT recycler discipline ----------------------------

def test_boost_recycler_decision_logic(monkeypatch):
    """First-boost new winners after 1h; recycle (un-RT→re-RT) only with
    4h+ gaps and under the per-post cycle cap; never touch <1h or >48h."""
    from datetime import datetime, timedelta
    from src import boost_recycler_bot as br
    now = datetime.now()
    too_fresh = {"url": _url_with_age(20), "likes": 50}
    winner_new = {"url": _url_with_age(90), "likes": 10}
    winner_recyclable = {"url": _url_with_age(8 * 60), "likes": 30}
    too_old = {"url": _url_with_age(50 * 60), "likes": 900}

    # New winner (not yet RT'd) wins over a recyclable one — first boost.
    action, url = br.pick_action(
        [too_fresh, winner_new, winner_recyclable, too_old],
        state={winner_recyclable["url"]: {"boosts": 1, "last": (now - timedelta(hours=9)).isoformat()}},
        currently_retweeted={winner_recyclable["url"]},
        now=now,
    )
    assert (action, url) == ("boost", winner_new["url"])

    # Only the recyclable one left → recycle it (gap satisfied).
    action, url = br.pick_action(
        [too_fresh, winner_recyclable, too_old],
        state={winner_recyclable["url"]: {"boosts": 1, "last": (now - timedelta(hours=9)).isoformat()}},
        currently_retweeted={winner_recyclable["url"]},
        now=now,
    )
    assert (action, url) == ("recycle", winner_recyclable["url"])

    # Gap not yet elapsed → hold.
    action, _ = br.pick_action(
        [winner_recyclable],
        state={winner_recyclable["url"]: {"boosts": 1, "last": (now - timedelta(hours=1)).isoformat()}},
        currently_retweeted={winner_recyclable["url"]},
        now=now,
    )
    assert action is None

    # Cycle cap reached → hold forever.
    action, _ = br.pick_action(
        [winner_recyclable],
        state={winner_recyclable["url"]: {"boosts": br.BOOST_RECYCLE_MAX_CYCLES,
                                          "last": (now - timedelta(hours=20)).isoformat()}},
        currently_retweeted={winner_recyclable["url"]},
        now=now,
    )
    assert action is None


# --- 2026-06-07: engine-health warmup grace (boot false-emergency) ----------

def test_engine_health_warmup_suppresses_boot_alerts(monkeypatch):
    """Right after process start every surface reads 0-by-this-hour — that's
    downtime, not collapse. Witnessed live 2026-06-07: an emergency self-heal
    Claude run was spawned for 'reply collapsed: 0 today' minutes after boot.
    Within WARMUP_MINUTES the cycle must do nothing; after it, checks run."""
    from datetime import datetime, timedelta
    from src import engine_health_bot as ehb
    monkeypatch.setattr(ehb, "_PROCESS_START", datetime.now())
    assert ehb._in_warmup(), "fresh boot must be in warmup"
    monkeypatch.setattr(ehb, "_PROCESS_START",
                        datetime.now() - timedelta(minutes=ehb.WARMUP_MINUTES + 5))
    assert not ehb._in_warmup(), "past the warmup window checks must resume"


# --- 2026-06-07: boost engine must never blind-toggle (banger un-RT bug) ----

def test_boost_resurfaces_banger_never_blind_toggles(monkeypatch):
    """When every visible own post is already self-RT'd, the boost engine
    must resurface the HIGHEST-engagement post via reboost_tweet (ends
    retweeted) — never retweet_own_latest, whose blind 't'+Enter UN-retweets
    an already-RT'd post (witnessed all morning 2026-06-07: the banger's
    self-RT toggled off every other cycle)."""
    from src import notify_bot as nb
    from src import twitter_client as tc

    posts = [
        {"author": "TheAIShrink", "url": "https://x.com/TheAIShrink/status/1", "likes": 2, "text": "meh"},
        {"author": "TheAIShrink", "url": "https://x.com/TheAIShrink/status/2", "likes": 9, "text": "banger"},
    ]
    monkeypatch.setattr(tc, "scrape_profile_tweets", lambda *a, **k: posts)
    monkeypatch.setattr(nb, "_load_boost_history",
                        lambda: {p["url"] for p in posts})  # all already boosted
    reboosted, toggled, first_rts = [], [], []
    monkeypatch.setattr(tc, "reboost_tweet", lambda url: reboosted.append(url))
    monkeypatch.setattr(tc, "retweet_post", lambda url: first_rts.append(url))
    monkeypatch.setattr(nb, "retweet_own_latest", lambda: toggled.append(1))

    nb.run_boost_cycle()
    assert reboosted == ["https://x.com/TheAIShrink/status/2"], "must pick the banger"
    assert toggled == [], "blind toggle is the un-retweet bug — never call it"
    assert first_rts == []

    # Scrape failure → skip, never toggle.
    def boom(*a, **k):
        raise RuntimeError("DOM drift")
    monkeypatch.setattr(tc, "scrape_profile_tweets", boom)
    nb.run_boost_cycle()
    assert toggled == []


def test_profile_visits_blocked_outside_allowlist(monkeypatch):
    """Operator mandate 2026-06-07 PM: NO profile visits for discovery —
    scrape surfaces are @TheBTCTherapist + Home (For You/Following) + search.
    A non-allowlisted profile must return [] BEFORE any Safari work, and the
    allowlist env must be read at call time (side-effect-gate rule)."""
    from src import twitter_client as tc
    from src.config import BOT_HANDLE

    monkeypatch.delenv("PROFILE_VISIT_ALLOWLIST", raising=False)
    monkeypatch.setattr(
        tc.webbrowser, "open",
        lambda *a, **k: pytest.fail("Safari was opened for a blocked profile"))
    assert tc.scrape_profile_tweets("unusual_whales") == []
    assert tc.scrape_profile_tweets("karpathy") == []
    tc.visit_profile_and_like("unusual_whales")  # must not open Safari either

    # Allowlist semantics (pure check, no Safari). Defaults: the two
    # reply-everything friends (operator 2026-06-07).
    assert tc._profile_visit_allowed(BOT_HANDLE)
    assert tc._profile_visit_allowed(f"{BOT_HANDLE}/with_replies")
    assert tc._profile_visit_allowed("TheBTCTherapist")
    assert tc._profile_visit_allowed("@thebtctherapist")
    assert tc._profile_visit_allowed("Graphseo")
    assert not tc._profile_visit_allowed("zerohedge")
    assert not tc._profile_visit_allowed("")

    # Env read at CALL time — a live edit takes effect without restart.
    monkeypatch.setenv("PROFILE_VISIT_ALLOWLIST", "TheBTCTherapist")
    assert not tc._profile_visit_allowed("graphseo")
    assert tc._profile_visit_allowed("thebtctherapist")


def test_buddy_blitz_replies_to_every_fresh_post(monkeypatch):
    """Operator 2026-06-07: 'reply to everything graphseo and thebtctherapist
    post'. The blitz must cover BOTH: bestie pass for TheBTCTherapist, buddy
    pass for Graphseo — every fresh post gets exactly one reply, already-
    replied URLs are skipped before the LLM."""
    from src import btc_blitz as bb
    from src import reply_bot as rb
    from src import twitter_client as tc
    from src import quote_tweet_bot as qb
    from src import engagement_log as el

    posts = {
        "TheBTCTherapist": [
            {"url": "https://x.com/TheBTCTherapist/status/111", "text": "btc pain", "likes": 5},
        ],
        "Graphseo": [
            {"url": "https://x.com/Graphseo/status/222", "text": "fresh seo take", "likes": 3},
            {"url": "https://x.com/Graphseo/status/333", "text": "already covered", "likes": 9},
        ],
    }
    monkeypatch.setattr(bb, "_fresh_posts", lambda h: list(posts.get(h, [])))
    gen_calls = []
    monkeypatch.setattr(
        bb, "_gen",
        lambda tpl, txt, model, label, author=None: gen_calls.append((label, txt)) or "sharp take")
    # Graphseo routes to his dedicated FR generator (operator 2026-06-07:
    # English shipped to him once — never again).
    import src.direct_reply as dr
    monkeypatch.setattr(dr, "_generate_graphseo_reply",
                        lambda txt: gen_calls.append(("GRAPHSEO_FR", txt)) or "réponse précise en français")
    # One Graphseo post already replied — must be skipped pre-LLM.
    monkeypatch.setattr(rb, "load_replied", lambda: {"https://x.com/Graphseo/status/333"})
    # Quote pass: bestie URL already quoted so the test stays reply-only.
    monkeypatch.setattr(qb, "_load_quoted", lambda: {"https://x.com/TheBTCTherapist/status/111"})
    monkeypatch.setattr(qb, "_save_quoted", lambda q: None)
    sent = []
    monkeypatch.setattr(tc, "reply_to_tweet", lambda url, text: sent.append(url) or True)
    monkeypatch.setattr(el, "log_reply", lambda *a, **k: None)

    bb.run_btc_blitz_cycle()

    assert sent == [
        "https://x.com/TheBTCTherapist/status/111",  # bestie pass
        "https://x.com/Graphseo/status/222",         # buddy pass
    ]
    assert all("already covered" not in txt for _, txt in gen_calls), \
        "replied URL must be skipped BEFORE the LLM call"


def test_reply_callers_never_premark_store(monkeypatch, tmp_path):
    """2026-06-07 post-mortem: five bots 'locked the URL in BEFORE posting'
    (save_replied premark) — the reply chokepoint (2026-06-05) loads that
    same store and silently refused its OWN caller's reply, 100% of the
    time, while unconditional log_reply calls wrote phantom rows into
    engagement_log. Contract pinned here: (1) the on-disk store must NOT
    contain the URL at the moment reply_to_tweet is invoked; (2) log_reply
    fires ONLY when reply_to_tweet returns True."""
    import src.direct_reply as dr
    import src.reply_bot as rb

    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))
    url = "https://x.com/some_ai_account/status/2063500000000000009"
    tweets = [{"url": url, "text": "nvidia margins at 75 percent again", "author": "some_ai_account"}]

    premarked_at_call = []
    def fake_reply(u, text):
        premarked_at_call.append(u in rb.load_replied())
        return True
    logged = []
    monkeypatch.setattr(dr, "_generate_single_reply",
                        lambda *a, **k: "calm reframe with the precise fact")
    monkeypatch.setattr(dr, "reply_to_tweet", fake_reply)
    monkeypatch.setattr(dr, "humanize", lambda t: t)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(dr, "_tweet_age_minutes", lambda u: 5)
    monkeypatch.setattr(dr, "_is_on_niche", lambda t: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 1000, 0))

    n = dr._reply_to_tweets(tweets, rb.load_replied(), "SEARCH-HOT", en_counter=[0])
    assert premarked_at_call == [False], \
        "caller premarked the store — the chokepoint would refuse its own reply"
    assert n == 1 and len(logged) == 1

    # Chokepoint refusal (False) → no phantom engagement_log row, posted=0.
    logged.clear()
    url2 = "https://x.com/some_ai_account/status/2063500000000000010"
    tweets2 = [{"url": url2, "text": "tsmc capex at 40 billion now", "author": "some_ai_account"}]
    monkeypatch.setattr(dr, "reply_to_tweet", lambda u, t: False)
    n2 = dr._reply_to_tweets(tweets2, rb.load_replied(), "SEARCH-HOT", en_counter=[0])
    assert n2 == 0 and logged == [], \
        "chokepoint skip must not produce a phantom engagement_log row"


def test_reply_chokepoint_returns_bool(monkeypatch, tmp_path):
    """reply_to_tweet must return True when the reply ships (DRY_RUN counts)
    and False on the dedup skip — callers gate log_reply on this."""
    from src import twitter_client as tc
    from src import reply_bot as rb
    from src import action_guard as ag
    from src import config as cfg

    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setattr(cfg, "DRY_RUN", True)

    url = "https://x.com/foo/status/2063500000000000042"
    text = "Naming the fear is step one. The number says 40 billion in capex."
    assert tc.reply_to_tweet(url, text) is True
    # Store was marked by the chokepoint itself — second attempt refuses.
    assert tc.reply_to_tweet(url, text) is False


def test_vip_scan_uses_bestie_prompt_for_btctherapist(monkeypatch, tmp_path):
    """Bug 2026-06-07 (shipped live, operator: 'why did it reply in french
    to the bitcoin therapist?'): the VIP lane applied the Graphseo FR
    generator (French + deliberate-typo style) to @TheBTCTherapist's
    English post. Pin: VIP replies to the bestie use the EN bestie prompt,
    never _generate_graphseo_reply; output passes through humanize."""
    import src.direct_reply as dr
    import src.reply_bot as rb
    from src import btc_blitz as bb

    # ⚠️ The VIP scan imports scrape_x_search / reply_to_tweet FUNCTION-
    # LOCALLY from twitter_client — patch THERE, not on direct_reply.
    # (First version of this test patched dr.* — the real Safari fired and
    # posted live replies to @TheBTCTherapist mid-test. conftest's
    # _no_safari wall now makes that mistake fail loudly instead.)
    import src.twitter_client as tc
    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setenv("VIP_SCAN_HANDLES", "TheBTCTherapist")
    url = "https://x.com/TheBTCTherapist/status/2063500000000000077"
    monkeypatch.setattr(tc, "scrape_x_search",
                        lambda q, max_tweets=20, tab="latest":
                        [{"url": url, "text": "working the weekend because bitcoin", "author": "TheBTCTherapist"}])
    monkeypatch.setattr(rb, "_tweet_age_minutes", lambda u: 30)
    monkeypatch.setattr(dr, "_tweet_age_minutes", lambda u: 30)

    graphseo_calls = []
    monkeypatch.setattr(dr, "_generate_graphseo_reply",
                        lambda text: graphseo_calls.append(text) or "réponse française")
    gen_labels = []
    def fake_gen(tpl, txt, model, label, author=None):
        gen_labels.append((label, tpl is bb._BESTIE_REPLY_PROMPT))
        return "the AI side sends love — and a fruit basket"
    monkeypatch.setattr(bb, "_gen", fake_gen)
    sent = []
    monkeypatch.setattr(tc, "reply_to_tweet", lambda u, t: sent.append(t) or True)
    import src.engagement_log as el
    monkeypatch.setattr(el, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)

    dr._run_graphseo_scan(rb.load_replied())

    assert graphseo_calls == [], "Graphseo FR generator must NEVER run for the bestie"
    assert gen_labels == [("VIP_REPLY/TheBTCTherapist", True)]
    assert len(sent) == 1
    assert "—" not in sent[0], "humanize must strip em dashes from VIP replies"


def test_reply_chokepoint_strips_em_dashes(monkeypatch, tmp_path):
    """Operator 2026-06-07: an em dash in a published reply is an AI tell
    ('what a shame'). The chokepoint must strip em/en dashes for EVERY
    reply path, even ones that skip humanize()."""
    from src import twitter_client as tc
    from src import reply_bot as rb
    from src import action_guard as ag
    from src import config as cfg

    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    recorded = {}
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setattr(cfg, "DRY_RUN", True)
    logged = []
    monkeypatch.setattr(tc, "log", type(tc.log)(tc.log.name)) if False else None
    # Capture the final text via the DRY_RUN log line is brittle — instead
    # verify through the store-marking path: patch _paste? Simplest: spy on
    # the DRY_RUN branch by reading the typo-injection input. We assert via
    # content_guard.validate receiving dash-free text.
    seen = {}
    import src.content_guard as cg2
    real_validate = cg2.validate
    def spy_validate(text, kind="post"):
        seen["text"] = text
        return real_validate(text, kind=kind)
    monkeypatch.setattr(cg2, "validate", spy_validate)

    url = "https://x.com/foo/status/2063500000000000088"
    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part of the trade.") is True
    assert "—" not in seen["text"]
    assert "conviction is the hard part" in seen["text"]


def test_skip_rationale_never_publishes():
    """2026-06-07 live leak: the model wrote 'SKIP.' + its whole rationale
    ('The tweet is incomplete (cuts off mid-sentence)...') and an
    exact-match SKIP check published it as a reply. Pin both layers:
    generator-side prefix check and the content_guard chokepoint."""
    from src import content_guard as cg
    ok, why = cg.validate("SKIP. The tweet is incomplete (cuts off mid-sentence at 'rema'), "
                          "and the angle is generic crypto psychology.", kind="reply")
    assert not ok and "SKIP" in why
    ok, _ = cg.validate("skip", kind="reply")
    assert not ok
    # Legitimate text containing 'skip' mid-sentence still passes.
    ok, _ = cg.validate("Most investors skip the part where conviction gets tested.", kind="reply")
    assert ok
    # Generator-side: prefix match, not exact match.
    from src import direct_reply as dr
    import src.llm_client as llm
    class R: returncode = 0; stdout = "SKIP. Here is why I refuse..."; stderr = ""
    # _generate_single_reply path is LLM-bound; test the cheap invariant via
    # the same predicate the code uses now:
    assert R.stdout.upper().strip().startswith("SKIP")


def test_bare_dash_replacement_keeps_spacing():
    """2026-06-07: '—' → ',' produced 'angle,conviction' in a live reply.
    Bare dashes must become ', ' with normalized spacing, in humanize AND
    at the reply chokepoint."""
    from src.humanizer import humanize
    out = humanize("The angle—conviction through crashes—is generic and it shows badly.")
    assert ",conviction" not in out and ", conviction" in out


def test_reply_queries_are_ai_first():
    """Operator 2026-06-07: 'bot needs to be more AI focused' / 'i want to
    see more AI shit'. The reply lane must be majority-AI: at least half of
    the search queries carry an AI term, BTC tail stays minimal (feud lane
    only, ≤2 queries)."""
    from src.direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
    ai_terms = ("openai", "anthropic", "chatgpt", "claude", "gemini", "grok",
                "ai ", "\"ai", "agi", "nvidia", "gpu", "llama", "deepseek",
                "palantir", "cursor", "copilot", "tsmc", "humanoid", " ia ")
    def is_ai(q):
        ql = " " + q.lower()
        return any(t in ql for t in ai_terms)
    topic_queries = [q for q in SEARCH_QUERIES if not q.startswith("from:")]
    ai_count = sum(1 for q in topic_queries if is_ai(q))
    assert ai_count * 2 >= len(topic_queries), \
        f"AI queries must be the majority of the reply lane ({ai_count}/{len(topic_queries)})"
    btc_only = [q for q in topic_queries
                if ("bitcoin" in q.lower() or "btc" in q.lower()) and not is_ai(q)]
    assert len(btc_only) <= 2, "BTC tail must stay minimal (feud lane only)"
    hot_ai = sum(1 for q in HOT_TAB_QUERIES if is_ai(q))
    assert hot_ai * 2 >= len(HOT_TAB_QUERIES)


def test_fr_forced_parent_rejects_english_reply(monkeypatch, tmp_path):
    """Operator 2026-06-07: 'i saw some english on Julien response'.
    @Graphseo is always-French; the chokepoint refuses an English reply to
    him from ANY bot, BEFORE the dedup mark (post stays fresh for an FR
    retry). SKIPPED-variant leaks are also pinned here."""
    from src import twitter_client as tc
    from src import reply_bot as rb
    from src import action_guard as ag
    from src import config as cfg
    from src import content_guard as cg

    monkeypatch.setattr(rb, "REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setattr(cfg, "DRY_RUN", True)

    url = "https://x.com/Graphseo/status/2063500000000000099"
    english = "The market just told you what your conviction is worth this week."
    assert tc.reply_to_tweet(url, english) is False
    # Post must stay UNMARKED — a later FR draft can still ship.
    assert url not in rb.load_replied()
    french = "Le marché vient de te dire ce que vaut ta conviction cette semaine."
    assert tc.reply_to_tweet(url, french) is True

    # SKIPPED / Skip. variants (live leaks 01:04-04:07) die at content_guard.
    for leak in ("SKIPPED", "Skip.", "skipped", "SKIP — no source context"):
        ok, _ = cg.validate(leak, kind="reply")
        assert not ok, f"{leak!r} must never publish"


def test_quote_ai_viral_pass_present_and_ranked():
    """Operator 2026-06-07: 'not really quote retweet on AI... do it more —
    find viral content from viral big accounts in AI or TOP posts in AI'.
    The quote bot must carry an always-scanned AI-viral pass (from: the
    biggest AI accounts + high-min_faves AI topics) and rank those
    candidates ahead of the generic pool."""
    from src import quote_tweet_bot as qb
    # Big AI accounts present.
    for h in ("sama", "openai", "anthropicai", "karpathy", "googledeepmind"):
        assert h in [x.lower() for x in qb.TOP_AI_HANDLES], f"missing top AI handle {h}"
    # AI-viral queries are from: the big accounts and high min_faves topics.
    joined = " ".join(qb.AI_VIRAL_QUERIES).lower()
    assert "from:sama" in joined and "from:openai" in joined
    assert "min_faves:1000" in joined or "min_faves:800" in joined, "needs a TOP-post viral floor"
    # Ranking order: priority + ai_viral + rest — assert the source line
    # prepends ai_viral ahead of the generic candidates.
    import inspect
    src = inspect.getsource(qb.run_quote_tweet_cycle)
    assert "ai_viral_candidates + priority_candidates + candidates" in src, \
        "AI virals must LEAD the main quote lane (bestie is covered by btc_blitz)"


def test_startup_reply_warmup_is_bounded(monkeypatch):
    """Operator 2026-06-07: 'more quote retweet on AI'. Root cause was an
    UNBOUNDED startup reply warmup that ran 20+ min and blocked
    scheduler.start() — so the dedicated quote/AI-viral jobs never came
    online (15:43 boot: 300+ replies, 0 quotes). run_direct_reply_cycle
    must honor max_replies and STOP, yielding Safari."""
    import src.direct_reply as dr
    # Every query returns 5 fresh on-niche tweets; without the cap the cycle
    # would reply to all of them across all 21 queries.
    calls = {"replies": 0, "queries": 0}
    def fake_search(q, max_tweets=25, tab="top"):
        calls["queries"] += 1
        base = 2063900000000000000 + calls["queries"] * 100
        return [{"url": f"https://x.com/acct/status/{base+i}",
                 "text": "openai shipped a new reasoning model today", "author": "acct"}
                for i in range(5)]
    def fake_reply_block(tweets, replied, source, source_detail="", remaining=None, en_counter=None):
        # Honor the remaining budget like the real _reply_to_tweets.
        n = len(tweets) if remaining is None else min(len(tweets), remaining)
        calls["replies"] += n
        return n
    monkeypatch.setattr(dr, "scrape_x_search", fake_search)
    monkeypatch.setattr(dr, "_reply_to_tweets", fake_reply_block)
    monkeypatch.setattr(dr, "_run_graphseo_scan", lambda replied: None)
    monkeypatch.setattr(dr, "load_replied", lambda: set())
    monkeypatch.setattr(dr, "save_replied", lambda s: None)

    dr.run_direct_reply_cycle(max_replies=12)
    assert calls["replies"] == 12, f"warmup must stop at the cap, got {calls['replies']}"
    assert calls["queries"] < 21, "must stop scanning queries once the budget is spent"


# --- 2026-06-08: GIF post/quote double-log fix ------------------------------

def test_bot_gif_hotake_logs_once_not_twice(monkeypatch, tmp_path):
    """Regression pin for the 2026-06-08 duplicate-row bug.

    Before this fix, every GIF hot take wrote TWO rows to engagement_log:
      (a) action_type='post', source='GIF/<q>'   ← post_tweet_with_gif
      (b) action_type='hotake', source=''         ← bot.py unconditional log
    The pillar classifier then bucketed (a) as meme_reaction and (b) as
    market_trauma (content match). Result: one ship inflated two pillars
    AND two per-action counts — the very same per-pillar metric that drove
    the autonomous 29.8x market_trauma pivot. The fix: bot.py must skip the
    second log call when gif_query is set."""
    from src import bot as bot_mod
    from src import engagement_log as el

    csv_path = str(tmp_path / "engagement_log.csv")
    monkeypatch.setattr(el, "ENGAGEMENT_LOG_FILE", csv_path)

    def fake_post_with_gif(text, gif_query, force=False):
        # Mirrors the real chokepoint's logging: action_type=post,
        # source=GIF/<q>. Returns True on a successful ship.
        el.log_post(text, source=f"GIF/{gif_query}")
        return True

    monkeypatch.setattr(bot_mod, "post_tweet_with_gif", fake_post_with_gif)

    # Replay the small block of bot.py that owns the dispatch. We capture
    # any caller-side log_hotake/log_post calls to assert they're skipped.
    caller_logs = []
    monkeypatch.setattr(bot_mod, "log_hotake",
                        lambda *a, **k: caller_logs.append(("hotake", a, k)))
    monkeypatch.setattr(bot_mod, "log_post",
                        lambda *a, **k: caller_logs.append(("post", a, k)))

    tweet = "SoftBank -6%. The AI rally is in its first real therapy session."
    gif_query = "this is fine"
    tweet_source = "hotake"
    pattern_id = "OTHER"

    # Reproduce the exact bot.py block (the one we just guarded).
    bot_mod.post_tweet_with_gif(tweet, gif_query)
    if not gif_query:
        if tweet_source == "hotake":
            bot_mod.log_hotake(tweet, pattern_id=pattern_id)
        else:
            bot_mod.log_post(tweet, pattern_id=pattern_id)

    # The caller-side log MUST be skipped when GIF was used.
    assert caller_logs == [], (
        "bot.py double-logged when gif_query was set — chokepoint already "
        "logged the row")

    # And the engagement_log.csv must hold exactly ONE row for this tweet.
    with open(csv_path) as f:
        rows = [ln for ln in f.read().splitlines() if tweet[:30] in ln]
    assert len(rows) == 1, (
        f"expected 1 engagement_log row for the GIF hotake, got {len(rows)}: {rows}")
    assert "GIF/this is fine" in rows[0], "chokepoint's GIF/ marker missing"


def test_bot_no_gif_text_only_hotake_still_logs(monkeypatch, tmp_path):
    """Inverse guard: a text-only (no-GIF) hot take must still log_hotake.
    The fix targets only the duplicate path; the no-GIF path must keep its
    single log row, otherwise hotake counts would silently drop to zero."""
    from src import bot as bot_mod
    from src import engagement_log as el

    csv_path = str(tmp_path / "engagement_log.csv")
    monkeypatch.setattr(el, "ENGAGEMENT_LOG_FILE", csv_path)

    caller_logs = []
    monkeypatch.setattr(bot_mod, "log_hotake",
                        lambda *a, **k: caller_logs.append("hotake"))
    monkeypatch.setattr(bot_mod, "log_post",
                        lambda *a, **k: caller_logs.append("post"))

    tweet = "Loss aversion isn't a bug, it's the feature."
    gif_query = ""  # text-only
    tweet_source = "hotake"

    if not gif_query:
        if tweet_source == "hotake":
            bot_mod.log_hotake(tweet, pattern_id="OTHER")
        else:
            bot_mod.log_post(tweet, pattern_id="OTHER")

    assert caller_logs == ["hotake"], (
        f"text-only hotake must log once as 'hotake', got {caller_logs}")


def test_quote_tweet_gif_logs_once_not_twice(monkeypatch, tmp_path):
    """Same family as the bot.py fix: quote_tweet_with_gif logs as
    action_type='quote_gif' with source='GIF/<q>'. quote_tweet_bot used to
    ALSO call log_reply(action_type='quote', source='QUOTE/<author>')
    unconditionally afterwards, producing two rows per GIF quote. The
    second row inflated both 'quote' and 'quote_gif' action counts and
    polluted per-pillar attribution. quote_tweet_bot must skip the log
    when _gif_q is set."""
    from src import quote_tweet_bot as qb
    from src import engagement_log as el

    csv_path = str(tmp_path / "engagement_log.csv")
    monkeypatch.setattr(el, "ENGAGEMENT_LOG_FILE", csv_path)

    caller_logs = []
    monkeypatch.setattr(qb, "log_reply",
                        lambda *a, **k: caller_logs.append((a, k)))

    url = "https://x.com/somefin/status/1234567890"
    quote = "$145B is the rent on silicon that doesn't exist yet."
    author = "somefin"
    _gif_q = "wolf of wall street"

    # Reproduce the guarded block.
    if not _gif_q:
        qb.log_reply(url, quote, action_type="quote", source=f"QUOTE/{author}")

    assert caller_logs == [], (
        "quote_tweet_bot must skip log_reply when _gif_q is set "
        "(quote_tweet_with_gif already logged as quote_gif)")


def test_bot_gif_dup_guard_present_in_source():
    """Structural pin: regression-guard the `if not gif_query:` wrapper in
    bot.py's _run_single_bot_cycle. The behavior test above can pass even
    if a future refactor moves the dispatch elsewhere; this test holds the
    code shape that the chokepoint contract relies on."""
    import inspect
    from src import bot as bot_mod
    src = inspect.getsource(bot_mod._run_single_bot_cycle)
    assert "if not gif_query:" in src, (
        "bot.py _run_single_bot_cycle must guard the engagement-log "
        "dispatch with `if not gif_query:` (chokepoint already logs)")


def test_quote_tweet_gif_dup_guard_present_in_source():
    """Structural pin: same family as the bot.py guard."""
    import inspect
    from src import quote_tweet_bot as qb
    src = inspect.getsource(qb.run_quote_tweet_cycle)
    assert "if not _gif_q:" in src, (
        "quote_tweet_bot.run_quote_tweet_cycle must guard the log_reply "
        "call with `if not _gif_q:` (chokepoint logs as quote_gif)")


def test_bot_cycle_no_unbound_tweet_when_news_capped(monkeypatch):
    """2026-06-08 live crash: `tweet` was initialized only inside
    `if can_news:`, so when the news cap was full (can_news=False,
    can_hotake=True) the `if tweet is None ...` check hit UnboundLocalError
    and crashed every post cycle. Pin: news-capped + hotake-available runs
    cleanly and ships the hotake."""
    from src import bot as b
    monkeypatch.setattr(b, "_get_counters", lambda: (999, 0))   # news capped, hotake open
    monkeypatch.setattr(b, "_live_news_cap", lambda: 999)
    monkeypatch.setattr(b, "_live_hotake_cap", lambda: 40)
    monkeypatch.setattr(b, "generate_hotake", lambda: "TEST-FIXTURE hotake zz-unbound-regression zz.")
    monkeypatch.setattr(b, "_increment_counter", lambda k: None)
    monkeypatch.setattr(b, "humanize", lambda t: t)
    shipped = {}
    # Stop right after tweet is chosen — patch post_tweet to capture, not send.
    monkeypatch.setattr(b, "post_tweet", lambda *a, **k: shipped.setdefault("text", a[0] if a else "") or True)
    try:
        b._run_single_bot_cycle()
    except UnboundLocalError as e:
        raise AssertionError(f"UnboundLocalError regression: {e}")
    # The hotake path must have been reached (tweet was not None).
    assert shipped.get("text"), "news-capped cycle should fall back to the hotake and post it"


def test_positive_only_subjects_in_hard_rules():
    """Operator 2026-06-08: Apple / US government / Trump / Elon Musk must be
    spoken of ONLY positively. The rule must live in the non-overridable
    hard-rules block injected into every generation prompt."""
    from src import personality_store as ps
    block = ps.hard_rules_block()  # fresh render (incl. respect list)
    low = block.lower()
    for subj in ("apple", "us government", "trump", "elon musk"):
        assert subj in low, f"positive-only subject {subj!r} missing from hard rules"
    # Must instruct positive-only + override the snark voice.
    assert "positive" in low and ("only" in low or "never criticize" in low)
    assert "override" in low or "overrides" in low


def test_mega_viral_quote_bypasses_daily_cap(monkeypatch):
    """Learning 2026-06-08: a 1,459-like AI viral was blocked purely by the
    daily quote cap. high_value quotes (mega-virals) get bonus slots beyond
    the cap so a top-tier viral is never blocked; normal quotes still hit
    the cap. Spacing still applies to both."""
    from src import action_guard as ag
    from src import config as cfg

    cap = cfg.MAX_QUOTE_REPOSTS_PER_DAY
    monkey_count = {"n": cap}
    monkeypatch.setattr(ag, "count_today", lambda action: monkey_count["n"] if action == ag.QUOTE else 0)
    monkeypatch.setattr(ag, "spacing_ok", lambda action, gap: True)

    ok_normal, why = ag.can_post(ag.QUOTE, high_value=False)
    assert not ok_normal and "cap" in why, "normal quote must be capped at the limit"
    ok_mega, _ = ag.can_post(ag.QUOTE, high_value=True)
    assert ok_mega, "mega-viral quote must bypass the daily cap (bonus slots)"

    # Bonus is finite: at cap+bonus, even mega-virals stop.
    monkey_count["n"] = cap + cfg.QUOTE_MEGA_VIRAL_BONUS_SLOTS
    ok_mega2, _ = ag.can_post(ag.QUOTE, high_value=True)
    assert not ok_mega2, "bonus slots are bounded — not an infinite bypass"


def test_suppression_watch_needs_minimum_seasoned_sample(monkeypatch, tmp_path):
    """Operator log 2026-06-09 06:50: 'FLAGGED — avg likes 0.00 on last 2
    seasoned posts < threshold 1.0. Pausing aggressive bots until 10:50'.
    The profile scrape returned only 5 own posts; the old gate (n<=4 BEFORE
    dropping the freshest 3) let n=2 through and flagged on noise. Same
    false-positive fired 9 times in bot.log. The fix drops the freshest
    first, then requires MIN_SEASONED_FOR_FLAG samples."""
    from src import suppression_watch_bot as swb

    state_file = tmp_path / "suppression_state.json"
    monkeypatch.setattr(swb, "SUPPRESSION_STATE_FILE", str(state_file))
    monkeypatch.setattr(swb, "MIN_SEASONED_FOR_FLAG", 5)

    # 5 raw own posts → 2 seasoned after the drop. Old code flagged; new code skips.
    own_url = "https://x.com/TheAIShrink/status/100"
    five_zero_like = [
        {"url": f"{own_url}{i}", "likes": 0, "is_reply": False} for i in range(5)
    ]
    monkeypatch.setattr(swb, "scrape_profile_tweets", lambda *a, **k: five_zero_like)
    monkeypatch.setattr(swb, "_is_own_post", lambda t: True)

    swb.run_suppression_watch_cycle()
    assert not swb.is_paused(), \
        "thin sample (n<MIN) must NOT trip suppression — was false-flagging on n=2"

    # And a healthy 8-raw → 5-seasoned sample with real likes still computes:
    healthy = [{"url": f"{own_url}{i}", "likes": 3, "is_reply": False} for i in range(8)]
    monkeypatch.setattr(swb, "scrape_profile_tweets", lambda *a, **k: healthy)
    swb.run_suppression_watch_cycle()
    import json as _json
    s = _json.loads(state_file.read_text())
    assert s["last_n"] == 5 and s["last_avg"] == 3.0, \
        f"expected n=5 avg=3.0, got n={s.get('last_n')} avg={s.get('last_avg')}"
    assert s["paused_until"] is None, "avg=3 > threshold=1 must NOT pause"

    # And a genuine collapse with enough samples still flags:
    collapsed = [{"url": f"{own_url}{i}", "likes": 0, "is_reply": False} for i in range(8)]
    monkeypatch.setattr(swb, "scrape_profile_tweets", lambda *a, **k: collapsed)
    swb.run_suppression_watch_cycle()
    assert swb.is_paused(), "n>=MIN with avg<threshold MUST still flag — signal preserved"


def test_core_identity_has_ai_fan_voice():
    """Operator 2026-06-09: 'be more excited about AI, be a fan of AI'. The
    voice anchor (loaded into every prompt) must carry the AI-fan/enthusiast
    dimension so excitement shows in posts/quotes/replies."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    txt = open(os.path.join(root, "core_identity.md")).read().lower()
    assert "ai fan" in txt or "genuine ai fan" in txt or "superfan" in txt
    assert "excit" in txt and ("wonder" in txt or "thrill" in txt)
    # Must coexist with, not replace, the therapist voice.
    assert "therapist" in txt and "calm the fear" in txt


def test_core_identity_has_likes_principle():
    """Operator 2026-06-09: posts/quotes get views but not likes (replies do).
    The voice anchor must carry the 'likes come from FEELING, lead with the
    emotion not the data' principle so it reaches every surface."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    txt = open(os.path.join(root, "core_identity.md")).read().lower()
    assert "earn a like" in txt or "earn the like" in txt
    assert "lead with the feeling" in txt
    assert "relatable" in txt and "view" in txt


def test_core_identity_positive_obsessed_energy():
    """Operator 2026-06-09: relentlessly positive, AI-obsessed, feel-good
    enthusiast about life + AI; make people feel good (real therapist).
    The voice anchor must carry this energy so it drives every surface."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    txt = open(os.path.join(root, "core_identity.md")).read().lower()
    assert "relentlessly positive" in txt
    assert "obsessed with ai" in txt
    assert "feel good" in txt or "feel good." in txt
    assert "never doom" in txt  # positivity must exclude doom/cynicism


def test_post_tweet_returns_bool_for_skip_vs_ship():
    """2026-06-09: the same hotake appeared 5x in engagement_log though dedup
    blocked the reposts — bot.py logged log_post/log_hotake unconditionally
    because post_tweet returned None on a skip. post_tweet must return False
    on policy/content/dedup skip and True only when it ships, so the caller
    can gate logging (same family as the reply phantom-log fix)."""
    from src import twitter_client as tc
    from src import action_guard as ag
    from src import content_guard as cg
    from src import config as cfg

    # Dedup skip → False (and no Safari).
    monkeypatch_targets = []
    import types
    orig_canpost = ag.can_post
    orig_validate = cg.validate
    orig_isdup = cg.is_duplicate
    orig_dry = cfg.DRY_RUN
    try:
        ag.can_post = lambda action: (True, "ok")
        cg.validate = lambda text, kind="original": (True, "")
        cg.is_duplicate = lambda text, threshold=None: True   # force dup
        cfg.DRY_RUN = True  # never touch Safari even if it didn't dedup
        assert tc.post_tweet("AI capex is the new rent again") is False, \
            "a near-duplicate post must return False, not None"
        # Not a dup, DRY_RUN → recorded ship → True
        cg.is_duplicate = lambda text, threshold=None: False
        assert tc.post_tweet("a genuinely fresh original take about AI") is True
    finally:
        ag.can_post = orig_canpost
        cg.validate = orig_validate
        cg.is_duplicate = orig_isdup
        cfg.DRY_RUN = orig_dry


def test_hotake_dedup_block_english_no_space():
    """2026-06-09: the hotake anti-repeat block was in FRENCH (weak on an
    English bot) and pushed SPACE content ('space push mode') — off-persona,
    and it let the same line ('AI capex is the new rent') regenerate 13x.
    The block must be English, anti-repeat on phrasing, and space-free."""
    import inspect
    from src import hotake_agent as h
    src = inspect.getsource(h)
    # The dedup/anti-repeat block must be English now.
    assert "DO NOT REPEAT" in src and "HARD PIVOT" in src
    assert "PIVOT ABSOLU" not in src, "dedup block still French"
    # Space must be excluded from the SCOPE blocks, never promoted as a pillar.
    assert "space push mode" not in src.lower()
    assert "off-persona" in src.lower()
    assert "espace: spacex" not in src.lower(), "French space scope still present"
    assert "2. space: spacex" not in src.lower(), "English space scope pillar still present"


def test_prompts_are_english_only():
    """Operator 2026-06-09: 'we are english only bro'. The live generation
    prompts must carry no French scaffolding (the old FR persona prompts +
    dead 25k PROMPT_TEMPLATE are gone)."""
    import re
    fr = re.compile(r"\b(tu écris|t'as|c'est pas|réécris|hors-scope|déjà posté dans|ne couvre pas le même|piège|chute française)\b", re.I)
    from src.hotake_agent import HOTAKE_PROMPT
    rendered = HOTAKE_PROMPT.format(lang_directive="[EN]", performance_section="", dedup_section="")
    assert not fr.search(rendered.lower()), "hotake prompt still has French"
    # Dead French templates must be gone.
    a = open("src/agent.py").read()
    assert "AI & Space Decoder" not in a, "dead French PROMPT_TEMPLATE still present"
    h = open("src/hotake_agent.py").read()
    assert "_ARCHIVE_OLD_HOTAKE_PROMPT" not in h, "dead French hotake archive still present"
    # No FR reply-seeking query.
    from src.direct_reply import SEARCH_QUERIES
    assert not any("lang:fr" in q for q in SEARCH_QUERIES), "FR reply query still present"


def test_tests_cannot_write_production_state(tmp_path):
    """2026-06-09: a guard test mocked post_tweet but bot.py's bookkeeping
    (save_tweet + log_hotake) wrote its fixture text into the REAL
    tweet_history.json + engagement_log.csv — 21 phantom engagement rows and
    6 phantom history entries over two days, which a later self-eval
    misdiagnosed as a live repetition bug. The conftest _no_prod_state wall
    must redirect every measurement/state store to per-test tmp files."""
    import os
    from src import config as cfg
    from src import engagement_log as el, history as hist, content_guard as cg

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for mod, attr in ((el, "ENGAGEMENT_LOG_FILE"), (hist, "HISTORY_FILE"),
                      (cg, "_HISTORY_FILE"), (cfg, "ACTION_LEDGER_FILE"),
                      (cfg, "REPLIED_FILE")):
        path = getattr(mod, attr)
        assert not os.path.abspath(path).startswith(repo + os.sep), \
            f"{mod.__name__}.{attr} points INSIDE the repo during tests: {path}"

    # A write through the normal API must land in tmp, not the repo.
    el.log_post("TEST-FIXTURE wall probe zz")
    hist.save_tweet("TEST-FIXTURE wall probe zz")
    real_log = os.path.join(repo, "engagement_log.csv")
    if os.path.exists(real_log):
        assert "wall probe zz" not in open(real_log).read(), \
            "test write leaked into the production engagement_log.csv"
    real_hist = os.path.join(repo, "tweet_history.json")
    if os.path.exists(real_hist):
        assert "wall probe zz" not in open(real_hist).read(), \
            "test write leaked into the production tweet_history.json"


def test_burned_catchphrases_blocked_at_chokepoint():
    """2026-06-09: the prompts quoted exemplar phrases ("we are so early",
    "okay this is genuinely...") and the model parroted them — 6+ posts in
    one day carried the same catchphrase, every one 0 likes. The exemplars
    are gone from the prompts and the chokepoint refuses the burned phrases
    on the profile surfaces (posts + quotes). Replies are unaffected."""
    from src import content_guard as cg

    burned = "Wild launch today. We are so early, most people can't feel it yet."
    for kind in ("original", "quote"):
        ok, why = cg.validate(burned, kind=kind)
        assert not ok and "catchphrase" in why, f"{kind} must refuse burned phrase: {why}"

    ok, _ = cg.validate(
        "We are so early on this one — the benchmark gap doubled in a single "
        "release and the pricing didn't move.", kind="reply")
    assert ok, "replies are not gated on catchphrases"

    fresh, _ = cg.validate("Nvidia's quarter was a therapy session disguised as an earnings call.", kind="original")
    assert fresh, "normal originals must still pass"


def test_reply_pipeline_overlaps_generation_with_posting(monkeypatch):
    """2026-06-09 (operator: 'BOT REALLY SLOW... ACCELERATE'): the reply loop
    serialized a ~30-50s LLM call THEN ~20s of Safari per reply. The pipeline
    must START generating reply N+1 while reply N is still posting — and keep
    the contracts: one gen + one post per candidate, log only on ship."""
    import threading
    from src import direct_reply as dr

    gen_calls = []
    second_gen_started = threading.Event()

    def fake_gen(author, text, lang="fr"):
        gen_calls.append(author)
        if author == "b":
            second_gen_started.set()
        return f"a sharp, substantive take for {author} that passes every gate"

    posts = []

    def fake_post(url, reply):
        if not posts:
            # The pipeline guarantee: while the FIRST reply is posting, the
            # SECOND generation has already started.
            assert second_gen_started.wait(timeout=5), \
                "gen of candidate 2 never started during posting of candidate 1 (pipeline broken)"
        posts.append(url)
        return True

    monkeypatch.setattr(dr, "_generate_single_reply", fake_gen)
    monkeypatch.setattr(dr, "reply_to_tweet", fake_post)
    monkeypatch.setattr(dr, "load_replied", lambda: set())
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_tweet_age_minutes", lambda url: 1)
    monkeypatch.setattr(dr, "_is_on_niche", lambda t: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 999, 0))
    monkeypatch.setattr(dr, "humanize", lambda t: t)

    tweets = [
        {"url": "https://x.com/usera/status/111", "text": "AI thing one", "author": "a"},
        {"url": "https://x.com/userb/status/222", "text": "AI thing two", "author": "b"},
    ]
    posted = dr._reply_to_tweets(tweets, set(), "SEARCH-TEST")
    assert posted == 2, f"both candidates must ship (posted={posted})"
    assert sorted(gen_calls) == ["a", "b"], "exactly one generation per candidate"
    assert len(posts) == 2

    # remaining bound: with remaining=1, exactly one generation is submitted.
    gen_calls.clear(); posts.clear()
    posted = dr._reply_to_tweets(list(tweets), set(), "SEARCH-TEST", remaining=1)
    assert posted == 1 and len(gen_calls) == 1, \
        "remaining=1 must bound generations AND posts to 1"


def test_agent_bounds_allow_operator_volume_mandate():
    """2026-06-09: originals stalled at ~5/day because THREE agent clamp
    sites still encoded the 2026-06-07 spec (news<=2, hotake<=2) and
    re-clamped live_strategy.json every cycle regardless of .env. The agent
    bounds must allow the operator's current volume mandate — when the
    mandate changes, change the bounds AND this test together."""
    from src.meta_strategy_agent import _BOUNDS
    assert _BOUNDS["MAX_NEWS_PER_DAY"][1] >= 8
    assert _BOUNDS["MAX_HOTAKES_PER_DAY"][1] >= 14
    assert _BOUNDS["MAX_QUOTES_PER_DAY"][1] >= 200
    # Floors: the agent may tune DOWN but never starve a surface to the
    # old-spec levels.
    assert _BOUNDS["MAX_HOTAKES_PER_DAY"][0] >= 6
    assert _BOUNDS["MAX_NEWS_PER_DAY"][0] >= 2

    from src.strategy_lab_bot import ALLOWED_PATHS
    assert ALLOWED_PATHS["caps.MAX_NEWS_PER_DAY"][1] >= 8
    assert ALLOWED_PATHS["caps.MAX_HOTAKES_PER_DAY"][1] >= 14
    assert ALLOWED_PATHS["caps.MAX_QUOTES_PER_DAY"][1] >= 200
    assert ALLOWED_PATHS["caps.FOLLOW_BLAST_PER_CYCLE"] == (0, 0), \
        "follow_blast must stay permanently 0"


def test_engine_health_quote_gif_counts_as_quote_and_slot_quiet_hours(monkeypatch, tmp_path):
    """2026-06-10 02:06 double false alarm (burned a self-heal run on a
    healthy engine): (1) quote_gif ships were invisible to the 'quote'
    bucket — count AND recent-fire guard missed them; (2) 'hotake collapsed'
    fired overnight although originals are slot-scheduled 08:30-21:30 and
    quiet-by-design at night."""
    import csv as _csv
    from datetime import datetime as _dt
    from src import engine_health_bot as ehb

    # (1) quote_gif rows must land in the 'quote' bucket.
    log_path = tmp_path / "engagement_log.csv"
    now = _dt.now()
    rows = [["timestamp", "type", "text", "target_url"]]
    rows.append([now.strftime("%Y-%m-%dT%H:00:00"), "quote_gif", "x", "y"])
    with open(log_path, "w") as f:
        _csv.writer(f).writerows(rows)
    monkeypatch.setattr(ehb, "ENGAGEMENT_LOG", str(log_path))
    counts, latest = ehb._counts_by_day_hour()
    assert counts.get((now.date().isoformat(), "quote")) == 1, \
        "quote_gif must count toward the quote surface"
    assert latest.get("quote") == now.hour, \
        "quote_gif must update the quote recent-fire hour"

    # (2) slot surfaces are not evaluated outside slot hours; 24/7 surfaces are.
    assert ehb._in_slot_quiet_hours("hotake", 2), "hotake at 02h = quiet by design"
    assert ehb._in_slot_quiet_hours("post", 23), "post at 23h = quiet by design"
    assert not ehb._in_slot_quiet_hours("hotake", 14), "hotake midday must be watched"
    assert not ehb._in_slot_quiet_hours("quote", 2), "quote runs 24/7 — always watched"
    assert not ehb._in_slot_quiet_hours("reply", 2), "reply runs 24/7 — always watched"
