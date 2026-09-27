"""bin/show_prompts.py prints the prompts the jobs assemble, and calls no
model: the `providers` fixture records any call that reaches a provider."""
import importlib.util
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "show_prompts.py"


def _script():
    spec = importlib.util.spec_from_file_location("show_prompts_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_lists_each_prompt_with_its_size_without_a_model_call(providers, capsys):
    assert _script().main([]) == 0
    out = capsys.readouterr().out
    for label in ("DIRECT_REPLY", "DEBATE", "REPLYBACK", "EDITORIAL_DRAFT"):
        assert re.search(rf"^{label}: \d+ characters$", out, re.MULTILINE), label
    assert re.search(r"^\S*VIP\S*: \d+ characters$", out, re.MULTILINE), "the Relations' prompts"
    assert "THEIR MESSAGE" not in out
    assert providers.calls == []


def test_writes_no_log_line(providers, caplog):
    """bot.log on the live machine is the bot's own record: a declined
    sample Draft logged there once read as "malformed JSON"."""
    caplog.set_level("INFO", logger="bot")
    _script().main([])
    assert [r.getMessage() for r in caplog.records if r.name == "bot"] == []


def test_prints_the_prompt_a_label_names(providers, capsys):
    assert _script().main(["DEBATE"]) == 0
    out = capsys.readouterr().out
    assert "THEIR MESSAGE (from @" in out
    assert "Your post:" not in out  # replyback's prompt stays unprinted
    assert providers.calls == []


def test_an_unknown_label_fails(providers, capsys):
    assert _script().main(["NO_SUCH_PROMPT"]) == 1
    assert "NO_SUCH_PROMPT" in capsys.readouterr().err
