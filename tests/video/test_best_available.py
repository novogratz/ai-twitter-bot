from copy import deepcopy
from dataclasses import replace
import json

import pytest

from src.video import bangers, editing, inventory, publisher, ranking, reconcile


@pytest.fixture
def fallback(video_cfg):
    return replace(video_cfg, auto_edit=True, bangers_only=True, ultra_bangers_only=True,
                   min_hook_score=9, best_available_fallback=True, max_age_hours=730 * 24)


@pytest.fixture
def reviewed(ready, video_store, fallback, at):
    def add(ident="clip1", grade=7, raw_score=95):
        doc = ready(ident, score=raw_score)
        doc["inspection"].update(banger_scores=dict.fromkeys(bangers.JUDGMENTS, grade),
            fit_score=grade * 2, entertainment_score=grade * 2, quality_score=grade * 1.5,
            edit={"start_seconds": 0, "end_seconds": 20, "cast": ["performer"],
                  "hook_score": grade, "cast_visible_first_second": True,
                  "action_first_second": True, "reason": "Complete observed performance"})
        doc["edit"] = editing.plan(doc["inspection"], doc["probe"], fallback, doc["original_sha256"])
        doc["qc"].update(deepcopy(doc["inspection"]),
            opening={"hook_score": grade, "cast_visible_first_second": True,
                     "action_first_second": True, "no_dead_intro": True},
            opening_samples_reviewed=True, opening_sample_times=[0, .2, .4, .6, .8],
            probe={"duration": 20}, edit=doc["edit"])
        video_store.save_candidate(ident, doc, at().timestamp(), state="ready", score=raw_score)
        return doc
    return add


def test_below_target_reaches_preparation_and_final_admission(reviewed, fallback, at):
    doc = reviewed(grade=6)
    before = deepcopy(doc)
    assert not ranking.gate(doc, fallback, at().timestamp(), final=True)
    assert not ranking.source_score_gate(doc, fallback, at().timestamp())
    assert not reconcile.preparation_reason(doc, fallback, at().timestamp())
    assert bangers.score(doc, at().timestamp(), best_available=True)["editorial_total"] == 60
    assert doc == before  # never inflate saved ratings or replace unknown popularity
    assert ranking.gate(doc, replace(fallback, best_available_fallback=False), at().timestamp(), final=True)


def test_publisher_picks_best_actual_quality_over_popularity_or_discovery_order(
        reviewed, video_store, fallback, at):
    reviewed("popular", grade=6, raw_score=100)
    reviewed("best", grade=8, raw_score=50)
    reviewed("middle", grade=7, raw_score=90)
    assert publisher.reserve(video_store, at(), fallback)["candidate"] == "best"
    assert publisher.reserve(video_store, at(), fallback) is None


def test_best_clip_beyond_eighty_popular_candidates_still_competes(
        reviewed, video_store, fallback, at):
    for i in range(80):
        reviewed(f"popular{i}", grade=6, raw_score=100)
    reviewed("best", grade=8, raw_score=50)
    assert publisher.reserve(video_store, at(), fallback)["candidate"] == "best"


def test_quality_target_takes_precedence_over_fallback(reviewed, video_store, fallback, at):
    reviewed("fallback", grade=8.9, raw_score=100)
    reviewed("target", grade=10, raw_score=50)
    assert publisher.reserve(video_store, at(), fallback)["candidate"] == "target"


@pytest.mark.parametrize("change", [
    {"unsafe": True}, {"audio_inspected": False}, {"brand_fit": False},
    {"language_dependent": True}, {"cast": []}, {"sha256": "changed"},
    {"banger_scores": dict.fromkeys(bangers.JUDGMENTS, float("nan"))},
])
def test_fallback_never_waives_source_evidence(reviewed, fallback, at, change):
    doc = reviewed()
    doc["inspection"].update(change)
    assert ranking.gate(doc, fallback, at().timestamp(), final=True)


@pytest.mark.parametrize("field,value", [
    ("audio_inspected", False), ("decoded", False), ("watermark_present", False),
    ("unsafe", True), ("opening_samples_reviewed", False), ("sha256", "changed"),
    ("brand_fit", False), ("language_dependent", True),
])
def test_fallback_never_waives_output_evidence(reviewed, fallback, at, field, value):
    doc = reviewed()
    doc["qc"][field] = value
    assert ranking.gate(doc, fallback, at().timestamp(), final=True)


@pytest.mark.parametrize("novelty", [
    {"state": "unchecked"}, {"state": "known_high_reach_match"},
    {"state": "verified_low_reach_match", "matching_copies": []},
    {"state": "checked_no_match", "checked_at": 1},
])
def test_fallback_still_needs_fresh_complete_x_checks(reviewed, fallback, at, novelty):
    doc = reviewed()
    doc["novelty"] = {"checked_at": at().timestamp(), **novelty}
    assert ranking.gate(doc, fallback, at().timestamp(), final=True)


def test_permanent_duplicate_is_skipped_for_next_best(reviewed, video_store, fallback, at):
    old = reviewed("duplicate", grade=10)
    old["canonical_url"] = "https://www.instagram.com/reel/other-link"
    with video_store.transaction() as db:
        db.execute("INSERT INTO history VALUES(?,?,?)", ("123456", at().timestamp() - 86400, json.dumps(old)))
    reviewed("fresh", grade=6)
    assert publisher.reserve(video_store, at(), fallback)["candidate"] == "fresh"
    assert video_store.candidate("duplicate")["state"] == "held"


def test_fallback_inventory_does_not_expire_at_a_quality_boundary(reviewed, fallback):
    doc = reviewed(grade=6)
    assert inventory.usable_until(doc, fallback) == min(doc["published_at"] + fallback.max_age_hours * 3600,
                                                       ranking.permission_expiry(doc, fallback))


def test_policy_change_reinspects_and_cannot_disable_review(fallback):
    assert editing.policy_revision(fallback) != editing.policy_revision(replace(fallback, best_available_fallback=False))
    with pytest.raises(ValueError):
        replace(fallback, auto_edit=False)
    with pytest.raises(ValueError):
        replace(fallback, best_available_fallback=1)


@pytest.mark.parametrize("field", ["cast_visible_first_second", "action_first_second", "no_dead_intro"])
def test_weak_observed_opening_is_fallback_but_missing_observation_is_not(reviewed, fallback, field):
    doc = reviewed()
    doc["qc"]["opening"][field] = False
    assert not ranking.output_gate(doc, fallback)
    doc["qc"]["opening"][field] = None
    assert ranking.output_gate(doc, fallback)
