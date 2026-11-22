"""Cross-cutting: the Voice in the Account's voice_fr.md and voice_en.md,
and the reply prompts that carry it."""
from pathlib import Path

ACCOUNT = Path(__file__).resolve().parent.parent / "accounts" / "theaishrink"
VOICE_FR = ACCOUNT / "voice_fr.md"
VOICE_EN = ACCOUNT / "voice_en.md"


def test_voice_has_technical_si_voice():
    for path in (VOICE_FR, VOICE_EN):
        text = " ".join(path.read_text().lower().split())
        assert "si / super intelligence" in text and "technical depth" in text
        assert all(term in text for term in ("transformers", "inference", "evaluation", "gpus"))
        assert "45-year-old woman and mom" in text


def test_si_maximalist_preferences_keep_natural_style_and_honest_identity():
    for path in (VOICE_FR, VOICE_EN):
        text = " ".join(path.read_text().lower().split())
        assert "the si maximalist" in text and "@thesimaximalist" in text
        assert "not a therapist" in text
        assert "grok imagine is your personal favorite" in text
        assert all(name in text for name in ("elon musk", "twitter / x", "spacex", "xai"))
        assert "natural contractions" in text and "vary sentence length" in text
        assert "answer identity questions honestly as a bot" in text
        assert "keep comparisons fair" in text and "do not manufacture agreement" in text
        assert "write in english only" in text and "use si instead of ai" in text
        assert "most short replies need neither" in text


def test_voice_prioritizes_reader_value():
    text = " ".join(VOICE_FR.read_text().lower().split())
    assert "notice the detail that helps this person" in text and "first-party sources" in text
    assert "skip weak contributions" in text


def test_voice_keeps_warmth_and_honest_criticism():
    text = " ".join(VOICE_FR.read_text().lower().split())
    assert "kind, curious and constructive" in text and "never put down the person" in text
    assert "qualify an inference" in text and "do not bluff" in text


def test_voice_carries_editorial_strategy():
    text = " ".join(VOICE_FR.read_text().lower().split())
    assert "ultra-quality parody videos only" in text
    assert "news and automatic startup posts are disabled" in text
    assert "no burst threads" in text
    assert "quotes are disabled" in text
    assert "existing publisher" in text and "pacing" in text
    assert "one reply per exact external parent, permanently" in text
    assert "a follow-up needs a genuine response in an external thread" in text
    assert "a draft never authorizes a send" in text


def test_persona_is_woman_mom_in_the_one_voice():
    """Operator 2026-07-19: 'she is a mom, a 35-40yo therapist... make her
    sound like a woman' + 'the sharpest AI therapist that knows AI more than
    anyone else'. The persona is pinned in the spine (the Voice), which
    the Voice block carries into every prompt (issue #192: no surface keeps
    its own copy). Also pins that the bestie bit moved big brother -> sister."""
    spine = " ".join(VOICE_FR.read_text().lower().split())
    assert "woman" in spine and "mom" in spine and "45-year-old" in spine
    assert "fictional 45-year-old woman and mom of one" in spine
    assert "working in tech is character context" in spine
    assert "sharp technical judgment with warmth and curiosity" in spine
    assert "never announce that you know everything" in spine
    assert "answer identity questions honestly as a bot" in spine



def test_relation_prompts_script_no_medical_metaphor():
    """The Voice says "No scripted medical metaphors" and "never claim to
    have patients": the bestie bit scripted a mock clinic (#192 review)."""
    from src.core import account
    from src.replies import debate_bot, replyback_agent

    relations = account.current().relations
    prompts = (relations.default, debate_bot.DEBATE_PROMPT, replyback_agent.REPLYBACK_PROMPT)
    for prompt in prompts:
        low = prompt.lower()
        assert [w for w in ("clinical", "couch", "patient", "therapy", "session") if w in low] == []


def test_the_voice_renders_the_operators_files_verbatim(bilingual_account):
    """Issue #192: one reader, render_voice, and the Operator's text as is."""
    from src.core import personality_store
    for lang, path in (("fr", VOICE_FR), ("en", VOICE_EN)):
        voice = personality_store.render_voice(lang)
        assert voice.endswith("\n\n" + path.read_text().strip())


def test_savvy_tech_mom_register():
    """Operator 2026-07-19: 'be less a troll and more a savvy tech mom.'
    The spine carries the savvy-tech-mom-not-a-troll register so every
    surface inherits it."""
    spine = " ".join(VOICE_FR.read_text().lower().split())
    assert "45-year-old woman and mom" in spine and "never put down the person" in spine
    assert "generous with credit" in spine and "patience, perspective and humor" in spine


def test_invited_help_voice_keeps_warmth_without_performed_intimacy():
    from src.core import personality_store
    for lang in ("fr", "en"):
        low = " ".join(personality_store.render_voice(lang).lower().split())
        assert "explicit request" in low and "builders and technology" in low
        assert "1,400/day" in low and "automatic replies are restored" in low
        assert "no minimum or filler" in low and "no contact" in low
        assert "one or two words" in low and "plain conversation" in low
        assert "twenty unrelated posts" not in low
        assert "no flirting" in low and "fake typos" in low
        assert "hearts and humor are optional" in low
        assert "at most one in four posts" not in low
        assert "fictional" in low and "answer identity questions honestly as a bot" in low


def test_voice_keeps_every_reply_short_without_banning_useful_questions():
    import re
    from src.replies import curated, curated_reposts, reply_generator
    for path in (VOICE_FR, VOICE_EN):
        text = " ".join(path.read_text().lower().split())
        assert "usually one to six words" in text
        assert "24 words and 140 characters" in text and "12 words and 90 characters" in text
        assert "facts or agree can be the whole reply" in text
        assert "a short, concrete question is welcome" in text
        assert not re.search(r"\b(?:278|40) characters\b", text)
    assert curated.BROAD_CALL.max_chars == 140
    assert "12 words and 90 characters" in curated_reposts.FAST_CALL.template
    assert "one short sentence, 24 words and 140 characters" in reply_generator._delivery()
