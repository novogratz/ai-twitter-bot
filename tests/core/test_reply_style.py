"""Reply variety follows actual shipped history and survives process restarts."""
import csv
import random

from src.core import config, reply_style as style


BRIEF = "Latency wins here."
STANDARD = "Smaller batches can cut latency, but throughput is a different tradeoff."


def history(texts, kind="reply", mode="w"):
    with open(config.ENGAGEMENT_LOG_FILE, mode, newline="") as stream:
        csv.writer(stream).writerows(("2026-10-12", kind, text) for text in texts)


def test_empty_history_can_choose_every_format_without_a_rotation():
    rng = random.Random(12)
    picked = [style.choose(rng=rng).name for _ in range(1000)]
    assert set(picked) == {"brief", "standard", "detailed", "reaction"}
    assert picked.count("reaction") < picked.count("detailed") < picked.count("brief")


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


def test_a_smiley_waits_for_twenty_other_shipped_replies():
    history(["🙂"] + [BRIEF, STANDARD] * 9 + [BRIEF])
    rng = random.Random(12)
    assert all(style.choose(rng=rng).name != "reaction" for _ in range(50))
    history([STANDARD], mode="a")
    assert "reaction" in {style.choose(rng=rng).name for _ in range(100)}


def test_operator_can_disable_reactions_and_tighten_text_floor(settings_override):
    settings_override(REPLY_ALLOW_REACTIONS=False, REPLY_MIN_CHARS=180)
    rng = random.Random(12)
    assert {style.choose(rng=rng).name for _ in range(30)} == {"detailed"}


def test_startup_formats_remain_at_most_twenty_words():
    rng = random.Random(12)
    selected = [style.choose(concise=True, rng=rng) for _ in range(100)]
    assert {s.name for s in selected} == {"brief", "standard", "reaction"}
    assert all(s.max_words <= 20 for s in selected)
