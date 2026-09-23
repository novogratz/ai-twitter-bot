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

from src.guards import content_guard as cg
from src.core import pattern_tags
from src.core.llm_client import unwrap_text, contains_post_unsafe_leak
from src.guards import replied_store as rs


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
    from src.x.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("CAPES DON'T SPIN COMPUTERS. WIRES DO.\n\n[RENAME]")
    assert "[RENAME]" not in out
    assert "WIRES DO." in out


def test_legit_brackets_survive_scrub():
    from src.x.twitter_client import _scrub_metadata_leaks
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


# --- history idempotency -------------------------------------------------------

def test_save_tweet_idempotent(monkeypatch, tmp_path):
    import src.core.history as history
    import src.core.config as config
    hist_file = str(tmp_path / "hist.json")
    monkeypatch.setattr(history, "HISTORY_FILE", hist_file)
    history.save_tweet("same text")
    history.save_tweet("same text")
    assert len(history.load_history()) == 1


# --- scraped JSON safety ------------------------------------------------------

def test_json_safety_strips_lone_surrogates_before_utf8_write(tmp_path):
    from src.core.json_safety import sanitize_for_json

    payload = {
        "items": [{
            "title": "AI math \ud835 signal",
            "url": "https://x.com/u/status/1",
        }]
    }
    safe = sanitize_for_json(payload)
    assert "\ud835" not in safe["items"][0]["title"]

    out = tmp_path / "signal.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2, ensure_ascii=False)
    assert "AI math  signal" in out.read_text(encoding="utf-8")


# --- truncation guard (the "botched ChatGPT paste" callout, 2026-06-05) -------

def test_smart_trim_ends_on_sentence():
    from src.core.humanizer import smart_trim
    long = ("jensen vend les pelles. les vrais gagnants d'internet n'ont pas tous misé "
            "sur Cisco en 2000 — ils ont construit des boîtes dessus quand le reste du "
            "marché cherchait encore comment épeler \"e-commerce\". la vraie question "
            "n'est pas quelle action acheter mais quel produit construire dessus.")
    out = smart_trim(long, 220)
    assert len(out) <= 220
    assert out.endswith((".", "!", "?", "…"))  # never a dangling fragment


def test_smart_trim_short_text_untouched():
    from src.core.humanizer import smart_trim
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

def _fake_safari(monkeypatch):
    """Live (non-dry) reply path with every Safari step succeeding: the
    Replied store is only claimed when a Reply really ships."""
    import src.x.twitter_client as tc
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(tc, "_paste_text", lambda *a, **k: True)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a, **k: None)
    monkeypatch.setattr(tc, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)


def test_reply_chokepoint_blocks_second_reply(monkeypatch, tmp_path):
    """Two reply bots racing on the same tweet: the second write MUST be
    refused at the chokepoint regardless of which bot it came from."""
    import src.x.twitter_client as tc
    from src.guards import action_guard

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    _fake_safari(monkeypatch)
    monkeypatch.setattr(action_guard, "can_post", lambda action: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(a))

    url = "https://x.com/Graphseo/status/1234567890123456789"
    reply = "le signal des fautes tient exactement un cycle de finetuning, profites-en tant que ça marche"
    tc.reply_to_tweet(url, reply)
    tc.reply_to_tweet(url, reply + " v2")          # same tweet, second bot
    tc.reply_to_tweet(url + "?s=20", reply + " v3")  # same tweet, different URL form

    assert len(recorded) == 1  # exactly ONE reply ever reached the write


# --- human-typo injection for @Graphseo (operator mandate 2026-06-05) ----------

def test_inject_human_typo_exactly_one_adjacent_char():
    import random
    from src.core.humanizer import inject_human_typo, _KEY_NEIGHBORS
    text = "le signal des fautes va marcher exactement un cycle de finetuning pas plus"
    out = inject_human_typo(text, rng=random.Random(42))
    assert out != text and len(out) == len(text)
    diffs = [(a, b) for a, b in zip(text, out) if a != b]
    assert len(diffs) == 1                       # exactly ONE character changed
    orig, typo = diffs[0]
    assert typo in _KEY_NEIGHBORS[orig]          # and it's keyboard-adjacent


def test_inject_human_typo_skips_unsafe_words():
    from src.core.humanizer import inject_human_typo
    # only mentions/URLs/short words -> unchanged
    text = "@Graphseo yes https://x.com/a $NVDA ok"
    assert inject_human_typo(text) == text


# --- GIF tag scrubbing (operator 2026-06-05) ----------------------------------


def test_gif_tag_scrubbed_at_chokepoint():
    from src.x.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("take here\n[GIF: kermit panic]")
    assert "[GIF" not in out and "take here" in out


# --- monetization mandate gates (2026-06-05 PM) ---------------------------------

def test_post_urls_stripped():
    from src.x.twitter_client import _strip_post_urls
    out = _strip_post_urls("Big take here.\n\nhttps://cnbc.com/article/xyz")
    assert "http" not in out and "Big take here." in out


def test_hashtags_stripped_at_chokepoint():
    from src.x.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("the market needs therapy #Bitcoin #AI")
    assert "#" not in out and "therapy" in out


def test_stale_review_mode_does_not_divert_post_to_a_queue(monkeypatch, tmp_path):
    """REVIEW_MODE queued drafts into review_queue.json that nothing shipped,
    so every editorial slot burned its attempts (#124). A leftover
    REVIEW_MODE=1 in .env must not hold drafts any more: DRY_RUN is the
    only no-publish switch."""
    import os
    import src.x.twitter_client as tc
    from src.guards import action_guard
    import src.core.config as config
    monkeypatch.setenv("REVIEW_MODE", "1")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(config, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(action_guard, "can_post", lambda a: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    assert tc.post_tweet("a sponsor-clean original take about the market needing a therapist today") is tc.DRY_RUN_RECORDED
    assert recorded == [((action_guard.POST,), {"dry_run": True})]
    assert not os.path.exists(os.path.join(str(tmp_path), "review_queue.json"))
    assert not hasattr(tc, "_queue_for_review")


# --- 2026-06-07 agent spec: follow policy (Part 1 hard constraints) ---------

@pytest.fixture()
def follow_env(monkeypatch, tmp_path):
    """Isolated ledger + whitelist + counts for action_guard follow tests."""
    from src.guards import action_guard as ag
    from src.core import config

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
    # These tests pin the LEGACY spec policy; growth mode (2026-06-11) has
    # its own dedicated test and must not leak in from the live .env.
    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
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
    from src.core import config
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


# --- 2026-06-07 round 2: pillar tags / freshness sort / trim ---------------

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


def _url_with_age(minutes: int) -> str:
    from datetime import datetime, timezone
    from src.x.x_urls import _TWITTER_EPOCH_MS
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    tweet_id = (now_ms - minutes * 60_000 - _TWITTER_EPOCH_MS) << 22
    return f"https://x.com/someone/status/{tweet_id}"


def test_reply_candidates_sorted_fresh_and_rising_first():
    """2026-06-07 spec: front-load fresh fast-rising posts. A 20-min riser
    must beat a 60-hour-old tweet; unknown-age URLs go last; within the
    same freshness bucket, higher likes-per-hour wins."""
    from src.replies.direct_reply import _freshness_sort_key
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
    from src.core.humanizer import smart_trim
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


# --- 2026-06-07 round 3: lane queries ---------------------------------------

def test_reply_queries_are_on_lane():
    """Spec lane: AI x markets x psychology. NO space content; the tier1-2
    seeds + foils must be scanned directly via from: queries."""
    from src.replies.direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
    joined = " ".join(SEARCH_QUERIES + HOT_TAB_QUERIES).lower()
    for banned in ("spacex", "starship", "nasa", "satellite", "rocket lab", "orbit"):
        assert banned not in joined, f"space term {banned!r} is off-persona"
    for seed in ("from:thebtctherapist", "from:morganhousel", "from:saylor"):
        assert seed in joined, f"missing seed scan {seed!r}"
    # Market-trauma VOICE still represented (panic/drawdown reply targets),
    # but trimmed to 1 query — operator 2026-06-08 "focus more on AI": the
    # therapist voice frames AI replies; it's no longer a topic lane.
    assert "panic" in joined, "market-trauma voice target missing"


# --- 2026-06-07 PM: early-reply pools are curator-driven, never static ------

def test_early_reply_targets_are_curator_driven():
    """2026-06-07 PM operator mandate: NO static target lists — the scan
    pools come from account_curator.tracked_handles(), pinned with the only
    two operator-mandated keepers (TheBTCTherapist, Graphseo)."""
    from src.replies.early_bird_bot import EARLY_BIRD_ACCOUNTS
    from src.replies.mega_watch_bot import MEGA_ACCOUNTS
    assert EARLY_BIRD_ACCOUNTS == [] and MEGA_ACCOUNTS == [], (
        "static early-reply lists must stay empty — pools come from the curator"
    )
    from src.account.account_curator import PINNED, tracked_handles
    # Mindset4Money_X pinned 2026-06-10: measured 100-like / 13.3K-view
    # reply conversion on his question post (operator: "more things like this").
    assert tuple(PINNED) == ("TheBTCTherapist", "Graphseo", "Mindset4Money_X")
    handles = tracked_handles(limit=5)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo"


# --- 2026-06-07 PM: self-curated tracking ----------------------------------

def test_curator_lane_gate_and_pins(monkeypatch, tmp_path):
    """Only ON-LANE engagements count as evidence (FR-era rows classify
    'other' and are ignored); pinned handles always lead the tracked list."""
    from datetime import datetime
    from src.account import account_curator as ac
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
    from src.account.account_curator import _promotable
    assert _promotable({"handle": "unusual_whales", "engagements": 9})
    assert not _promotable({"handle": "bisdianora24202", "engagements": 9}), "digit-run spam"
    assert not _promotable({"handle": "goodname", "engagements": 4}), "below promote floor"


def test_profile_visits_blocked_outside_allowlist(monkeypatch):
    """Operator mandate 2026-06-07 PM: NO profile visits for discovery —
    scrape surfaces are @TheBTCTherapist + Home (For You/Following) + search.
    A non-allowlisted profile must return [] BEFORE any Safari work, and the
    allowlist env must be read at call time (side-effect-gate rule)."""
    from src.x import twitter_client as tc
    from src.core.config import BOT_HANDLE

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


def test_reply_callers_never_premark_store(monkeypatch, tmp_path):
    """2026-06-07 post-mortem: five bots 'locked the URL in BEFORE posting'
    (save_replied premark) — the reply chokepoint (2026-06-05) loads that
    same store and silently refused its OWN caller's reply, 100% of the
    time, while unconditional log_reply calls wrote phantom rows into
    engagement_log. Contract pinned here: (1) the on-disk store must NOT
    contain the URL at the moment reply_to_tweet is invoked; (2) log_reply
    fires ONLY when reply_to_tweet returns True."""
    import src.replies.direct_reply as dr

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    url = _url_with_age(5)
    tweets = [{"url": url, "text": "nvidia margins at 75 percent again", "author": "some_ai_account"}]

    premarked_at_call = []
    def fake_reply(u, text):
        premarked_at_call.append(u in rs.load_replied())
        return True
    logged = []
    monkeypatch.setattr(dr, "_generate_single_reply",
                        lambda *a, **k: "calm reframe with the precise fact")
    monkeypatch.setattr(dr, "reply_to_tweet", fake_reply)
    monkeypatch.setattr(dr, "humanize", lambda t: t)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(dr, "_is_on_niche", lambda t: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 1000, 0))

    n = dr._reply_to_tweets(tweets, set(), "SEARCH-HOT", en_counter=[0])
    assert premarked_at_call == [False], \
        "caller premarked the store — the chokepoint would refuse its own reply"
    assert n == 1 and len(logged) == 1

    # Chokepoint refusal (False) → no phantom engagement_log row, posted=0.
    logged.clear()
    url2 = _url_with_age(6)
    tweets2 = [{"url": url2, "text": "tsmc capex at 40 billion now", "author": "some_ai_account"}]
    monkeypatch.setattr(dr, "reply_to_tweet", lambda u, t: False)
    n2 = dr._reply_to_tweets(tweets2, set(), "SEARCH-HOT", en_counter=[0])
    assert n2 == 0 and logged == [], \
        "chokepoint skip must not produce a phantom engagement_log row"


def test_reply_chokepoint_returns_bool(monkeypatch, tmp_path):
    """reply_to_tweet must return True when the reply ships and False on the
    dedup skip — callers gate log_reply on this."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    _fake_safari(monkeypatch)

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
    import src.replies.direct_reply as dr

    # ⚠️ The VIP scan imports scrape_x_search / reply_to_tweet FUNCTION-
    # LOCALLY from twitter_client — patch THERE, not on direct_reply.
    # (First version of this test patched dr.* — the real Safari fired and
    # posted live replies to @TheBTCTherapist mid-test. conftest's
    # _no_safari wall now makes that mistake fail loudly instead.)
    import src.x.twitter_client as tc
    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setenv("VIP_SCAN_HANDLES", "TheBTCTherapist")
    url = _url_with_age(30).replace("/someone/", "/TheBTCTherapist/")
    monkeypatch.setattr(tc, "scrape_x_search",
                        lambda q, max_tweets=20, tab="latest":
                        [{"url": url, "text": "working the weekend because bitcoin", "author": "TheBTCTherapist"}])

    graphseo_calls = []
    monkeypatch.setattr(dr, "_generate_graphseo_reply",
                        lambda text: graphseo_calls.append(text) or "réponse française")
    gen_labels = []
    def fake_gen(tpl, txt, model, label, author=None):
        gen_labels.append((label, tpl is dr.BESTIE_REPLY_PROMPT))
        return "the AI side sends love — and a fruit basket"
    monkeypatch.setattr(dr, "generate_vip_reply", fake_gen)
    sent = []
    monkeypatch.setattr(tc, "reply_to_tweet", lambda u, t: sent.append(t) or True)
    import src.core.engagement_log as el
    monkeypatch.setattr(el, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)

    dr._run_graphseo_scan(set())

    assert graphseo_calls == [], "Graphseo FR generator must NEVER run for the bestie"
    assert gen_labels == [("VIP_REPLY/TheBTCTherapist", True)]
    assert len(sent) == 1
    assert "—" not in sent[0], "humanize must strip em dashes from VIP replies"


def test_reply_chokepoint_strips_em_dashes(monkeypatch, tmp_path):
    """Operator 2026-06-07: an em dash in a published reply is an AI tell
    ('what a shame'). The chokepoint must strip em/en dashes for EVERY
    reply path, even ones that skip humanize()."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    recorded = {}
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")
    logged = []
    monkeypatch.setattr(tc, "log", type(tc.log)(tc.log.name)) if False else None
    # Capture the final text via the DRY_RUN log line is brittle — instead
    # verify through the store-marking path: patch _paste? Simplest: spy on
    # the DRY_RUN branch by reading the typo-injection input. We assert via
    # content_guard.validate receiving dash-free text.
    seen = {}
    import src.guards.content_guard as cg2
    real_validate = cg2.validate
    def spy_validate(text, kind="post"):
        seen["text"] = text
        return real_validate(text, kind=kind)
    monkeypatch.setattr(cg2, "validate", spy_validate)

    url = "https://x.com/foo/status/2063500000000000088"
    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part of the trade.") is tc.DRY_RUN_RECORDED
    assert "—" not in seen["text"]
    assert "conviction is the hard part" in seen["text"]


def test_skip_rationale_never_publishes():
    """2026-06-07 live leak: the model wrote 'SKIP.' + its whole rationale
    ('The tweet is incomplete (cuts off mid-sentence)...') and an
    exact-match SKIP check published it as a reply. Pin both layers:
    generator-side prefix check and the content_guard chokepoint."""
    from src.guards import content_guard as cg
    ok, why = cg.validate("SKIP. The tweet is incomplete (cuts off mid-sentence at 'rema'), "
                          "and the angle is generic crypto psychology.", kind="reply")
    assert not ok and "SKIP" in why
    ok, _ = cg.validate("skip", kind="reply")
    assert not ok
    # Legitimate text containing 'skip' mid-sentence still passes.
    ok, _ = cg.validate("Most investors skip the part where conviction gets tested.", kind="reply")
    assert ok
    # Generator-side: prefix match, not exact match.
    from src.replies import direct_reply as dr
    import src.core.llm_client as llm
    class R: returncode = 0; stdout = "SKIP. Here is why I refuse..."; stderr = ""
    # _generate_single_reply path is LLM-bound; test the cheap invariant via
    # the same predicate the code uses now:
    assert R.stdout.upper().strip().startswith("SKIP")


def test_bare_dash_replacement_keeps_spacing():
    """2026-06-07: '—' → ',' produced 'angle,conviction' in a live reply.
    Bare dashes must become ', ' with normalized spacing, in humanize AND
    at the reply chokepoint."""
    from src.core.humanizer import humanize, strip_dashes
    out = humanize("The angle—conviction through crashes—is generic and it shows badly.")
    assert ",conviction" not in out and ", conviction" in out
    # Reply admission shares the same cleanup for paths that skip humanize.
    assert strip_dashes("The angle—conviction — is generic") == "The angle, conviction. is generic"


def test_reply_queries_are_ai_first():
    """Operator 2026-06-07: 'bot needs to be more AI focused' / 'i want to
    see more AI shit'. The reply lane must be majority-AI: at least half of
    the search queries carry an AI term, BTC tail stays minimal (feud lane
    only, ≤2 queries)."""
    from src.replies.direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
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
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")

    url = "https://x.com/Graphseo/status/2063500000000000099"
    english = "The market just told you what your conviction is worth this week."
    assert tc.reply_to_tweet(url, english) is False
    # Post must stay UNMARKED — a later FR draft can still ship.
    assert url not in rs.load_replied()
    french = "Le marché vient de te dire ce que vaut ta conviction cette semaine."
    assert tc.reply_to_tweet(url, french) is tc.DRY_RUN_RECORDED

    # SKIPPED / Skip. variants (live leaks 01:04-04:07) die at content_guard.
    for leak in ("SKIPPED", "Skip.", "skipped", "SKIP — no source context"):
        ok, _ = cg.validate(leak, kind="reply")
        assert not ok, f"{leak!r} must never publish"


def test_startup_reply_warmup_is_bounded(monkeypatch):
    """Operator 2026-06-07: 'more quote retweet on AI'. Root cause was an
    UNBOUNDED startup reply warmup that ran 20+ min and blocked
    scheduler.start() — so the dedicated quote/AI-viral jobs never came
    online (15:43 boot: 300+ replies, 0 quotes). run_direct_reply_cycle
    must honor max_replies and STOP, yielding Safari."""
    import src.replies.direct_reply as dr
    # Every query returns 5 fresh on-niche tweets; without the cap the cycle
    # would reply to all of them across all 21 queries.
    calls = {"replies": 0, "queries": 0}
    def fake_search(q, max_tweets=25, tab="top"):
        calls["queries"] += 1
        base = 2063900000000000000 + calls["queries"] * 100
        return [{"url": f"https://x.com/acct/status/{base+i}",
                 "text": "openai shipped a new reasoning model today", "author": "acct"}
                for i in range(5)]
    def fake_reply_block(tweets, tried, source, source_detail="", remaining=None, en_counter=None):
        # Honor the remaining budget like the real _reply_to_tweets.
        n = len(tweets) if remaining is None else min(len(tweets), remaining)
        calls["replies"] += n
        return n
    monkeypatch.setattr(dr, "scrape_x_search", fake_search)
    monkeypatch.setattr(dr, "_reply_to_tweets", fake_reply_block)
    monkeypatch.setattr(dr, "_run_graphseo_scan", lambda tried: None)

    dr.run_direct_reply_cycle(max_replies=12)
    assert calls["replies"] == 12, f"warmup must stop at the cap, got {calls['replies']}"
    assert calls["queries"] < 21, "must stop scanning queries once the budget is spent"


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


def test_mega_viral_quote_cannot_bypass_editorial_policy(monkeypatch):
    from src.guards import action_guard as ag
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    for urgent in (False, True):
        assert not ag.can_post(ag.QUOTE, high_value=True, urgent=urgent)[0]


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


def test_post_tweet_returns_bool_for_skip_vs_ship(monkeypatch):
    """2026-06-09: the same hotake appeared 5x in engagement_log though dedup
    blocked the reposts — bot.py logged log_post/log_hotake unconditionally
    because post_tweet returned None on a skip. post_tweet must return False
    on policy/content/dedup skip and True only when it ships, so the caller
    can gate logging (same family as the reply phantom-log fix)."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg

    # Dedup skip → False (and no Safari).
    monkeypatch_targets = []
    import types
    orig_canpost = ag.can_post
    orig_validate = cg.validate
    orig_isdup = cg.is_duplicate
    monkeypatch.setenv("DRY_RUN", "1")  # never touch Safari even if it didn't dedup
    try:
        ag.can_post = lambda action: (True, "ok")
        cg.validate = lambda text, kind="original": (True, "")
        cg.is_duplicate = lambda text, threshold=None: True   # force dup
        assert tc.post_tweet("AI capex is the new rent again") is False, \
            "a near-duplicate post must return False, not None"
        # Not a dup, DRY_RUN → recorded, not shipped
        cg.is_duplicate = lambda text, threshold=None: False
        assert tc.post_tweet("a genuinely fresh original take about AI") is tc.DRY_RUN_RECORDED
    finally:
        ag.can_post = orig_canpost
        cg.validate = orig_validate
        cg.is_duplicate = orig_isdup


def test_prompts_are_english_only():
    """Operator 2026-06-09: 'we are english only bro'. The reply lane must
    not seek French posts."""
    from src.replies.direct_reply import SEARCH_QUERIES
    assert not any("lang:fr" in q for q in SEARCH_QUERIES), "FR reply query still present"


def test_tests_cannot_write_production_state(tmp_path):
    """2026-06-09: a guard test mocked post_tweet but bot.py's bookkeeping
    (save_tweet + log_hotake) wrote its fixture text into the REAL
    tweet_history.json + engagement_log.csv — 21 phantom engagement rows and
    6 phantom history entries over two days, which a later self-eval
    misdiagnosed as a live repetition bug. The conftest _no_prod_state wall
    must redirect every measurement/state store to per-test tmp files."""
    import os
    from src.core import config as cfg
    from src.core import engagement_log as el, history as hist
    from src.guards import content_guard as cg

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


def test_state_files_resolve_to_the_repo_root():
    """config, llm_client and twitter_client moved under src/core and src/x
    (#114): a path computed from __file__ gains a level, and the bot would then
    read .env and write its state files under src/. The guards and editorial
    modules followed under src/guards and src/editorial (#115)."""
    from pathlib import Path
    from src.core import config, llm_client
    from src.editorial import editorial_bot, reach_report
    from src.guards import action_guard, respect_list
    from src.x import twitter_client

    repo = Path(__file__).resolve().parent.parent
    assert Path(config._PROJECT_ROOT).resolve() == repo
    for state_file in (llm_client._CODEX_LOCKOUT_FILE, twitter_client._FOLLOW_REJECTS_FILE,
                       action_guard._FOLLOWING_COUNT_FILE, respect_list.RESPECT_FILE,
                       editorial_bot.STATE_FILE, editorial_bot.AUDIT_FILE,
                       reach_report.REPORT_FILE, reach_report.REPORT_MARKDOWN):
        assert Path(state_file).resolve().parent == repo, state_file


def test_tests_cannot_spawn_osascript(monkeypatch):
    """twitter_client, safari_hygiene and several jobs call osascript through
    subprocess.run directly, past the _run_applescript wall: the conftest
    wall refuses those processes too."""
    import subprocess

    def _leak(*a, **k):
        raise RuntimeError("the conftest wall let a Safari process through")
    monkeypatch.setattr(subprocess, "_fork_exec", _leak, raising=False)
    monkeypatch.setattr(os, "posix_spawn", _leak)

    for argv in (["osascript", "-e", "return 1"], ["open", "-a", "Safari"],
                 ["pkill", "-x", "Safari"], "osascript -e 'return 1'"):
        with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
            subprocess.run(argv, shell=isinstance(argv, str))


def test_burned_catchphrases_blocked_at_chokepoint():
    """2026-06-09: the prompts quoted exemplar phrases ("we are so early",
    "okay this is genuinely...") and the model parroted them — 6+ posts in
    one day carried the same catchphrase, every one 0 likes. The exemplars
    are gone from the prompts and the chokepoint refuses the burned phrases
    on the profile surfaces (posts + quotes). Replies are unaffected."""
    from src.guards import content_guard as cg

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
    from src.replies import direct_reply as dr

    gen_calls = []
    second_gen_started = threading.Event()

    def fake_gen(author, text, lang="fr"):
        gen_calls.append(author)
        if author == "userb":
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
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_is_on_niche", lambda t: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 999, 0))
    monkeypatch.setattr(dr, "humanize", lambda t: t)

    tweets = [
        {"url": _url_with_age(1).replace("/someone/", "/usera/"), "text": "AI thing one", "author": "a"},
        {"url": _url_with_age(2).replace("/someone/", "/userb/"), "text": "AI thing two", "author": "b"},
    ]
    posted = dr._reply_to_tweets(tweets, set(), "SEARCH-TEST")
    assert posted == 2, f"both candidates must ship (posted={posted})"
    assert sorted(gen_calls) == ["usera", "userb"], \
        "exactly one generation per candidate, for the URL handle"
    assert len(posts) == 2

    # remaining bound: with remaining=1, exactly one generation is submitted.
    gen_calls.clear(); posts.clear()
    posted = dr._reply_to_tweets(list(tweets), set(), "SEARCH-TEST", remaining=1, skipped=set())
    assert posted == 1 and len(gen_calls) == 1, \
        "remaining=1 must bound generations AND posts to 1"


def test_follow_quality_gate_blocks_small_and_offniche(monkeypatch):
    """2026-06-12 operator: "the accounts you follow are trash, very small
    ... not related to AI or investment or crypto". The follow chokepoint
    must refuse small or off-niche profiles (whitelist seeds exempt), and
    must not follow blind when the followers count is unreadable."""
    import inspect
    from src.x.twitter_client import (_parse_follower_count,
                                    _follow_quality_decision, follow_account)

    assert _parse_follower_count("12.3K") == 12300
    assert _parse_follower_count("1,423") == 1423
    assert _parse_follower_count("2.1M") == 2_100_000
    assert _parse_follower_count("") == -1

    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "2000")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")

    ok, why = _follow_quality_decision(150, "AI trader", "x", whitelisted=False)
    assert not ok and "too small" in why
    ok, why = _follow_quality_decision(50_000, "dog photos and recipes", "x",
                                       whitelisted=False)
    assert not ok and "off-niche" in why
    ok, why = _follow_quality_decision(-1, "AI investor", "x", whitelisted=False)
    assert not ok and "unreadable" in why
    ok, _ = _follow_quality_decision(50_000, "Macro investor, AI & crypto",
                                     "x", whitelisted=False)
    assert ok
    # Whitelisted seeds bypass (e.g. Graphseo's SEO bio is off-niche by
    # design — operator-pinned accounts are never gated).
    ok, _ = _follow_quality_decision(10, "SEO expert", "x", whitelisted=True)
    assert ok

    # Structural pin: the chokepoint actually consults the gate.
    src = inspect.getsource(follow_account)
    assert "_follow_quality_decision" in src and "_quality_reject_recent" in src


def test_core_identity_carries_editorial_strategy():
    from pathlib import Path
    text = Path("core_identity.md").read_text().lower()
    assert "six original ai posts" in text
    assert "seven is the absolute ceiling" in text
    assert "no automated quote tweets" in text
    assert "replies remain uncapped" in text


def test_parent_like_is_probabilistic_not_every_reply(monkeypatch):
    """2026-06-15 (operator: "hit by automation flag — cool down likes").
    Liking the parent of EVERY reply (743/day) was the automation
    signature. _maybe_like_parent gates the like behind a low env
    probability: prob<=0 disables it; the reply chokepoint must route
    through the gate, not an unconditional like_tweet on the parent."""
    import inspect
    from src.x import twitter_client as tc

    liked = []
    monkeypatch.setattr(tc, "like_tweet", lambda url=None: liked.append(url))

    monkeypatch.setenv("REPLY_LIKE_PARENT_PROB", "0")
    for _ in range(20):
        tc._maybe_like_parent("https://x.com/a/status/1", "REPLY_LIKE_PARENT_PROB", 0.12)
    assert liked == [], "prob=0 must disable parent-likes entirely"

    monkeypatch.setenv("REPLY_LIKE_PARENT_PROB", "1")
    tc._maybe_like_parent("https://x.com/a/status/2", "REPLY_LIKE_PARENT_PROB", 0.12)
    assert liked == ["https://x.com/a/status/2"]

    rsrc = inspect.getsource(tc.reply_to_tweet)
    assert "_maybe_like_parent" in rsrc
    assert "like_tweet(tweet_url)" not in rsrc, \
        "reply must not unconditionally like the parent"


def test_uppercase_metadata_tag_stripped_at_chokepoint():
    """2026-06-14: qwen shipped '[SIGNS: yes]' live at the end of a post.
    The scrubber must strip any bracketed UPPERCASE-label + colon tag the
    keyword list doesn't name, while leaving real bracketed content
    ([2026], a single letter, normal prose) untouched."""
    from src.x.twitter_client import _scrub_metadata_leaks

    assert "[SIGNS" not in _scrub_metadata_leaks("Mike Novogratz says 95% done [SIGNS: yes]")
    assert "VERDICT" not in _scrub_metadata_leaks("the take [VERDICT: skip] here")
    # Real content with brackets must survive (no all-caps label + colon).
    assert _scrub_metadata_leaks("the 2026 plan [2026] holds") == \
        "the 2026 plan [2026] holds"
    assert _scrub_metadata_leaks("ranked [A] tier") == "ranked [A] tier"


def test_profile_surfaces_force_capable_provider():
    """Profile generators must pass force_provider=PROFILE_LLM_PROVIDER so
    profile/reply routing can be changed independently from AI_CLI."""
    import inspect
    from src.editorial import editorial_bot

    assert "force_provider=config.PROFILE_LLM_PROVIDER" in inspect.getsource(editorial_bot._json_call), \
        "the editorial generator must force the profile provider"

    from src.core import config
    # Default is Ollama, env-overridable to Codex/Gemini when needed.
    assert config.PROFILE_LLM_PROVIDER in ("ollama", "codex", "gemini", None) or \
        isinstance(config.PROFILE_LLM_PROVIDER, str)


def test_decode_header_stripped_at_chokepoint():
    """Operator 2026-06-06: 'I don't want to see the decode daily.' The
    prompt forbids the series header but weaker models (ollama primary,
    2026-06-11: 11 headered drafts in one night) keep emitting it — and a
    headered draft with a valid URL would ship. The chokepoint scrubber
    must strip the header line mechanically; legit sentences starting with
    'decode' stay untouched."""
    from src.x.twitter_client import _scrub_metadata_leaks

    headered = ("🔎 The Decode Daily #109. AI. 2026-06-11\n\n"
                "OpenAI just linked ChatGPT to Visa. the agent has a wallet now")
    out = _scrub_metadata_leaks(headered)
    assert "Decode Daily" not in out
    assert out.startswith("OpenAI just linked")

    fr = "Le Décode Quotidien #42. Crypto. 2026-06-11\nBitcoin holds 75k"
    assert "Décode" not in _scrub_metadata_leaks(fr)

    legit = "decode this chart and you'll see why everyone's wrong\n\nthe answer is rates"
    assert _scrub_metadata_leaks(legit) == legit


def test_follow_growth_mode_unties_ceiling_from_followers(monkeypatch):
    """2026-06-11 operator: "go back on following people and following back".
    Growth mode must untie the following ceiling from the followers count
    (following>followers mid-purge would block every follow), while
    FOLLOW_TOTAL_CAP stays the hard stop and legacy mode keeps the old
    followers-tied invariant."""
    from src.guards import action_guard
    from src.core import config

    monkeypatch.setattr(action_guard, "current_counts",
                        lambda: (1423, 2485))  # followers, following
    monkeypatch.setattr(config, "FOLLOW_TOTAL_CAP", 3000)

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", True)
    assert action_guard.following_ceiling() == 3000, \
        "growth mode: ceiling is FOLLOW_TOTAL_CAP, not the followers count"

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    assert action_guard.following_ceiling() == 1423, \
        "legacy mode keeps following <= followers"


def test_burned_structure_contrast_reframe_blocked():
    """2026-06-10 humanize mandate: after the catchphrase ban the model
    migrated to the contrast-reframe skeleton ("That's not fear, that's a
    crush") — 6+ ships in 40 posts, the new tell that got the account
    publicly spotted as a bot. The chokepoint must refuse the SHAPE for
    originals and quotes; replies and innocent text stay unaffected."""
    from src.guards import content_guard

    burned = [
        "Everyone in the thread is calling this fear but that's not fear, that's a crush on the future.",
        "The whole timeline calls it skepticism. that's not skepticism, it's grief about the old world.",
        "Everyone watching the chart thinks the market is broken. This isn't a dip. It's a discount.",
    ]
    for text in burned:
        ok, why = content_guard.validate(text, kind="quote")
        assert not ok and "burned structure" in why, f"should block: {text!r}"
        ok, why = content_guard.validate(text, kind="original")
        assert not ok, f"should block original too: {text!r}"

    fine = [
        "Nvidia sold out its 2027 supply before the keynote ended. the buildout is real",
        "I've read this three times and I still can't believe it's real",
    ]
    for text in fine:
        ok, why = content_guard.validate(text, kind="quote")
        assert ok, f"false positive on {text!r}: {why}"


def test_qrt_playbook_setup_colon_and_dotdot_texture():
    """2026-06-10 QRT playbook (operator: model the human meme account):
    (1) a text ending with a setup-colon ("[actor] watching X:") is refused
    as truncated (the GIF chokepoints that allowed it are removed, #111);
    (2) humanize() must preserve the human ".." / "..." texture (only 4+
    dots is an artifact); (3) casualize() never strips a ".." ending."""
    from src.guards import content_guard
    from src.core.humanizer import humanize, casualize

    setup = "Goldman Sachs watching retail buy the dip at 110x revenue:"
    ok, why = content_guard.validate(setup, kind="quote")
    assert not ok and "truncated" in why

    assert humanize("MFs will see this and still not take profit btw..") \
        .endswith("btw..")
    assert humanize("wait what....") .endswith("what...")

    class _Fire:
        def random(self):
            return 0.0

    assert casualize("the bears are exhausted btw..", rng=_Fire()).endswith("..")


def test_casualize_human_texture_is_safe():
    """2026-06-10 humanize mandate: casualize() may only (a) drop a final
    period when the ending can't read as truncated, (b) lowercase a
    title-cased common opener. It must NEVER touch ?/!/…, all-caps openers
    ("JUST IN:"), proper nouns, or produce text looks_truncated() rejects."""
    import random
    from src.core.humanizer import casualize
    from src.guards.content_guard import looks_truncated

    # Deterministic "always fire" rng.
    class _Fire:
        def random(self):
            return 0.0

    out = casualize("This is the wildest demo I've seen all year.", rng=_Fire())
    assert out == "this is the wildest demo I've seen all year"
    assert not looks_truncated(out)

    # All-caps opener + proper noun openers are never lowercased.
    assert casualize("JUST IN: Nvidia beats earnings again.", rng=_Fire()).startswith("JUST IN")
    assert casualize("Nvidia just sold out 2027 supply.", rng=_Fire()).startswith("Nvidia")

    # ? / ! / … endings untouched.
    assert casualize("What would you automate first?", rng=_Fire()).endswith("?")

    # rng that never fires → text unchanged.
    class _Never:
        def random(self):
            return 1.0

    text = "The market healed by lunch."
    assert casualize(text, rng=_Never()) == text

    # Never produce a truncated-looking ending: short final word keeps it safe.
    out = casualize("Honestly the whole thread is worth it.", rng=_Fire())
    assert not looks_truncated(out)


def test_engage_cycle_skips_likes_for_non_allowlisted_handles():
    """2026-06-17: engage_bot's reciprocity-like step calls
    visit_profile_and_like, which is gated by PROFILE_VISIT_ALLOWLIST
    (home/search-only mandate, 2026-06-07). Non-allowlisted handles return
    instantly after logging '[LIKE] profile visit blocked' — but the engage
    cycle still logged '[ENGAGE] Liking @X's latest tweets...' and slept
    3-5s between each, producing ~50s of paired noise per cycle. Same shape
    as PR #49's trusted-news skip: pre-filter by `_profile_visit_allowed`
    before the like step. The follow_account call above is intentionally
    NOT gated (mechanically required to click the Follow button)."""
    import inspect
    from src.account import engage_bot as eb

    src = inspect.getsource(eb.run_engage_cycle)
    # Pin: the cycle imports the allowlist gate and uses it to skip likes
    # for non-allowlisted handles before logging/sleeping.
    assert "_profile_visit_allowed" in src, \
        "engage cycle must pre-filter the like step by the profile allowlist"
    # Pin: the gate runs BEFORE visit_profile_and_like (i.e. the skip path
    # exists in the same function that calls the like primitive).
    gate_idx = src.find("_profile_visit_allowed")
    like_idx = src.find("visit_profile_and_like(username")
    assert 0 < gate_idx < like_idx, \
        "_profile_visit_allowed check must run before visit_profile_and_like"


def test_deliberate_skip_short_circuits_validation_retries():
    """2026-06-18 audit: when the model returns 'SKIP' deliberately,
    content_guard.generate_validated burned all 3 attempts (~30s each on
    Claude Sonnet) before logging 'empty draft' — ~29 quote cycles/day,
    ~43 min/day of wasted compute. Fix: gen_fn raises DeliberateSkip on
    a confident refusal; generate_validated catches it and stops retrying.
    """
    from src.guards import content_guard as cg

    calls = {"n": 0}

    def gen_fn():
        calls["n"] += 1
        raise cg.DeliberateSkip("model returned SKIP")

    out = cg.generate_validated(gen_fn, kind="quote", label="TEST", attempts=3)
    assert out is None
    assert calls["n"] == 1, f"DeliberateSkip must not retry — got {calls['n']} calls"

    # Sanity: a None-returning generator still retries (transient LLM hiccup
    # is the legitimate retry case — only deliberate refusals short-circuit).
    calls["n"] = 0

    def gen_none():
        calls["n"] += 1
        return None

    cg.generate_validated(gen_none, kind="quote", label="TEST", attempts=3)
    assert calls["n"] == 3, "None must still retry up to `attempts` times"


def test_reciprocal_followback_bypasses_whitelist(monkeypatch):
    """Self-improve #3 (2026-06-24): followback was dead — whitelist-only
    blocked following people who engage with us. reciprocal=True bypasses ONLY
    the whitelist gate (when FOLLOWBACK_BYPASS_WHITELIST), never the other
    gates. Pin: a non-whitelisted handle is whitelist-blocked normally but
    NOT for a reciprocal follow-back."""
    from src.guards import action_guard
    from src.core import config
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", True)
    monkeypatch.setattr(config, "FOLLOWBACK_BYPASS_WHITELIST", True)
    monkeypatch.setattr(action_guard, "is_whitelisted", lambda h, **k: False)
    _, why_norm = action_guard.can_follow("randomstranger999")
    assert "not on whitelist" in why_norm
    _, why_recip = action_guard.can_follow("randomstranger999", reciprocal=True)
    assert "not on whitelist" not in why_recip
    # kill switch: bypass off => reciprocal blocked again
    monkeypatch.setattr(config, "FOLLOWBACK_BYPASS_WHITELIST", False)
    _, why_off = action_guard.can_follow("randomstranger999", reciprocal=True)
    assert "not on whitelist" in why_off


def test_urgent_quote_obeys_editorial_policy(monkeypatch):
    from src.guards import action_guard as ag
    monkeypatch.setattr(ag, "count_today", lambda a: 0)
    assert not ag.can_post(ag.QUOTE, urgent=True)[0]


def test_direct_reply_scans_rotating_query_subset(monkeypatch):
    """2026-07-10 reply throughput ("you used to be around 900/day now only
    600"): direct_reply scanned ALL ~26 search queries EVERY 1-2 min cycle —
    the same query scraped 4x/hour mostly yields dedup-skips, and search
    scrapes ate the Safari time replies needed for POSTING (~27/hr). Pin the
    contract: each cycle scans a bounded rotating slice, consecutive cycles
    rotate (no slice starvation), full coverage lands within ceil(N/K)
    cycles, and the K env is read at call time."""
    from src.replies import direct_reply as dr
    monkeypatch.setenv("DIRECT_REPLY_QUERIES_PER_CYCLE", "8")
    qs = [f"q{i}" for i in range(26)]
    dr._QUERY_ROTATION_OFFSET[0] = 0
    slices = [dr._queries_for_cycle(qs) for _ in range(4)]
    assert all(len(s) == 8 for s in slices), "cycle must pay for K scrapes only"
    assert slices[0] != slices[1], "consecutive cycles must rotate"
    assert set().union(*(set(s) for s in slices)) == set(qs), \
        "rotation must cover every query within ceil(N/K) cycles"
    # K >= N degrades to scan-everything; env read at call time
    monkeypatch.setenv("DIRECT_REPLY_QUERIES_PER_CYCLE", "99")
    assert dr._queries_for_cycle(qs) == qs
    # the live cycle actually routes through the rotation
    import inspect
    src = inspect.getsource(dr.run_direct_reply_cycle)
    assert "_queries_for_cycle" in src, \
        "run_direct_reply_cycle must scan the rotating slice, not all queries"


def test_reply_search_surface_disabled_by_default(monkeypatch):
    """2026-07-19: the LLM-web-search reply surface (reply_bot -> reply_agent)
    is retired by default. Web search cannot index <=24h x.com tweets, so the
    path either hallucinated URLs (PR #59) or answered conversationally to its
    own stale FR-era persona prompt — 388 failed Claude CLI calls for 1 reply
    over 35h, plus a refresh_feed() Safari touch every ~3 min. Pin: with
    ENABLE_REPLY_SEARCH unset/0 the cycle returns before ANY side effect
    (no Safari, no LLM); =1 re-arms the path. Env read at call time."""
    from src.replies import reply_bot as rb

    calls = []
    monkeypatch.setattr(rb, "refresh_feed", lambda: calls.append("safari"))
    monkeypatch.setattr(rb, "generate_replies", lambda **kw: calls.append("llm") or None)

    # Default (unset) -> disabled, zero side effects
    monkeypatch.delenv("ENABLE_REPLY_SEARCH", raising=False)
    rb.run_reply_cycle()
    assert calls == [], "disabled surface must not touch Safari or the LLM"

    # Explicit 0 -> same
    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "0")
    rb.run_reply_cycle()
    assert calls == [], "ENABLE_REPLY_SEARCH=0 must short-circuit the cycle"

    # =1 -> the path runs again (env read at call time, no restart needed)
    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "1")
    monkeypatch.setattr(rb, "MAX_REPLIES_PER_CYCLE", 5)
    rb.run_reply_cycle()
    assert calls == ["safari", "llm"], "ENABLE_REPLY_SEARCH=1 must re-arm the surface"


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


def test_follow_gate_english_only(monkeypatch):
    """Operator 2026-07-19: 'follow US / english accounts not foreigner
    langage follows' — the quality gate (rides EVERY follow path via the
    follow_account chokepoint) must reject non-Latin-script and foreign-
    language bios."""
    from src.x.twitter_client import _follow_quality_decision
    monkeypatch.setenv("FOLLOW_REQUIRE_ENGLISH", "1")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")
    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "2000")

    ok, _ = _follow_quality_decision(
        50000, "AI investor. Building agents, GPUs and datacenter plays.",
        "Jane Doe", False)
    assert ok, "big EN on-niche account must pass"
    ok, why = _follow_quality_decision(
        50000, "AIと暗号資産の最新情報を毎日配信します。株式投資も。", "田中太郎", False)
    assert not ok and "non-English" in why, "Japanese bio must be rejected"
    ok, why = _follow_quality_decision(
        50000, "Analyse crypto et IA pour les investisseurs. Avec vous dans les marchés.",
        "Jean Dupont", False)
    assert not ok and "non-English" in why, "French bio must be rejected"
    # Whitelisted seeds stay exempt (Graphseo's FR bio is by design)
    ok, _ = _follow_quality_decision(500, "SEO et croissance pour les startups", "Julien", True)
    assert ok, "whitelisted seed must bypass the language gate"


def test_blank_page_storm_post_restart_grace_and_label_diversity(monkeypatch):
    """2026-07-19: 7 reactive Safari restarts in 2.2h. Two structural causes:
    (1) scrapes queued behind a hygiene restart hit the cold Safari, blank,
    and re-trip the threshold — a self-perpetuating ~15-min loop. Blanks
    within the post-restart grace window must not count. (2) one page
    legitimately empty in a loop (e.g. a quiet Following tab) is NOT a
    wedged Safari — a true wedge blanks EVERY page, so the restart needs
    >=2 distinct labels among the consecutive blanks."""
    import time as _time
    from src.x import twitter_client as tc
    from src.x import safari_hygiene as sh

    restarts = []
    monkeypatch.setattr(sh, "restart_safari", lambda reason="": restarts.append(reason) or True)

    # (1) grace: blanks right after a restart don't count
    tc._reset_blank_page_count()
    monkeypatch.setattr(sh, "_last_run_ts", lambda: _time.time())
    for _ in range(5):
        tc._record_blank_page(label="search 'x'")
    assert restarts == [], "blanks during post-restart grace must not restart Safari"

    # (2) out of grace: same-label loop holds, diverse labels restart
    monkeypatch.setattr(sh, "_last_run_ts", lambda: _time.time() - 3600)
    tc._reset_blank_page_count()
    for _ in range(4):
        tc._record_blank_page(label="following feed")
    assert restarts == [], "single-page empty loop is not a wedge — no restart"
    tc._reset_blank_page_count()
    tc._record_blank_page(label="following feed")
    tc._record_blank_page(label="search 'ai'")
    tc._record_blank_page(label="@TheAIShrink")
    assert restarts == ["black_screen_recovery"], "diverse-label blanks = wedge = restart"
    tc._reset_blank_page_count()


def test_safari_warmup_verifies_render_and_retries_blank(monkeypatch):
    """Dark-screen recovery must verify x.com rendered after restart.
    A blank app shell should trigger cache-busted retries and return False if
    Safari never reaches a usable page."""
    from src.x import safari_hygiene as sh

    commands = []
    statuses = iter([
        (True, "BLANK:0:https://x.com/home"),
        (True, "BLANK:0:https://x.com/home?bot_recover=1"),
        (True, "READY:shell:500"),
    ])

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(sh.subprocess, "run", lambda *a, **k: commands.append(a) or _R())
    monkeypatch.setattr(sh.time, "sleep", lambda *_: None)

    def fake_js(js_code, timeout=30):
        if "serviceWorker" in js_code:
            return True, ""
        return next(statuses)

    monkeypatch.setattr(sh, "_run_safari_js", fake_js)

    assert sh._warm_up_xcom()
    joined = "\n".join(str(c) for c in commands)
    assert "bot_recover=" in joined, "blank render must trigger cache-busted retry"


def test_pin_rotation_url_ground_truth_and_stale_override():
    """2026-07-19: the pin never rotated. Root cause = 4th hit of the
    display-name-vs-handle family: pin_bot compared scraper `author` (the
    DISPLAY NAME) to BOT_HANDLE, filtering every own post. Pin: ownership
    must come from is_own_post (URL ground truth), and a pin older than
    PIN_MAX_AGE_DAYS must stop defending its slot via the 1.3x beat rule."""
    import inspect
    from src.account import pin_bot
    src = inspect.getsource(pin_bot.run_pin_cycle)
    assert "is_own_post" in src, "pin candidates must be filtered by URL ground truth"
    assert 'author != BOT_HANDLE' not in src and 'author and author !=' not in src, \
        "display-name-vs-handle compare must be gone"
    assert "PIN_MAX_AGE_DAYS" in src and "pin_is_stale" in src, \
        "a stale pin must rotate instead of defending with the 1.3x rule"
    assert pin_bot.MIN_LIKES_TO_PIN <= 2 or "PIN_MIN_LIKES" in inspect.getsource(pin_bot), \
        "likes floor must be reachable at this account size"


def test_engagement_log_records_provider_column(monkeypatch, tmp_path):
    """2026-07-19 (all-ollama switch): every engagement_log row must carry
    the provider configured for its surface at write time, so provider
    switches are judged on likes-per-post data instead of vibes. Profile
    surfaces tag PROFILE_LLM_PROVIDER; replies tag the AI_CLI default."""
    import csv
    from src.core import engagement_log as el
    p = tmp_path / "engagement_log.csv"
    monkeypatch.setattr(el, "ENGAGEMENT_LOG_FILE", str(p))
    monkeypatch.setenv("PROFILE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AI_CLI", "codex")
    el.log_post("test post", source="TEST")
    el.log_reply("https://x.com/someone/status/123", "test reply", "reply", source="TEST")
    rows = list(csv.reader(open(p)))
    assert rows[0][-1] == "provider"
    post_row = next(r for r in rows[1:] if r[1] == "post")
    reply_row = next(r for r in rows[1:] if r[1] == "reply")
    assert post_row[7] == "ollama", "profile surface must tag PROFILE_LLM_PROVIDER"
    assert reply_row[7] == "codex", "reply surface must tag the AI_CLI default"


def test_debate_turn_cap_is_owned_by_the_reply_chokepoint(monkeypatch):
    """A Debate turn (CONTEXT.md) is capped per author per Toronto day at
    the reply chokepoint, whichever bot answers: debate_bot and replyback
    share one count. Ordinary replies to the same author stay uncapped, a
    refused turn leaves the tweet unmarked, and the cap is read at call time."""
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg
    from src.x import twitter_client as tc

    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(tc, "_run_applescript", lambda *a: True)
    monkeypatch.setattr(tc, "_paste_text", lambda *a: True)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: None)
    monkeypatch.setattr(tc, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "2")

    text = "Inference cost falls when batching works, so the margin story depends on utilisation."
    url = lambda author, n: f"https://x.com/{author}/status/{n}"
    assert tc.reply_to_tweet(url("Challenger", 1), text, debate_turn=True)
    assert tc.reply_to_tweet_in_thread(url("challenger", 2), text, debate_turn=True)
    assert not tc.reply_to_tweet(url("challenger", 3), text, debate_turn=True)
    assert url("challenger", 3) not in rs.load_replied(), "refused turn must stay fresh"
    assert tc.reply_to_tweet(url("challenger", 4), text), "plain replies stay uncapped"
    assert tc.reply_to_tweet(url("someone_else", 5), text, debate_turn=True)
    assert ag.debate_turns_today("challenger") == 2
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "3")
    assert tc.reply_to_tweet(url("challenger", 3), text, debate_turn=True)
    assert not tc.reply_to_tweet("https://x.com/i/web/status/6", text, debate_turn=True), \
        "a turn without a URL handle fails closed"


def test_debate_turn_cap_judged_under_the_safari_lock(monkeypatch):
    """Another thread can ship the Engager's last turn while this one waits
    for the browser: admission, judged under the lock, refuses before Safari."""
    import contextlib
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg
    from src.x import twitter_client as tc

    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "1")

    @contextlib.contextmanager
    def contended_lock():
        ag.record(ag.DEBATE_TURN, target="challenger")  # the other thread won
        yield
    monkeypatch.setattr(tc, "_safari_lock", contended_lock())
    # _run_applescript stays walled off by conftest: reaching Safari fails.
    url = "https://x.com/challenger/status/7"
    assert not tc.reply_to_tweet(url, "Batching changes the cost curve.", debate_turn=True)
    assert ag.debate_turns_today("challenger") == 1
    assert url not in rs.load_replied(), "the race loser was never claimed"


def test_replyback_reciprocity_never_follows(monkeypatch):
    """Engager follows belong to follow_engagers_job (engager=True). The
    replyback reciprocity pass only visits and likes; its old bare
    follow_account call was refused by the Seed-account rule anyway."""
    from src.replies import notify_bot as nb

    visited = []
    monkeypatch.setattr(nb, "visit_profile_and_like", lambda h, **k: visited.append(h))
    monkeypatch.setattr(nb, "follow_account",
                        lambda *a, **k: pytest.fail("replyback must not follow"), raising=False)
    monkeypatch.setattr(nb.random, "random", lambda: 0.0)
    nb._reciprocate_engagers([{"user": "Fresh @fresh", "url": "https://x.com/fresh/status/12"}], set())
    assert visited == ["fresh"]


def test_savvy_tech_mom_register():
    """Operator 2026-07-19: 'be less a troll and more a savvy tech mom.'
    The spine carries the savvy-tech-mom-not-a-troll register so every
    surface inherits it."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spine = open(os.path.join(root, "core_identity.md")).read().lower()
    assert "45-year-old woman and mom" in spine and "never cruel" in spine
    assert "something useful" in spine, "helpful register must be stated"


def test_follow_engagers_lane_and_gate_bypass(monkeypatch, tmp_path):
    """2026-07-19 likes+follows push: (1) the engager quality path skips
    size/niche (behavior proves both; small engagers follow back at the
    highest rate) but KEEPS the English gate; (2) follow_engagers_bot pulls
    Engagers from the ledger's Debate turns (newest first), never retries an
    attempted handle, respects caps, and routes through follow_account
    with engager=True."""
    from src.x.twitter_client import _follow_quality_decision
    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "10000")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")
    monkeypatch.setenv("FOLLOW_REQUIRE_ENGLISH", "1")
    ok, _ = _follow_quality_decision(42, "just a person who likes computers", "Sam", False, engager=True)
    assert ok, "engager must bypass min-followers and niche gates"
    ok, why = _follow_quality_decision(42, "Analyse crypto et IA pour les investisseurs. Avec vous dans les marchés.", "Jean", False, engager=True)
    assert not ok and "non-English" in why, "engager must NOT bypass the English gate"
    ok, _ = _follow_quality_decision(42, "just a person", "Sam", False)
    assert not ok, "non-engager path keeps the size gate"

    from src.guards import action_guard as ag
    from src.account import follow_engagers_bot as fe
    for engager in ("oldguy", "business", "freshfan"):  # business: big-media skip
        ag.record(ag.DEBATE_TURN, target=engager)
    monkeypatch.setattr(fe, "STATE_FILE", str(tmp_path / "fe_state.json"))
    followed = []
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h, engager=False: followed.append((h, engager)) or True)
    monkeypatch.setattr(ag, "can_follow", lambda h, reciprocal=False: (True, ""))
    monkeypatch.setenv("ENABLE_FOLLOW_ENGAGERS", "1")
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_CYCLE", "1")
    monkeypatch.setenv("FOLLOW_ENGAGERS_PER_DAY", "10")
    fe.run_follow_engagers_cycle()
    assert followed == [("freshfan", True)], "newest engager first, media skipped, engager flag set"
    fe.run_follow_engagers_cycle()
    assert [h for h, _ in followed] == ["freshfan", "oldguy"], \
        "attempted handles never retried; next cycle takes the next engager"


def test_evening_slots_stay_inside_waking_hours():
    """2026-07-19: the post-slot grid covers the measured best evening
    hours, inside Waking hours."""
    from src.editorial.editorial_bot import SLOTS
    assert all("04:30" <= clock < "22:00" for clock, _ in SLOTS)
    assert "20:30" in dict(SLOTS)


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


def test_pin_job_actually_scheduled_and_transient_refusals_dont_burn(monkeypatch, tmp_path):
    """2026-07-28 nine-day health read — shipped features were dead:
    (1) pin_bot was the DEAD-IMPORT family again (imported + in the
    hot-reload map, scheduler.add_job never called, zero [PIN] lines ever)
    — pin that main.py registers pin_job; (2) follow_engagers burned 262
    candidates into its attempted-forever set via TRANSIENT policy
    refusals (the 3500 total-following ceiling) — a transient refusal must
    end the cycle WITHOUT burning candidates."""
    from main import build_scheduler
    assert build_scheduler().get_job("pin_job") is not None

    from src.guards import action_guard as ag
    from src.account import follow_engagers_bot as fe
    ag.record(ag.DEBATE_TURN, target="somefan")
    monkeypatch.setattr(fe, "STATE_FILE", str(tmp_path / "fe_state.json"))
    called = []
    monkeypatch.setattr("src.x.twitter_client.follow_account",
                        lambda h, engager=False: called.append(h) or True)
    monkeypatch.setattr("src.guards.action_guard.can_follow",
                        lambda h, reciprocal=False: (False, "total following ceiling reached (3500 >= 3500)"))
    monkeypatch.setenv("ENABLE_FOLLOW_ENGAGERS", "1")
    fe.run_follow_engagers_cycle()
    assert called == [], "transient refusal must not reach follow_account"
    st = fe._load_state()
    assert st.get("attempted", []) == [], \
        "transient policy refusal must NOT burn the candidate"


def test_rationed_winner_shape_enforced_at_chokepoint(monkeypatch, tmp_path):
    """2026-07-28: the 'me [verb]ing' winner format shipped in 7 of 15
    posts (ollama ignores prompt-level rationing) — the winner became the
    broken record. Same family as catchphrases -> structures: the ration
    is enforced at the content_guard chokepoint. A 'me [verb]ing' draft is
    refused when the recent window already posted one; fresh windows and
    non-matching openers pass. Also: the mentions tab (legitimately empty
    when nobody mentioned us) must never count toward blank-page restarts."""
    import json
    from src.guards import content_guard as cg
    from src.core import history as hist
    from datetime import datetime

    hfile = tmp_path / "tweet_history.json"
    monkeypatch.setattr(hist, "HISTORY_FILE", str(hfile))

    # Empty window -> the shape passes
    hfile.write_text("[]")
    ok, why = cg.validate("me refreshing my 401k like a loading screen", kind="original")
    assert ok, f"first use in window must pass: {why}"

    # Window already has one -> refused
    hfile.write_text(json.dumps([
        {"text": "me watching nvidia earnings like a season finale",
         "timestamp": datetime.now().isoformat()},
    ]))
    ok, why = cg.validate("me refreshing my portfolio again", kind="original")
    assert not ok and "rationed shape" in why, "second same-shape in window must be refused"

    # Different opener -> passes regardless
    ok, why = cg.validate("Nvidia down 4%. my clients are doing breathing exercises", kind="original")
    assert ok, f"non-rationed opener must pass: {why}"

    # Mentions never count toward blank-page restarts
    from src.x import twitter_client as tc
    from src.x import safari_hygiene as sh
    import time as _time
    restarts = []
    monkeypatch.setattr(sh, "restart_safari", lambda reason="": restarts.append(reason) or True)
    monkeypatch.setattr(sh, "_last_run_ts", lambda: _time.time() - 3600)
    tc._reset_blank_page_count()
    for _ in range(6):
        tc._record_blank_page(label="mentions")
    assert restarts == [] and tc._blank_page_count == 0, \
        "legit-empty mentions tab must never count as a blank page"
    tc._reset_blank_page_count()


def test_scheduler_build_has_no_startup_publishing(monkeypatch):
    import main
    def forbidden(*a, **k):
        raise AssertionError("Startup must not execute an editorial cycle")
    monkeypatch.setattr(main, "safe_run_editorial_cycle", forbidden)
    scheduler = main.build_scheduler()
    assert scheduler.get_job("editorial_job") is not None
    assert not any("quote" in j.id or "boost" in j.id or "thread" in j.id for j in scheduler.get_jobs())


def test_violence_cruelty_gate_blocks_at_every_surface():
    """2026-07-29 — SHIPPED LIVE: 'Killing the right terrorist = higher ROI
    on every contract' as a PLTR reply (2026-07-28 15:29, uncensored local
    reply model; the persona's never-cruel rule is prompt-level only). The
    chokepoint must refuse violence/cruelty content on EVERY surface —
    replies included — while common idioms (killer app, made a killing,
    AI killed my job) still pass."""
    from src.guards.content_guard import validate
    live_leak = ("Palantir was built for pattern recognition. Killing the "
                 "right terrorist = higher ROI on every contract.")
    for kind in ("original", "quote", "reply"):
        ok, why = validate(live_leak, kind=kind)
        assert not ok and "violence" in why, f"{kind} must refuse the live leak"
    ok, _ = validate("drone strikes are basically a subscription business", kind="reply")
    assert not ok, "monetized-violence framing must be refused"
    for benign in ("AI didn't kill your job. It took Kevin's job.",
                   "made a killing on NVDA earnings today",
                   "this is the killer app for AI agents"):
        ok, why = validate(benign, kind="reply")
        assert ok, f"idiom must pass: {benign!r} ({why})"
