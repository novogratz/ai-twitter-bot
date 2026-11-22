"""Temporary authority to like one admitted, verified Reply parent."""
from contextlib import contextmanager
from contextvars import ContextVar

from ..core import settings
from ..x import x_urls


_SOURCE = ContextVar("admitted_reply_parent_like", default=None)


@contextmanager
def scope(url, text):
    """Only the Reply transaction enters this after its exact-source check."""
    token = _SOURCE.set((x_urls.canonical_status_url(url), text))
    try:
        yield
    finally:
        _SOURCE.reset(token)


def expected_source(url):
    if not settings.get("REPLY_REQUIRE_PARENT_LIKE") or settings.get("REPLY_REVIEW_ONLY"):
        return None
    current = _SOURCE.get()
    canonical = x_urls.canonical_status_url(url)
    return current[1] if current and canonical and current[0] == canonical and current[1] else None


def allowed(url):
    """A caller's quota flag cannot authorize a restricted ordinary like."""
    text = expected_source(url)
    if not text:
        return False
    from . import reply_intent
    return not reply_intent.source_refusal(url, text)


def active():
    """Check authority before a disabled write evaluates any row callback."""
    current = _SOURCE.get()
    return bool(current and allowed(current[0]))
