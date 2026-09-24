"""src/x/twitter_client: metadata, URL, hashtag and header scrubbing at the
write chokepoint."""


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


def test_gif_tag_scrubbed_at_chokepoint():
    from src.x.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("take here\n[GIF: kermit panic]")
    assert "[GIF" not in out and "take here" in out


def test_post_urls_stripped():
    from src.x.twitter_client import _strip_post_urls
    out = _strip_post_urls("Big take here.\n\nhttps://cnbc.com/article/xyz")
    assert "http" not in out and "Big take here." in out


def test_hashtags_stripped_at_chokepoint():
    from src.x.twitter_client import _scrub_metadata_leaks
    out = _scrub_metadata_leaks("the market needs therapy #Bitcoin #AI")
    assert "#" not in out and "therapy" in out


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
