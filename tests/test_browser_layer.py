"""Cross-cutting: no private primitive of `src.x.safari` leaves the browser
layer (#256). Jobs, scrapes and writes act on a page through a page session;
only `safari.py` and `page_session.py` reach `_safari_lock`, `_run_js`,
`_run_applescript` and the other private names, save the listed
exceptions."""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAYER = {"src/x/safari.py", "src/x/page_session.py"}
# safari_hygiene quits and relaunches Safari under the lock, past any page;
# bin/mass_unfollow.py drives the front tab by hand, bot stopped, without
# the lock (issue #250).
EXCEPTIONS = {"src/x/safari_hygiene.py", "bin/mass_unfollow.py"}
_PRIVATE_SAFARI = re.compile(r"(?:^|\.)safari\.(_(?!_)\w*)")


def _module(rel):
    return rel.removesuffix(".py").replace("/", ".")


def references(source, module):
    """(line, dotted name) of what `module` takes from other modules: each
    module or name it imports (relative at any level, or absolute), each
    attribute read on an imported name, and each `getattr` of one with a
    constant name."""
    package = module.split(".")[:-1]
    bound, found = {}, []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((node.lineno, a.name))
                if a.asname:
                    bound[a.asname] = a.name
                else:
                    head = a.name.split(".")[0]
                    bound[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(package):
                    continue
                base = package[:len(package) - (node.level - 1)]
                target = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                target = node.module or ""
            for a in node.names:
                found.append((node.lineno, f"{target}.{a.name}"))
                bound[a.asname or a.name] = f"{target}.{a.name}"

    def dotted(node):
        chain = []
        while isinstance(node, ast.Attribute):
            chain.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name) and node.id in bound:
            return ".".join([bound[node.id], *reversed(chain)])
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = dotted(node)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2
              and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            owner = dotted(node.args[0])
            name = owner and f"{owner}.{node.args[1].value}"
        else:
            continue
        if name:
            found.append((node.lineno, name))
    return found


def private_safari_accesses(source, module):
    """Each place `module` reaches a private name of src.x.safari, as
    "<line>: <dotted name>"."""
    return sorted({f"{lineno}: {name}" for lineno, name in references(source, module)
                   if _PRIVATE_SAFARI.search(name)})


def _production_files():
    return sorted([ROOT / "main.py", *(ROOT / "src").rglob("*.py"), *(ROOT / "bin").glob("*.py")])


def test_no_private_safari_primitive_leaves_the_browser_layer():
    problems = []
    for path in _production_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in LAYER or rel in EXCEPTIONS:
            continue
        problems += [f"{rel}:{p}" for p in private_safari_accesses(path.read_text(), _module(rel))]
    assert not problems, ("Private Safari primitives outside the browser layer; go through "
                          "page_session:\n  " + "\n  ".join(problems))


def test_each_listed_exception_still_needs_its_place():
    """An exception that no longer reaches a private primitive leaves the
    list, so the list names only what the layer really lets through."""
    for rel in sorted(EXCEPTIONS):
        path = ROOT / rel
        assert path.exists(), rel
        assert private_safari_accesses(path.read_text(), _module(rel)), rel


@pytest.mark.parametrize("line", [
    "safari._run_js('1')",
    "with safari._safari_lock:\n    pass",
    "getattr(safari, '_run_applescript')('x')",
])
def test_a_private_primitive_added_to_a_job_fails_the_guard(line):
    """The guard on a real module: twitter_client plus one private access."""
    rel = "src/x/twitter_client.py"
    source = (ROOT / rel).read_text()
    assert private_safari_accesses(source, _module(rel)) == []
    assert private_safari_accesses(f"{source}\n{line}\n", _module(rel))


@pytest.mark.parametrize("source", [
    "from . import safari\nsafari._run_js('1')",
    "from . import safari as sf\nsf._scroll_page()",
    "from .safari import _paste_text",
    "from .safari import _safari_lock as lock",
    "from ..x.safari import _run_applescript",
    "from ..x import safari\nsafari._safari_lock",
    "from .. import x\nx.safari._run_js",
    "from src.x.safari import _run_js",
    "from src.x import safari\nsafari._run_js",
    "import src.x.safari as sf\nsf._run_js",
    "import src.x.safari\nsrc.x.safari._run_js",
    "from . import safari_hygiene\nsafari_hygiene.safari._run_applescript",
    "from . import safari\ngetattr(safari, '_run_js')",
    "def run():\n    from . import safari\n    return safari._safari_lock",
])
def test_the_guard_catches_every_import_form(source):
    assert private_safari_accesses(source, "src.account.example_bot")


@pytest.mark.parametrize("source", [
    "from . import safari\nsafari.FIRST_TWEET_KEYS",
    "from ..x import safari\nsafari.KEYSTROKE_TIMEOUT_S",
    "from src.x import safari\nsafari.__name__",
    "from . import page_session\npage_session._active",
    "from . import safari_hygiene\nsafari_hygiene._last_run_ts()",
    "_run_js = 1\n_run_js",
])
def test_the_guard_lets_public_names_and_other_modules_through(source):
    assert private_safari_accesses(source, "src.x.example") == []
