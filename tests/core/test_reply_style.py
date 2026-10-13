"""Reply variety follows actual shipped history and survives process restarts."""
import csv
import random
import pytest

from src.core import config, reply_style as style, settings


BRIEF = "Latency wins here."
STANDARD = "Smaller batches can cut latency, but throughput is a different tradeoff."


def history(texts, kind="reply", mode="w"):
    with open(config.ENGAGEMENT_LOG_FILE, mode, newline="") as stream:
        csv.writer(stream).writerows(("2026-10-12", kind, text) for text in texts)


def test_empty_history_can_choose_every_format_without_a_rotation():
    rng = random.Random(12)
    picked = [style.choose(rng=rng).name for _ in range(1000)]
    assert set(picked) == {"brief", "standard", "detailed"}
    assert picked.count("detailed") < picked.count("brief") < picked.count("standard")


def test_shipped_history_prevents_three_replies_of_the_same_shape():
    history([BRIEF, "Context matters more."])
    rng = random.Random(12)
    assert all(style.choose(rng=rng).name != "brief" for _ in range(50))
    # A subsequent shipped reply changes the decision without any cached state.
    history([STANDARD], mode="a")
    assert "brief" in {style.choose(rng=rng).name for _ in range(50)}


def test_likes_and_failed_writes_do_not_shape_replies():
    history([BRIEF, "Context matters more."], kind="like")
    history(["🙂"], kind="failed", mode="a")
    assert style.recent_replies() == []


def test_historical_smileys_never_reenable_reaction_formats(settings_override):
    settings_override(REPLY_ALLOW_REACTIONS=True)
    assert settings.get("REPLY_ALLOW_REACTIONS") is False
    history(["🙂"] + [BRIEF, STANDARD] * 9 + [BRIEF])
    rng = random.Random(12)
    assert all(style.choose(rng=rng).name != "reaction" for _ in range(50))
    history([STANDARD], mode="a")
    assert "reaction" not in {style.choose(rng=rng).name for _ in range(100)}


def test_operator_can_disable_reactions_and_tighten_text_floor(settings_override):
    settings_override(REPLY_ALLOW_REACTIONS=False, REPLY_MIN_CHARS=180)
    rng = random.Random(12)
    assert {style.choose(rng=rng).name for _ in range(30)} == {"detailed"}


def test_startup_formats_remain_at_most_twenty_words():
    rng = random.Random(12)
    selected = [style.choose(concise=True, rng=rng) for _ in range(100)]
    assert {s.name for s in selected} == {"brief", "standard"}
    assert all(s.max_words <= 20 for s in selected)


@pytest.mark.parametrize("text", ["Latency wins 🙂", "Latency wins:)", "Latency wins ;-)"])
def test_text_formats_refuse_smileys_appended_to_prose(text):
    assert "not allowed" in style.STYLES[0].problem(text)


def test_every_reply_gets_one_of_the_three_random_endings():
    rng = random.Random(12)
    endings = [style.split_ending(style.finish_reply(BRIEF, rng=rng))[1] for _ in range(100)]
    assert set(endings) == {"😂", "💀", "😂💀"}
    assert any(a == b for a, b in zip(endings, endings[1:])), "no fixed rotation"


@pytest.mark.parametrize("ending", ["😂", "💀", "😂💀"])
def test_chosen_endings_survive_repeated_finishing(ending):
    draft = f"{BRIEF} {ending}"
    assert style.finish_reply(draft) == draft
    assert style.split_ending(draft) == (BRIEF, ending)


def test_endings_do_not_change_shipped_length_history():
    body = "One two three four five six seven eight."
    history([body + " 😂", body + " 😂💀"])
    rng = random.Random(12)
    assert all(style.choose(rng=rng).name != "brief" for _ in range(30))
