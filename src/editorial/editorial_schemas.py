"""The Draft and the Editor's review: their limits, the JSON schemas built
from them, and the call profiles that send those schemas to the model.

Each limit below lives here only. The schemas, and editorial_bot's prompts and
checks, read it at call time: changing one changes all three."""
import os

from ..core.llm_client import CallProfile, Output

TEXT_MAX_CHARS = 250
# Exact source sentences offered as Evidence, and how many a Draft may cite.
EVIDENCE_PASSAGES = 40
EVIDENCE_IDS_MAX = 3
# The Editor must set every approval flag; the Exceptional slot also needs
# EXCEPTIONAL_FLAG, a Trend slot TREND_FLAG.
APPROVAL_FLAGS = ("approved", "grounded", "ai_relevant", "adds_value", "natural_voice", "novel")
EXCEPTIONAL_FLAG = "exceptional"
TREND_FLAG = "trending"


def review_flags() -> tuple:
    """Every boolean field of the review, in the order the Editor sees them."""
    return (*APPROVAL_FLAGS, EXCEPTIONAL_FLAG, TREND_FLAG)


def draft_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "text": {"type": "string", "maxLength": TEXT_MAX_CHARS},
            "angle": {"type": "string", "maxLength": 160},
            "takeaway": {"type": "string", "maxLength": 200},
            "evidence_ids": {"type": "array", "maxItems": EVIDENCE_IDS_MAX,
                             "items": {"type": "string",
                                       "enum": [str(i) for i in range(EVIDENCE_PASSAGES)]}},
            "skip": {"type": "boolean"},
        },
        "required": ["source_id", "text", "angle", "takeaway", "evidence_ids"],
        "additionalProperties": False,
    }


def review_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            **{key: {"type": "boolean"} for key in review_flags()},
            "reason": {"type": "string", "maxLength": 600},
        },
        "required": [*review_flags(), "reason"],
        "additionalProperties": False,
    }


def _profile(schema: dict, temperature: float) -> CallProfile:
    return CallProfile(
        ollama_model=os.environ.get("EDITORIAL_OLLAMA_MODEL", "gemma4:31b"),
        schema=schema,
        temperature=temperature,
        min_timeout=int(os.environ.get("EDITORIAL_LLM_TIMEOUT_SECONDS", "300")),
        output=Output.JSON,
    )


def draft_profile() -> CallProfile:
    return _profile(draft_schema(), 0.65)


def review_profile() -> CallProfile:
    return _profile(review_schema(), 0.2)
