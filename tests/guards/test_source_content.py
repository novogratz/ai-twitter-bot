import pytest

from src.guards import content_guard


@pytest.mark.parametrize("text,language", [("So beautiful", "en"), ("Yes", "qst"), ("Wow", "qst"), ("🙂", "")])
def test_watched_source_reactions_are_not_our_generated_replies(text, language):
    assert content_guard.validate(text, kind="source", source_language=language)[0]
    assert not content_guard.validate(text, kind="reply")[0]


@pytest.mark.parametrize("text", ["Bonjour", "Merci beaucoup", "C'est vraiment très beau", "Prachtig uitzicht"])
def test_source_language_evidence_does_not_let_french_or_unknown_prose_through(text):
    assert not content_guard.validate(text, kind="source")[0]


def test_french_source_is_refused_even_with_an_incorrect_english_tag():
    assert not content_guard.validate("Bonjour", kind="source", source_language="en")[0]


@pytest.mark.parametrize("text", ["Kill civilians.", "Bitcoin will hit $200000 tomorrow."])
def test_source_kind_keeps_substantive_content_restrictions(text):
    assert not content_guard.validate(text, kind="source", source_language="en")[0]
