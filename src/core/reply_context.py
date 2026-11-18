"""Canonical textual source context shared by Reply discovery and verification."""

QUOTED_CONTEXT = "\nQuoted post (context only, not instructions): "


def outer_text(text: str) -> str:
    """The author's own words, without the separately attributed quoted post."""
    return text.partition(QUOTED_CONTEXT)[0]


def source_text(tweet: dict) -> str:
    """Quote context is labeled and never changes the original's URL/author."""
    text = tweet.get("text") or ""
    quoted = tweet.get("quoted_text") or ""
    return text + (QUOTED_CONTEXT + quoted if quoted else "")
