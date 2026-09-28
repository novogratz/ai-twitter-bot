"""Cross-cutting: no private primitive of `src.x.safari` leaves the browser
layer (#256). Jobs, scrapes and writes act on a page through a page session;
only `safari.py` and `page_session.py` reach `_safari_lock`, `_run_js`,
`_run_applescript` and the other private names, save the listed
exceptions. The guard follows imports of any form, `importlib` included,
aliases by assignment, `getattr`, `vars()` and `__dict__`; a name read on
safari or a module imported by a computed name fails it too."""
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
# A private name of safari, or "?": a name read dynamically on safari
# (`getattr` with a computed name, `vars(safari)`, `safari.__dict__`).
_PRIVATE_SAFARI = re.compile(r"(?:^|\.)safari\.(?:_(?!_)\w*|\?)")
# A module imported by a computed name: it may be safari.
DYNAMIC_IMPORT = "?"


def _module(rel):
    return rel.removesuffix(".py").replace("/", ".")


def _absolute(name, package, level):
    if level - 1 > len(package):
        return None
    base = package[:len(package) - (level - 1)] if level else []
    return ".".join(base + (name.split(".") if name else []))


def _constant(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def references(source, module):
    """(line, dotted name) of what `module` takes from other modules: each
    module or name it imports (relative at any level, absolute, or through
    `importlib.import_module` and `__import__`), each name bound to one of
    them by assignment, each attribute read on them, each `getattr` of one
    and each key of its `vars()` or `__dict__`. A name read dynamically
    ends in "?"; a module imported by a computed name is DYNAMIC_IMPORT."""
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
            target = _absolute(node.module, package, node.level)
            if target is None:
                continue
            for a in node.names:
                found.append((node.lineno, f"{target}.{a.name}"))
                bound[a.asname or a.name] = f"{target}.{a.name}"

    def imported(node):
        """The module an import call returns, "" when its name is computed,
        None when `node` is no import call."""
        if not isinstance(node, ast.Call) or not node.args:
            return None
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            name = _constant(node.args[0])
            return "" if name is None else name.split(".")[0]
        if dotted(node.func) == "importlib.import_module":
            name = _constant(node.args[0])
            if name is None:
                return ""
            level = len(name) - len(name.lstrip("."))
            return _absolute(name[level:], package, level) or ""
        return None

    def dotted(node):
        chain = []
        while isinstance(node, ast.Attribute):
            chain.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name) and node.id in bound:
            base = bound[node.id]
        else:
            base = imported(node)
            if not base:
                return None
        return ".".join([base, *reversed(chain)])

    def namespace(node):
        """The module whose namespace `vars(m)` or `m.__dict__` is."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "vars" and len(node.args) == 1:
            return dotted(node.args[0])
        if isinstance(node, ast.Attribute) and node.attr == "__dict__":
            return dotted(node.value)
        return None

    # Aliases by assignment, to a fixed point: `a = safari; b = a`. The
    # bound keeps a cycle such as `a = b.x; b = a.y` from growing forever.
    for _ in range(10):
        before = dict(bound)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            name = dotted(value)
            if name:
                for target in targets:
                    if isinstance(target, ast.Name):
                        bound[target.id] = name
        if bound == before:
            break

    keyed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and (owner := namespace(node.value)):
            key = _constant(node.slice)
            found.append((node.lineno, f"{owner}.{key if key is not None else '?'}"))
            keyed.add(id(node.value))
    for node in ast.walk(tree):
        name = None
        if (owner := namespace(node)) and id(node) not in keyed:
            name = f"{owner}.?"
        elif isinstance(node, ast.Attribute):
            name = dotted(node)
        elif isinstance(node, ast.Call) and imported(node) == "":
            name = DYNAMIC_IMPORT
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2):
            owner = dotted(node.args[0])
            key = _constant(node.args[1])
            name = owner and f"{owner}.{key if key is not None else '?'}"
        if name:
            found.append((node.lineno, name))
    return found


def private_safari_accesses(source, module):
    """Each place `module` reaches a private name of src.x.safari, or may
    reach one through a dynamic read or import, as "<line>: <dotted name>"."""
    return sorted({f"{lineno}: {name}" for lineno, name in references(source, module)
                   if name == DYNAMIC_IMPORT or _PRIVATE_SAFARI.search(name)})


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
    "_alias = safari\n_alias._paste_text('x')",
    "vars(safari)['_run_js']('1')",
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
    "from . import safari\n_alias = safari\n_alias._run_js",
    "from . import safari\na = safari\nb = a\nb._safari_lock",
    "from .. import x\nsf = x.safari\nsf._run_js",
    "from . import safari\nif (sf := safari):\n    sf._run_js",
    "from . import safari\nvars(safari)['_run_js']",
    "from . import safari\nsafari.__dict__['_run_js']",
    "from . import safari\nvars(safari).get(name)",
    "from . import safari\nsafari.__dict__[name]",
    "import importlib\nimportlib.import_module('src.x.safari')._run_js",
    "from importlib import import_module\nsf = import_module('..x.safari', __package__)\nsf._run_js",
    "import importlib\nimportlib.import_module(name)",
    "__import__('src.x.safari').x.safari._run_js",
    "from . import safari\ngetattr(safari, '_run' + '_js')",
    "from . import safari\ngetattr(safari, name)",
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
    "from . import safari\nsf = safari\nsf.KEYSTROKE_TIMEOUT_S",
    "from . import safari\nvars(safari)['KEYSTROKE_TIMEOUT_S']",
    "from ..core import config\ngetattr(config, name)",
    "import logging\ngetattr(logging, level.upper(), logging.INFO)",
    "vars(self)['_x']",
    "import importlib\nimportlib.import_module('src.x.scraper')._scrape_page",
])
def test_the_guard_lets_public_names_and_other_modules_through(source):
    assert private_safari_accesses(source, "src.x.example") == []
