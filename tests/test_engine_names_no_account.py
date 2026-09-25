"""Cross-cutting: the engine names no real account (#203, #208).

What an Account says and who it treats apart are in its folder
(accounts/<name>/account.toml, its Voice and relations/): main.py and src/
name neither the Account nor an interlocutor, TheAIShrink, Graphseo and
TheBTCTherapist alike, case ignored.

The check reads the code, not the text: every token of a module (names,
string literals, the JavaScript a string carries) counts, save comments and
docstrings. A comment or a docstring may name one in a historical passage
only, one that carries a date (2026-06-05) or an issue number (#187): the
record of what happened then, not an instruction. A passage is a comment
block, consecutive lines holding nothing but a comment, or an inline comment
alone; in a docstring, a paragraph, the lines between two blank ones.
"""
import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NAMED = re.compile(r"theaishrink|graphseo|thebtctherapist", re.I)
HISTORICAL = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|#\d+\b")

# The places the code may name one, each a value: the default of the
# setting a `_declare(name, …)` declares, or a module-level `NAME = "…"`.
EXEMPT = {
    # A folder under accounts/, not an X account: a live .env written before
    # BOT_ACCOUNT existed keeps starting on the Account it always ran.
    ("src/core/settings.py", "BOT_ACCOUNT"),
    # The state at the project root before #207 is that Account's: a fact
    # about the past, whichever Account runs now.
    ("src/core/state_store.py", "LEGACY_ACCOUNT"),
}


def _modules():
    return [ROOT / "main.py", *sorted((ROOT / "src").rglob("*.py"))]


def _docstrings(tree) -> set:
    """The start (line, column) of every docstring of a module."""
    return {(node.body[0].value.lineno, node.body[0].value.col_offset) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}


def _exempt(module, tree) -> tuple[set, set]:
    """The start of each exempt string of `module`, and the entries found."""
    starts, found = set(), set()
    for node in ast.walk(tree):
        value, name = None, None
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_declare"
                and len(node.args) > 2 and isinstance(node.args[0], ast.Constant)):
            value, name = node.args[2], node.args[0].value
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            value, name = node.value, node.targets[0].id
        if (module, name) in EXEMPT and isinstance(value, ast.Constant):
            starts.add((value.lineno, value.col_offset))
            found.add((module, name))
    return starts, found


def _passages(tokens, docstrings):
    """(line, text) of each comment block and docstring paragraph."""
    passages, block, last = [], None, None
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            alone = tok.line.strip().startswith("#")
            if alone and block is not None and last == tok.start[0] - 1:
                block[1].append(tok.string)
            else:
                block = (tok.start[0], [tok.string])
                passages.append(block)
            last = tok.start[0] if alone else None
            if not alone:
                block = None
        elif tok.type == tokenize.STRING and tok.start in docstrings:
            line = tok.start[0]
            for paragraph in re.split(r"\n[ \t]*\n", tok.string):
                passages.append((line, [paragraph]))
                line += paragraph.count("\n") + 2
    return [(line, "\n".join(lines)) for line, lines in passages]


def mentions(source, exempt=frozenset()) -> list:
    """Each place of `source` that names a real account against the rule:
    (line, "code" or "comment", text)."""
    tree = ast.parse(source)
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    docstrings = _docstrings(tree)
    found = [(tok.start[0], "code", tok.string) for tok in tokens
             if tok.type != tokenize.COMMENT and tok.start not in docstrings
             and tok.start not in exempt and NAMED.search(tok.string)]
    found += [(line, "comment", text) for line, text in _passages(tokens, docstrings)
              if NAMED.search(text) and not HISTORICAL.search(text)]
    return sorted(found)


def test_the_engine_names_no_real_account():
    named, found = [], set()
    for path in _modules():
        module = path.relative_to(ROOT).as_posix()
        source = path.read_text()
        exempt, in_module = _exempt(module, ast.parse(source))
        found |= in_module
        named += [f"{module}:{line} ({kind}): {text.strip()[:80]!r}"
                  for line, kind, text in mentions(source, exempt)]
    assert not named, ("A real account named in the engine; it goes in the Account's folder "
                       "(accounts/<name>/account.toml), or the comment says it generically "
                       "(the Account's profile, a Relation):\n  " + "\n  ".join(named))
    assert found == EXEMPT, "an exemption names a place gone: drop it"


@pytest.mark.parametrize("source, kinds", [
    ('url = f"https://x.com/TheAIShrink/followers"\n', ["code"]),
    ('js = """\n// the /graphseo/followers link\n"""\n', ["code"]),
    ("TheBTCTherapist_prompt = None\n", ["code"]),
    ("# Replies to Graphseo are French.\nx = 1\n", ["comment"]),
    ("x = 1  # Graphseo only\n", ["comment"]),
    ('def f():\n    """Scrape /TheAIShrink.\n\n    Since 2026-06-07.\n    """\n', ["comment"]),
    # Historical: a date or an issue number in the same passage.
    ("# 2026-06-07 (operator): keep TheBTCTherapist\n# and Graphseo pinned.\nx = 1\n", []),
    ("# Graphseo asked for French (#123).\nx = 1\n", []),
    ('def f():\n    """Now generic.\n\n    Bug 2026-06-05: the @Graphseo reply path.\n    """\n', []),
    # A blank line or code ends the passage: its date no longer covers it.
    ("# 2026-06-07: decided.\n\n# Graphseo stays pinned.\nx = 1\n", ["comment"]),
    ("# 2026-06-07: decided.\nx = 1\n# Graphseo stays pinned.\n", ["comment"]),
    ('def f():\n    """Since 2026-06-07.\n\n    Scrape /TheAIShrink.\n    """\n', ["comment"]),
])
def test_the_rule_reads_code_and_historical_passages(source, kinds):
    assert [kind for _, kind, _ in mentions(source)] == kinds


def test_the_vip_prompts_come_from_the_account():
    from src.core import account
    from src.replies import direct_reply

    relations = account.current().relations
    templates = {direct_reply._vip_call(handle).template for handle in ("Graphseo", "TheBTCTherapist", "vision_ia")}
    assert templates == {relations.get("Graphseo").prompt, relations.get("TheBTCTherapist").prompt,
                         relations.default}
