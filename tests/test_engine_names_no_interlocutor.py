"""Cross-cutting: the engine names no interlocutor (#203).

The instructions for particular accounts are the Account's Relations
(accounts/<name>/account.toml and relations/): no string of src/ may name
Graphseo or TheBTCTherapist, docstrings and comments aside, except the
handle lists below. Each one is a value, never a prompt, and has its ticket.
"""
import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
NAMED = re.compile(r"graphseo|thebtctherapist", re.I)

STILL_IN_THE_ENGINE = {
    # Setting defaults: a handle list .env can change.
    "core/settings.py": {"Graphseo", "TheBTCTherapist"},
    # The respect list's seed, the Operator's data moved by #206.
    "guards/respect_list.py": {"graphseo"},
}


def _strings(tree):
    """Every string constant of a module but its docstrings."""
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def test_no_engine_string_names_an_interlocutor():
    named = []
    for path in sorted(SRC.rglob("*.py")):
        module = path.relative_to(SRC).as_posix()
        allowed = STILL_IN_THE_ENGINE.get(module, set())
        named += [f"{module}:{node.lineno}: {node.value[:80]!r}" for node in _strings(ast.parse(path.read_text()))
                  if NAMED.search(node.value) and node.value not in allowed]
    assert not named, ("An interlocutor named in the engine; its instructions go in the Account's "
                       "Relations (accounts/<name>/account.toml):\n  " + "\n  ".join(named))


def test_the_vip_prompts_come_from_the_account():
    from src.core import account
    from src.replies import direct_reply

    relations = account.current().relations
    templates = {direct_reply._vip_call(handle).template for handle in ("Graphseo", "TheBTCTherapist", "vision_ia")}
    assert templates == {relations.get("Graphseo").prompt, relations.bestie, relations.buddy}
