"""Helpers for writing scraped text to JSON safely."""

import re
from typing import Any


_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def strip_lone_surrogates(text: str) -> str:
    """Remove invalid UTF-16 surrogate code units from scraped browser text."""
    return _SURROGATE_RE.sub("", text)


def sanitize_for_json(value: Any) -> Any:
    """Recursively strip invalid surrogate code units before UTF-8 JSON writes."""
    if isinstance(value, str):
        return strip_lone_surrogates(value)
    if isinstance(value, list):
        return [sanitize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_json(v) for v in value)
    if isinstance(value, dict):
        return {
            sanitize_for_json(k) if isinstance(k, str) else k: sanitize_for_json(v)
            for k, v in value.items()
        }
    return value
