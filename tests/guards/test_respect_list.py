"""src/guards/respect_list: the prompt block and the text check the write
chokepoints apply. conftest points the Account folder at a copy."""
import pytest

from src.guards import respect_list


def test_the_prompt_block_names_every_respected_account(respected):
    respected(*(f"respected{n}" for n in range(40)))
    handles = respect_list.load()
    assert len(handles) > 30
    block = respect_list.render_block()
    assert all(f"@{h}" in block for h in handles)


def test_the_prompt_block_is_in_english(monkeypatch):
    monkeypatch.setattr(respect_list, "load", lambda: {"kindperson"})
    block = respect_list.render_block()
    assert "RESPECT LIST — accounts you must NEVER criticize BY NAME" in block
    assert "criticize the IDEA,\nnever the person. When in doubt -> SKIP." in block
    assert block.endswith("Current list: @kindperson.\n")


def test_a_neutral_text_passes_unchanged():
    text = "Inference is getting cheaper faster than training."
    assert respect_list.scrub_text_or_skip(text) == (text, "")


@pytest.mark.parametrize("text", [
    "01net vient de publier le benchmark, mais on ne sait pas encore s'il tient.",
    "01net vient de publier le benchmark. L'argument du prix, lui, est ridicule.",
])
def test_a_respected_name_in_a_neutral_sentence_passes(text):
    assert respect_list.scrub_text_or_skip(text) == (text, "")


def test_a_respected_name_mocked_in_its_sentence_is_refused():
    text = "Le benchmark tient. Mais 01net publie encore un comparatif ridicule."
    cleaned, why = respect_list.scrub_text_or_skip(text)
    assert cleaned is None and "01net" in why


def test_only_the_addressee_handle_passes():
    """An Original has no addressee; a Reply's addressee is never mocked."""
    text = "@graphseo le support tient tant que les volumes suivent."
    assert respect_list.scrub_text_or_skip(text, addressee="GraphSEO") == (text, "")
    assert respect_list.scrub_text_or_skip(text)[0] is None
    assert respect_list.scrub_text_or_skip(text, addressee="01net")[0] is None
    mocked = "@graphseo ton analyse est ridicule."
    assert respect_list.scrub_text_or_skip(mocked, addressee="graphseo")[0] is None
