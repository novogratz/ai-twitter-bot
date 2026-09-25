"""src/guards/respect_list: the prompt block and the text check the write
chokepoints apply. conftest points respect_list.json at tmp_path."""
from src.guards import respect_list


def test_the_prompt_block_names_every_respected_account():
    for n in range(40):
        respect_list.add(f"respected{n}")
    handles = respect_list.load()
    assert len(handles) > 30
    block = respect_list.render_block()
    assert all(f"@{h}" in block for h in handles)


def test_the_default_prompt_block_names_every_default_account():
    block = respect_list.render_block(defaults=True)
    assert all(f"@{h}" in block for h in respect_list._DEFAULTS)


def test_a_neutral_text_passes_unchanged():
    text = "Inference is getting cheaper faster than training."
    assert respect_list.scrub_text_or_skip(text) == (text, "")
