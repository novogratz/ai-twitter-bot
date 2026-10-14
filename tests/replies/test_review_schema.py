import json

import pytest

from src.replies import review_schema


def test_each_review_is_bound_to_a_required_distinct_id():
    properties = {"score": {"type": "integer", "minimum": 0, "maximum": 100}}
    schema = review_schema.keyed(["first", "second"], properties)["properties"]["reviews"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert schema["required"] == ["first", "second"]
    assert set(schema["properties"]) == {"first", "second"}
    assert all(item["properties"] == properties and item["required"] == ["score"]
               for item in schema["properties"].values())
    assert review_schema.read('{"reviews":{"second":{"score":98},"first":{"score":20}}}',
                              ["first", "second"]) == [dict(id="first", score=20), dict(id="second", score=98)]


@pytest.mark.parametrize("text", [
    '{"reviews":{"first":{},"first":{}}}',
    '{"reviews":{"first":{"score":10,"score":99},"second":{}}}',
    '{"reviews":{"first":{},"second":{}},"reviews":{"first":{},"second":{}}}',
    '{"reviews":{"first":{}}}',
    '{"reviews":{"first":{},"second":{},"invented":{}}}',
    '{"reviews":{"first":{"id":"second"},"second":{}}}',
    '{"reviews":{"first":99,"second":{}}}',
    '{"reviews":[{"id":"first"},{"id":"first"}]}',
    '{"reviews":[],"approved":true}',
    'null',
])
def test_ambiguous_missing_or_invented_reviews_never_approve(text):
    with pytest.raises(ValueError):
        review_schema.read(text, ["first", "second"])


@pytest.mark.parametrize("ids", [[], ["first", "first"]])
def test_schema_refuses_invalid_candidate_ids(ids):
    with pytest.raises(ValueError):
        review_schema.keyed(ids, {"score": {"type": "integer"}})
