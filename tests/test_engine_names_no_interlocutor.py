"""Cross-cutting: the engine names no interlocutor (#203).

The instructions for particular accounts are the Account's Relations
(accounts/<name>/account.toml and relations/): no string of src/ may name
Graphseo or TheBTCTherapist, docstrings and comments aside, except in the
places below. Each one is a value, never a prompt, and has its ticket.
"""
import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
NAMED = re.compile(r"graphseo|thebtctherapist", re.I)

# One place per entry, and its ticket: the default of the setting a
# `_declare(name, …)` declares, or one key of a module-level dict.
DECLARE_DEFAULTS = {
    # A handle list .env can change; #208 moves it to the Account.
    ("core/settings.py", "FR_FORCED_REPLY_HANDLES"): "#208",
}
DICT_KEYS = {}


def _strings(tree):
    """Every string constant of a module but its docstrings."""
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def _allowed(module, tree):
    """The ids of the exempt string nodes of `module`, and the entries found."""
    allowed, found = set(), set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_declare"
                and len(node.args) > 2 and isinstance(node.args[0], ast.Constant)
                and (module, node.args[0].value) in DECLARE_DEFAULTS):
            allowed.add(id(node.args[2]))
            found.add((module, node.args[0].value))
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            for key in node.value.keys:
                entry = (module, node.targets[0].id, getattr(key, "value", None))
                if isinstance(key, ast.Constant) and entry in DICT_KEYS:
                    allowed.add(id(key))
                    found.add(entry)
    return allowed, found


def test_no_engine_string_names_an_interlocutor():
    named, found = [], set()
    for path in sorted(SRC.rglob("*.py")):
        module = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text())
        allowed, in_module = _allowed(module, tree)
        found |= in_module
        named += [f"{module}:{node.lineno}: {node.value[:80]!r}" for node in _strings(tree)
                  if NAMED.search(node.value) and id(node) not in allowed]
    assert not named, ("An interlocutor named in the engine; its instructions go in the Account's "
                       "Relations (accounts/<name>/account.toml):\n  " + "\n  ".join(named))
    assert found == set(DECLARE_DEFAULTS) | set(DICT_KEYS), "an exemption names a place gone: drop it"


def test_the_vip_prompts_come_from_the_account():
    from src.core import account
    from src.replies import direct_reply

    relations = account.current().relations
    templates = {direct_reply._vip_call(handle).template for handle in ("Graphseo", "TheBTCTherapist", "vision_ia")}
    assert templates == {relations.get("Graphseo").prompt, relations.get("TheBTCTherapist").prompt,
                         relations.default}
