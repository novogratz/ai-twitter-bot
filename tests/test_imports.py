"""Every intra-project import resolves (issue #106).

Live jobs import helpers from legacy modules lazily, often inside
`try/except`: when the target module or name disappears, the suite stays
green while the live path silently returns False. This test reads the source
with `ast` (nothing is imported) and checks every import that points into the
project, at any depth: the module exists and defines each imported name.

Name resolution rules:
- A module defines the names bound at its top level, including inside
  top-level `if`/`try`/`with`/`for`: def, class, assignment, annotated
  assignment with a value, `import ... as`, `except ... as`, and names a
  function declares `global`. A bare annotation (`x: int`) binds nothing.
- `from pkg import name` also accepts a submodule `pkg/name.py`.
- A module that defines a module-level `__getattr__` or runs
  `from ... import *` has names the AST cannot enumerate: any name is
  accepted there, the module itself must still exist. Failing would block CI
  on imports that work at runtime.
- `from <project module> import *` is itself a failure: it hides which names
  the caller depends on, so this test could no longer pin them. The project
  has none; import names explicitly.

Out of scope: attribute access on an imported module (`m.helper`) and
dotted strings (`importlib.import_module("src.x")`, `monkeypatch.setattr`).
"""
import ast
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent


class Module(NamedTuple):
    file: Path          # the .py file, or the package's __init__.py
    package_dir: Path | None


def project_files(root):
    files = [root / "main.py", *sorted((root / "src").rglob("*.py"))]
    for folder in ("bin", "scripts", "tests"):
        files += sorted((root / folder).glob("*.py"))
    return [f for f in files if f.is_file()]


def _is_package(path):
    return (path / "__init__.py").is_file()


def locate(base, parts):
    """Find a dotted module under `base` the way the import system would."""
    here = base
    for part in parts[:-1]:
        here = here / part
        if not _is_package(here):
            return None
    last = here / parts[-1]
    if _is_package(last):
        return Module(last / "__init__.py", last)
    if last.with_suffix(".py").is_file():
        return Module(last.with_suffix(".py"), None)
    return None


class _TopLevelNames(ast.NodeVisitor):
    def __init__(self):
        self.names = set()
        self.open = False

    def _scope(self, node):
        self.names.add(node.name)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Global):
                self.names.update(sub.names)

    def visit_FunctionDef(self, node):
        self._scope(node)
        if node.name == "__getattr__":
            self.open = True

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._scope(node)

    def visit_Lambda(self, node):
        pass

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_Lambda

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_Import(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                self.open = True
            else:
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)


_names_cache = {}


def defined_names(path):
    """(names bound at top level, True if names cannot be enumerated)."""
    if path not in _names_cache:
        visitor = _TopLevelNames()
        visitor.visit(ast.parse(path.read_text(), filename=str(path)))
        _names_cache[path] = (visitor.names, visitor.open)
    return _names_cache[path]


def _package_parts(root, path):
    """Dotted package containing `path`, or None if run as a script."""
    if not _is_package(path.parent):
        return None
    # src/x.py and src/__init__.py both live in package `src`.
    return list(path.relative_to(root).parts[:-1])


def _search_bases(root, path):
    # A script outside any package runs with its own folder first on sys.path
    # (`python bin/x.py`, pytest's rootdir insertion for tests/); the scripts
    # and conftest.py put the project root there as well.
    if _is_package(path.parent):
        return [root]
    return list(dict.fromkeys([path.parent, root]))


def check_file(root, path):
    """Every unresolved intra-project import in `path`, as readable problems."""
    rel = path.relative_to(root)
    tree = ast.parse(path.read_text(), filename=str(path))
    package = _package_parts(root, path)
    bases = _search_bases(root, path)
    problems = []

    def report(node, what):
        problems.append(f"{rel}:{node.lineno}: `{ast.unparse(node)}`: {what}")

    def find(parts):
        """(module or None, base) for the first base that owns parts[0]."""
        for base in bases:
            if locate(base, parts[:1]):
                return locate(base, parts), base
        return None, None

    def check_bare_sibling(node, top):
        # `import config` inside src/ only works if src/ itself is on sys.path.
        if (package and top not in sys.stdlib_module_names
                and locate(path.parent, [top]) and not locate(root, [top])):
            report(node, f"`{top}` is a sibling in {path.parent.relative_to(root)}/ but "
                         f"not importable from the project root; use a package import")
            return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if check_bare_sibling(node, parts[0]):
                    continue
                if not find(parts[:1])[0]:
                    continue
                for i in range(2, len(parts) + 1):
                    if not find(parts[:i])[0]:
                        report(node, f"module `{'.'.join(parts[:i])}` does not exist")
                        break
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        if node.level:
            if package is None:
                report(node, "relative import in a file that is not inside a package")
                continue
            if node.level - 1 >= len(package):
                report(node, f"relative import goes beyond the top-level package "
                             f"`{'.'.join(package)}`")
                continue
            parts = package[: len(package) - (node.level - 1)]
            parts = parts + (node.module.split(".") if node.module else [])
            module, base = locate(root, parts), root
        else:
            parts = node.module.split(".")
            if check_bare_sibling(node, parts[0]):
                continue
            if not find(parts[:1])[0]:
                continue
            module, base = find(parts)

        dotted = ".".join(parts)
        if module is None:
            report(node, f"module `{dotted}` does not exist")
            continue
        names, open_ = defined_names(module.file)
        for alias in node.names:
            if alias.name == "*":
                report(node, f"star import from project module `{dotted}`; "
                             f"import the names explicitly")
            elif alias.name in names or open_:
                continue
            elif module.package_dir and locate(base, parts + [alias.name]):
                continue
            elif module.package_dir:
                report(node, f"`{alias.name}` is neither defined in "
                             f"{module.file.relative_to(root)} nor a module "
                             f"{(module.package_dir / alias.name).relative_to(root)}.py")
            else:
                report(node, f"`{alias.name}` is not defined in "
                             f"{module.file.relative_to(root)}")
    return problems


# --- the project -----------------------------------------------------------

def test_every_internal_import_resolves():
    files = project_files(ROOT)
    assert ROOT / "main.py" in files and len(files) > 50
    problems = [p for f in files for p in check_file(ROOT, f)]
    assert not problems, (
        "Unresolved intra-project imports (a function-local one fails only "
        "at runtime, often swallowed by try/except):\n  " + "\n  ".join(problems))


# --- the checker itself, on synthetic projects -----------------------------

def _project(tmp_path, files):
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path


def _problems(root, rel):
    return check_file(root, root / rel)


BASE = {
    "src/__init__.py": "",
    "src/helpers.py": (
        "import os as _os\n"
        "from typing import Any\n"
        "LIMIT = 3\n"
        "TYPED: int = 4\n"
        "BARE: int\n"
        "try:\n    import json\nexcept ImportError as err:\n    json = None\n"
        "def helper():\n    global LATE\n    LATE = 1\n"
        "class Box:\n    inner = 1\n"
    ),
    "src/sub/__init__.py": "",
    "src/sub/deep.py": "def dig():\n    pass\n",
}


def test_valid_imports_pass(tmp_path):
    root = _project(tmp_path, {**BASE, "src/user.py": (
        "from .helpers import helper, LIMIT, TYPED, Box, Any, _os, json, err, LATE\n"
        "from . import helpers, sub\n"
        "from src import helpers as h\n"
        "from src.sub import deep\n"
        "from src.sub.deep import dig\n"
        "import src.sub.deep\n"
        "import os, json\n"
        "from pytest import raises\n"
    ), "src/sub/nested.py": "from ..helpers import helper\nfrom .deep import dig\n"})
    assert _problems(root, "src/user.py") == []
    assert _problems(root, "src/sub/nested.py") == []


def test_function_local_import_of_missing_module_fails(tmp_path):
    root = _project(tmp_path, {**BASE, "src/job.py": (
        "def run():\n"
        "    try:\n"
        "        from src.gone_bot import helper\n"
        "    except Exception:\n"
        "        return False\n"
    )})
    assert _problems(root, "src/job.py") == [
        "src/job.py:3: `from src.gone_bot import helper`: module `src.gone_bot` does not exist"]


def test_missing_name_fails(tmp_path):
    root = _project(tmp_path, {**BASE, "main.py": (
        "def job():\n    from src.helpers import helper, renamed, BARE, inner\n"
    )})
    problems = _problems(root, "main.py")
    assert [p.rsplit(": ", 1)[1] for p in problems] == [
        "`renamed` is not defined in src/helpers.py",
        "`BARE` is not defined in src/helpers.py",
        "`inner` is not defined in src/helpers.py",
    ]
    assert all(p.startswith("main.py:2: ") for p in problems)


def test_missing_modules_in_every_form_fail(tmp_path):
    root = _project(tmp_path, {**BASE, "src/user.py": (
        "from . import nothing\n"
        "from .nothing import x\n"
        "import src.sub.nothing\n"
        "from src.sub import nothing\n"
        "from ...up import x\n"
    )})
    problems = _problems(root, "src/user.py")
    assert [p.split(": ", 1)[0] for p in problems] == [f"src/user.py:{n}" for n in range(1, 6)]
    assert "`nothing` is neither defined in src/__init__.py nor a module src/nothing.py" in problems[0]
    assert "module `src.nothing` does not exist" in problems[1]
    assert "module `src.sub.nothing` does not exist" in problems[2]
    assert "nor a module src/sub/nothing.py" in problems[3]
    assert "beyond the top-level package" in problems[4]


def test_scripts_resolve_siblings_and_root(tmp_path):
    root = _project(tmp_path, {**BASE,
                               "tests/conftest.py": "FIXTURE = 1\n",
                               "tests/test_x.py": "from conftest import FIXTURE, MISSING\n"
                                                  "from src.helpers import helper\n",
                               "bin/tool.py": "from . import x\n"})
    assert _problems(root, "tests/test_x.py") == [
        "tests/test_x.py:1: `from conftest import FIXTURE, MISSING`: "
        "`MISSING` is not defined in tests/conftest.py"]
    assert "not inside a package" in _problems(root, "bin/tool.py")[0]


def test_bare_sibling_import_inside_package_fails(tmp_path):
    root = _project(tmp_path, {**BASE, "src/user.py": "def f():\n    import helpers\n"})
    assert "not importable from the project root" in _problems(root, "src/user.py")[0]


def test_star_import_from_project_fails_and_open_modules_accept_any_name(tmp_path):
    root = _project(tmp_path, {**BASE,
                               "src/lazy.py": "def __getattr__(name):\n    return name\n",
                               "src/reexport.py": "from os.path import *\n",
                               "src/user.py": "from src.lazy import anything\n"
                                              "from src.reexport import join\n"
                                              "from src.helpers import *\n"})
    problems = _problems(root, "src/user.py")
    assert len(problems) == 1
    assert problems[0].startswith("src/user.py:3: ") and "star import" in problems[0]
