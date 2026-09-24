"""Constrain local editorial output before applying factual/quality checks."""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "text": {"type": "string", "maxLength": 250},
        "angle": {"type": "string", "maxLength": 160},
        "takeaway": {"type": "string", "maxLength": 200},
        "evidence_ids": {"type": "array", "maxItems": 3,
                         "items": {"type": "string", "enum": [str(i) for i in range(40)]}},
        "skip": {"type": "boolean"},
    },
    "required": ["source_id", "text", "angle", "takeaway", "evidence_ids"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        **{key: {"type": "boolean"} for key in (
            "approved", "grounded", "ai_relevant", "adds_value", "natural_voice", "novel", "exceptional",
            "trending")},
        "reason": {"type": "string", "maxLength": 600},
    },
    "required": ["approved", "grounded", "ai_relevant", "adds_value",
                 "natural_voice", "novel", "exceptional", "trending", "reason"],
    "additionalProperties": False,
}
