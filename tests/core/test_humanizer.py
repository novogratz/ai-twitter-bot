"""src/core/humanizer: trimming, typos, dashes and casual texture."""
from src.guards import content_guard as cg


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


# --- dashes and casual texture --------------------------------------------------


def test_bare_dash_replacement_keeps_spacing():
    """2026-06-07: '—' → ',' produced 'angle,conviction' in a live reply.
    Bare dashes must become ', ' with normalized spacing, in humanize AND
    at the reply chokepoint."""
    from src.core.humanizer import humanize, strip_dashes
    out = humanize("The angle—conviction through crashes—is generic and it shows badly.")
    assert ",conviction" not in out and ", conviction" in out
    # Reply admission shares the same cleanup for paths that skip humanize.
    assert strip_dashes("The angle—conviction — is generic") == "The angle, conviction. is generic"


def test_setup_colon_refused_and_dotdot_texture_kept():
    """Meme-account texture, introduced 2026-06-10:
    (1) a reply ending with a setup-colon ("[actor] watching X:") is refused
    as truncated (the GIF chokepoints that allowed it are removed, #111);
    (2) humanize() must preserve the human ".." / "..." texture (only 4+
    dots is an artifact); (3) casualize() never strips a ".." ending."""
    from src.guards import content_guard
    from src.core.humanizer import humanize, casualize

    setup = "Goldman Sachs watching retail buy the dip at 110x revenue:"
    ok, why = content_guard.validate(setup, kind="reply")
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
