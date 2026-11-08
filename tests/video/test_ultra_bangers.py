from copy import deepcopy
from dataclasses import replace

import pytest

from src.video import bangers, editing, ranking


@pytest.fixture
def ultra(video_cfg):
    return replace(video_cfg, auto_edit=True, bangers_only=True,
                   ultra_bangers_only=True, min_hook_score=9, max_age_hours=730 * 24)


@pytest.mark.parametrize("key", bangers.JUDGMENTS)
@pytest.mark.parametrize("value", [8.9, None, float("nan"), True])
def test_each_editorial_component_must_be_exceptional(ready, ultra, at, key, value):
    doc = ready()
    doc["inspection"]["banger_scores"][key] = value
    doc["ranking"]["components"] = {"momentum": 25}
    assert ranking.source_score_gate(doc, ultra, at().timestamp())


def test_strong_but_ordinary_scores_cannot_use_views_or_freshness_to_pass(ready, ultra, at):
    doc = ready()
    doc["inspection"]["banger_scores"] = dict.fromkeys(bangers.JUDGMENTS, 9)
    doc["ranking"]["components"] = {"momentum": 25}
    result = bangers.score(doc, at().timestamp(), source=True)
    assert result["total"] > 88 and result["editorial_total"] == 90
    assert "95/100" in ranking.source_score_gate(doc, ultra, at().timestamp())


def test_exceptional_old_unseen_source_can_pass_without_invented_momentum(ready, ultra, at):
    doc = ready()
    doc["published_at"] = at().timestamp() - 400 * 86400
    assert not ranking.source_score_gate(doc, ultra, at().timestamp())
    scored = bangers.score(doc, at().timestamp(), source=True)
    assert scored["editorial_total"] == 100 and scored["total"] >= ultra.banger_min_score
    assert scored["measured_momentum"] is None


@pytest.mark.parametrize("field,value", [("fit_score", 18), ("entertainment_score", 18), ("quality_score", 13)])
def test_secondary_source_quality_floors_still_apply(ready, ultra, at, field, value):
    doc = ready()
    doc["inspection"][field] = value
    assert ranking.source_score_gate(doc, ultra, at().timestamp())


def test_output_gets_independent_ultra_and_opening_review(ready, ultra):
    doc = ready()
    qc = deepcopy(doc["inspection"]) | {"opening": {"hook_score": 9, "cast_visible_first_second": True,
        "action_first_second": True, "no_dead_intro": True}, "opening_samples_reviewed": True,
        "opening_sample_times": [0, .2, .4, .6, .8]}
    assert not editing.banger_refusal(qc, ultra, output=True)
    qc["opening"]["hook_score"] = 8
    assert "first second" in editing.banger_refusal(qc, ultra, output=True)
    qc["opening"]["hook_score"] = 9
    qc["banger_scores"]["performance"] = 8.9
    assert "9/10" in editing.banger_refusal(qc, ultra, output=True)


def test_explicit_selection_cannot_waive_ultra_review(ready, ultra, at, monkeypatch):
    doc = ready()
    monkeypatch.setattr(ranking, "selected", lambda *a: True)
    doc["inspection"]["banger_scores"]["quality"] = 8
    assert ranking.source_score_gate(doc, ultra, at().timestamp())


def test_ultra_policy_invalidates_previous_edit_review(ultra):
    assert editing.policy_revision(ultra) != editing.policy_revision(replace(ultra, ultra_bangers_only=False))


@pytest.mark.parametrize("change", [{"bangers_only": False}, {"auto_edit": False}, {"min_hook_score": 8}])
def test_ultra_requires_all_review_prerequisites(ultra, change):
    with pytest.raises(ValueError, match="ultra bangers"):
        replace(ultra, **change)
