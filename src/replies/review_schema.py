"""Structured comparisons require one distinct review for every supplied ID."""
import json


def keyed(ids: list, properties: dict) -> dict:
    """Fixed object keys prevent an array from repeating its first review."""
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("review IDs must be nonempty and unique")
    item = {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}
    return {"type": "object", "properties": {"reviews": {
        "type": "object", "properties": {key: item for key in ids},
        "required": ids, "additionalProperties": False}},
        "required": ["reviews"], "additionalProperties": False}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate review field: {key}")
        result[key] = value
    return result


def read(text: str, ids: list) -> list:
    """Return rows in input order; never silently overwrite duplicate keys."""
    payload = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"reviews"}:
        raise ValueError("expected a reviews object")
    reviews = payload["reviews"]
    if not isinstance(reviews, dict) or set(reviews) != set(ids):
        raise ValueError("review keys must match every supplied ID exactly")
    if any(not isinstance(value, dict) or "id" in value for value in reviews.values()):
        raise ValueError("each review must be an object identified only by its key")
    return [{"id": key, **reviews[key]} for key in ids]
