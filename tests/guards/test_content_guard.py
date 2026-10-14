"""src/guards/content_guard: dedup, price targets, language, truncation,
burned phrases and shapes, violence."""
import pytest

from src.guards import content_guard as cg


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


def test_dedup_text_window_read_at_call_time(monkeypatch, settings_override):
    from datetime import datetime, timedelta
    from src.core import history

    posted = (datetime.now() - timedelta(hours=60)).isoformat()
    monkeypatch.setattr(history, "load_history", lambda: [{
        "timestamp": posted,
        "text": "Everyone watches GPU supply. The real bottleneck is the power bill",
    }])
    draft = ("Everyone is tracking GPU supply. The real bottleneck is the power bill. "
             "You are buying silicon; you are renting electricity.")

    assert not cg.is_duplicate(draft)
    settings_override(DUP_TEXT_WINDOW_HOURS=72.0)
    assert cg.is_duplicate(draft)


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


def test_price_gate_cannot_be_switched_off(settings_override):
    """#201: BAN_SHORT_TERM_PRICE_TARGETS has floor 1, so 0 changes nothing."""
    text = ("Analysts keep repeating one line this week: $NVDA to $200 by friday. "
            "Datacenter demand is real, but a four-day price call is a coin flip "
            "wearing a suit.")

    settings_override(BAN_SHORT_TERM_PRICE_TARGETS=False)
    assert cg.validate(text) == (
        False, "near-term price target (price + near-term timeframe)")


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


# --- truncation guard (the "botched ChatGPT paste" callout, 2026-06-05) -------


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


def test_validate_refuses_unknown_kind():
    """A retired kind such as "quote" matches no surface gate: it would skip
    the language and length checks in silence, so it must raise instead."""
    for kind in ("quote", "post", ""):
        with pytest.raises(ValueError, match="unknown content kind"):
            cg.validate("a sharp take on the benchmark gap", kind=kind)


# --- skips, burned phrases and shapes, violence ------------------------------


def test_skip_rationale_never_publishes():
    """2026-06-07 live leak: the model wrote 'SKIP.' + its whole rationale
    ('The tweet is incomplete (cuts off mid-sentence)...') and an
    exact-match SKIP check published it as a reply. Pinned here at the
    content_guard chokepoint; the Reply generator's side is pinned in
    tests/replies/test_reply_generator.py."""
    from src.guards import content_guard as cg
    ok, why = cg.validate("SKIP. The tweet is incomplete (cuts off mid-sentence at 'rema'), "
                          "and the angle is generic crypto psychology.", kind="reply")
    assert not ok and "SKIP" in why
    ok, _ = cg.validate("skip", kind="reply")
    assert not ok
    # Legitimate text containing 'skip' mid-sentence still passes.
    ok, _ = cg.validate("Most investors skip the part where conviction gets tested.", kind="reply")
    assert ok


def test_burned_catchphrases_blocked_at_chokepoint():
    """2026-06-09: the prompts quoted exemplar phrases ("we are so early",
    "okay this is genuinely...") and the model parroted them — 6+ posts in
    one day carried the same catchphrase, every one 0 likes. The exemplars
    are gone from the prompts and the chokepoint refuses the burned phrases
    on originals. Replies are unaffected."""
    from src.guards import content_guard as cg

    burned = "Wild launch today. We are so early, most people can't feel it yet."
    ok, why = cg.validate(burned, kind="original")
    assert not ok and "catchphrase" in why, f"original must refuse burned phrase: {why}"

    ok, _ = cg.validate(
        "We are so early on this one — the benchmark gap doubled in a single "
        "release and the pricing didn't move.", kind="reply")
    assert ok, "replies are not gated on catchphrases"

    fresh, _ = cg.validate("Nvidia's quarter was a therapy session disguised as an earnings call.", kind="original")
    assert fresh, "normal originals must still pass"


def test_burned_structure_contrast_reframe_blocked():
    """2026-06-10 humanize mandate: after the catchphrase ban the model
    migrated to the contrast-reframe skeleton ("That's not fear, that's a
    crush") — 6+ ships in 40 posts, the new tell that got the account
    publicly spotted as a bot. The chokepoint must refuse the SHAPE for
    originals; replies and innocent text stay unaffected."""
    from src.guards import content_guard

    burned = [
        "Everyone in the thread is calling this fear but that's not fear, that's a crush on the future.",
        "The whole timeline calls it skepticism. that's not skepticism, it's grief about the old world.",
        "Everyone watching the chart thinks the market is broken. This isn't a dip. It's a discount.",
    ]
    for text in burned:
        ok, why = content_guard.validate(text, kind="original")
        assert not ok and "burned structure" in why, f"should block: {text!r}"

    fine = [
        "Nvidia sold out its 2027 supply before the keynote ended. the buildout is real",
        "I've read this three times and I still can't believe it's real",
    ]
    for text in fine:
        ok, why = content_guard.validate(text, kind="original")
        assert ok, f"false positive on {text!r}: {why}"


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
    from datetime import datetime

    hfile = tmp_path / "tweet_history.json"

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
    from src.x import scraper
    from src.x import safari_hygiene as sh
    import time as _time
    restarts = []
    monkeypatch.setattr(sh, "restart_safari", lambda reason="": restarts.append(reason) or True)
    monkeypatch.setattr(sh, "_last_run_ts", lambda: _time.time() - 3600)
    scraper._reset_blank_page_count()
    for _ in range(6):
        scraper._record_blank_page(label="mentions")
    assert restarts == [] and scraper._blank_page_count == 0, \
        "legit-empty mentions tab must never count as a blank page"
    scraper._reset_blank_page_count()


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
    for kind in ("original", "reply"):
        ok, why = validate(live_leak, kind=kind)
        assert not ok and "violence" in why, f"{kind} must refuse the live leak"
    ok, _ = validate("drone strikes are basically a subscription business", kind="reply")
    assert not ok, "monetized-violence framing must be refused"
    for benign in ("AI didn't kill your job. It took Kevin's job.",
                   "made a killing on NVDA earnings today",
                   "this is the killer app for AI agents"):
        ok, why = validate(benign, kind="reply")
        assert ok, f"idiom must pass: {benign!r} ({why})"
