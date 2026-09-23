"""Every intra-project import resolves (issue #106).

Live jobs import helpers from legacy modules lazily, often inside
`try/except`: when the target module or name disappears, the suite stays
green while the live path silently returns False. This test reads the source
with `ast` (nothing is imported) and checks every import that points into the
project, at any depth: the module exists and defines each imported name.
It reads `main.py` and every file under `src/`, `bin/`, `scripts/` and
`tests/`, subfolders included.

Name resolution rules:
- A module defines the names bound at its top level, including inside
  top-level `if`/`try`/`with`/`for`: def, class, assignment, annotated
  assignment with a value, `import ... as`, `except ... as`, and names a
  function declares `global`. A bare annotation (`x: int`) binds nothing.
- `from pkg import name` also accepts a submodule `pkg/name.py`.
- A module that defines a module-level `__getattr__` or runs
  `from ... import *` accepts any name (failing would block CI on imports
  that work at runtime); the module itself must still exist.
- `from <project module> import *` is itself a failure: it hides which names
  the caller depends on, so this test could no longer pin them. The project
  has none; import names explicitly.
- An absolute import that no search folder resolves is third-party, unless
  its first segment names a module under `src/`: such a bare import only
  works if that module's folder is on sys.path, so it fails.
- Every package folder has an `__init__.py`; namespace packages are not used.

Out of scope: attribute access on an imported module (`m.helper`) and
dotted strings (`importlib.import_module("src.x")`, `monkeypatch.setattr`).
"""
import ast
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
SCANNED_FOLDERS = ("src", "bin", "scripts", "tests")


class Module(NamedTuple):
    file: Path
    package_dir: Path | None


def _python_files(folder):
    for path in sorted(folder.rglob("*.py")):
        if not any(part == "__pycache__" or part.startswith(".")
                   for part in path.relative_to(folder).parts):
            yield path


def project_files(root):
    files = [root / "main.py"]
    for folder in SCANNED_FOLDERS:
        files += _python_files(root / folder)
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


def _folder_without_init(base, parts):
    """First folder along `parts` that exists but has no __init__.py, or None."""
    here = base
    for part in parts:
        here = here / part
        if not here.is_dir():
            return None
        if not _is_package(here):
            return here
    return None


class _TopLevelNames(ast.NodeVisitor):
    def __init__(self):
        self.names = set()
        self.names_unknowable = False

    def _bind_def_and_its_globals(self, node):
        self.names.add(node.name)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Global):
                self.names.update(sub.names)

    def visit_FunctionDef(self, node):
        self._bind_def_and_its_globals(node)
        if node.name == "__getattr__":
            self.names_unknowable = True

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._bind_def_and_its_globals(node)

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
                self.names_unknowable = True
            else:
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)


_names_cache = {}


def defined_names(path):
    """(names bound at top level, True if names cannot be enumerated)."""
    if path not in _names_cache:
        visitor = _TopLevelNames()
        visitor.visit(ast.parse(path.read_text(), filename=str(path)))
        _names_cache[path] = (visitor.names, visitor.names_unknowable)
    return _names_cache[path]


_src_modules_cache = {}


def src_modules(root):
    """Name of every module and package under src/ -> its path, for messages."""
    if root not in _src_modules_cache:
        found = {}
        for path in _python_files(root / "src"):
            if path.name == "__init__.py":
                if path.parent != root / "src":
                    found.setdefault(path.parent.name, f"{path.parent.relative_to(root)}/")
            else:
                found.setdefault(path.stem, str(path.relative_to(root)))
        _src_modules_cache[root] = found
    return _src_modules_cache[root]


def _package_of(root, path):
    """(dotted package of `path`, folder holding its top package), or (None, None)."""
    top = path.parent
    while top != root and _is_package(top):
        top = top.parent
    if top == path.parent:
        return None, None
    return list(path.parent.relative_to(top).parts), top


def check_file(root, path):
    """Every unresolved intra-project import in `path`, as readable problems."""
    rel = path.relative_to(root)
    tree = ast.parse(path.read_text(), filename=str(path))
    package, package_base = _package_of(root, path)
    # sys.path as pytest's prepend mode and `python bin/x.py` build it: the
    # folder above the top package, or a script's own folder; conftest.py and
    # the scripts add the project root.
    bases = list(dict.fromkeys([package_base or path.parent, root]))
    problems = []

    def report(node, what):
        problems.append(f"{rel}:{node.lineno}: `{ast.unparse(node)}`: {what}")

    def missing(base, parts):
        folder = _folder_without_init(base, parts)
        if folder:
            return (f"{folder.relative_to(root)}/ has no __init__.py: add one "
                    f"(namespace packages are not used here)")
        return f"module `{'.'.join(parts)}` does not exist"

    def project_base(node, top):
        """Search folder owning `top`; None for third-party or a reported bare import."""
        for base in bases:
            if locate(base, [top]):
                return base
        if top in sys.stdlib_module_names:
            return None
        if package and locate(path.parent, [top]):
            report(node, f"`{top}` is a sibling in {path.parent.relative_to(root)}/ but "
                         f"not importable from the project root; use a package import")
        elif top in src_modules(root):
            report(node, f"`{top}` is a project module ({src_modules(root)[top]}); "
                         f"import it through the package")
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                base = project_base(node, parts[0])
                if base is None:
                    continue
                for i in range(2, len(parts) + 1):
                    if not locate(base, parts[:i]):
                        report(node, missing(base, parts[:i]))
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
            base = package_base
        else:
            parts = node.module.split(".")
            base = project_base(node, parts[0])
            if base is None:
                continue

        module = locate(base, parts)
        if module is None:
            report(node, missing(base, parts))
            continue
        dotted = ".".join(parts)
        names, names_unknowable = defined_names(module.file)
        for alias in node.names:
            if alias.name == "*":
                report(node, f"star import from project module `{dotted}`; "
                             f"import the names explicitly")
            elif alias.name in names or names_unknowable:
                continue
            elif module.package_dir and locate(base, parts + [alias.name]):
                continue
            elif module.package_dir and _folder_without_init(base, parts + [alias.name]):
                report(node, missing(base, parts + [alias.name]))
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
    # A renamed or emptied folder would otherwise leave the check silently.
    assert {f.relative_to(ROOT).parts[0] for f in files} == {"main.py", *SCANNED_FOLDERS}
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


SYNTHETIC_PROJECT = {
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
    root = _project(tmp_path, {**SYNTHETIC_PROJECT, "src/user.py": (
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
    root = _project(tmp_path, {**SYNTHETIC_PROJECT, "src/job.py": (
        "def run():\n"
        "    try:\n"
        "        from src.gone_bot import helper\n"
        "    except Exception:\n"
        "        return False\n"
    )})
    assert _problems(root, "src/job.py") == [
        "src/job.py:3: `from src.gone_bot import helper`: module `src.gone_bot` does not exist"]


def test_missing_name_fails(tmp_path):
    root = _project(tmp_path, {**SYNTHETIC_PROJECT, "main.py": (
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
    root = _project(tmp_path, {**SYNTHETIC_PROJECT, "src/user.py": (
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
    root = _project(tmp_path, {**SYNTHETIC_PROJECT,
                               "tests/conftest.py": "FIXTURE = 1\n",
                               "tests/test_x.py": "from conftest import FIXTURE, MISSING\n"
                                                  "from src.helpers import helper\n",
                               "bin/tool.py": "from . import x\n"})
    assert _problems(root, "tests/test_x.py") == [
        "tests/test_x.py:1: `from conftest import FIXTURE, MISSING`: "
        "`MISSING` is not defined in tests/conftest.py"]
    assert "not inside a package" in _problems(root, "bin/tool.py")[0]


def test_subfolders_are_scanned_and_resolved(tmp_path):
    root = _project(tmp_path, {**SYNTHETIC_PROJECT,
                               "tests/sub/test_a.py": "from src.nope import x\n"
                                                      "from src.helpers import helper\n",
                               "tests/pkg/__init__.py": "",
                               "tests/pkg/helper.py": "VALUE = 1\n",
                               "tests/pkg/test_b.py": "from .helper import VALUE\n"
                                                      "from pkg.helper import VALUE\n"
                                                      "from .helper import GONE\n",
                               "tests/__pycache__/stale.py": "from src.nope import x\n",
                               "tests/.hidden/test_h.py": "from src.nope import x\n"})
    scanned = [f.relative_to(root).as_posix() for f in project_files(root)]
    assert "tests/sub/test_a.py" in scanned and "tests/pkg/test_b.py" in scanned
    assert not any("__pycache__" in f or ".hidden" in f for f in scanned)
    assert _problems(root, "tests/sub/test_a.py") == [
        "tests/sub/test_a.py:1: `from src.nope import x`: module `src.nope` does not exist"]
    assert _problems(root, "tests/pkg/test_b.py") == [
        "tests/pkg/test_b.py:3: `from .helper import GONE`: "
        "`GONE` is not defined in tests/pkg/helper.py"]


def test_bare_sibling_import_inside_package_fails(tmp_path):
    root = _project(tmp_path, {**SYNTHETIC_PROJECT, "src/user.py": "def f():\n    import helpers\n"})
    assert "not importable from the project root" in _problems(root, "src/user.py")[0]


def test_bare_import_of_a_project_module_elsewhere_in_src_fails(tmp_path):
    root = _project(tmp_path, {**SYNTHETIC_PROJECT,
                               "src/x/__init__.py": "",
                               "src/x/x_urls.py": "def author(url):\n    pass\n",
                               "src/editorial/__init__.py": "",
                               "src/editorial/bot.py": "from x_urls import author\n"
                                                       "import sub\n"
                                                       "import requests, json\n"
                                                       "from yaml import safe_load\n",
                               "bin/tool.py": "from x_urls import author\n"})
    assert _problems(root, "src/editorial/bot.py") == [
        "src/editorial/bot.py:1: `from x_urls import author`: `x_urls` is a project "
        "module (src/x/x_urls.py); import it through the package",
        "src/editorial/bot.py:2: `import sub`: `sub` is a project module (src/sub/); "
        "import it through the package"]
    assert "`x_urls` is a project module" in _problems(root, "bin/tool.py")[0]


def test_package_folder_without_init_is_named(tmp_path):
    root = _project(tmp_path, {**SYNTHETIC_PROJECT,
                               "src/core/cfg.py": "X = 1\n",
                               "src/user.py": "import src.core.cfg\n"
                                              "from src.core.cfg import X\n"
                                              "from .core import cfg\n"
                                              "from src import core\n"})
    problems = _problems(root, "src/user.py")
    assert len(problems) == 4
    assert all(p.endswith(": src/core/ has no __init__.py: add one "
                          "(namespace packages are not used here)") for p in problems)


def test_star_import_from_project_fails_and_open_modules_accept_any_name(tmp_path):
    root = _project(tmp_path, {**SYNTHETIC_PROJECT,
                               "src/lazy.py": "def __getattr__(name):\n    return name\n",
                               "src/reexport.py": "from os.path import *\n",
                               "src/user.py": "from src.lazy import anything\n"
                                              "from src.reexport import join\n"
                                              "from src.helpers import *\n"})
    problems = _problems(root, "src/user.py")
    assert len(problems) == 1
    assert problems[0].startswith("src/user.py:3: ") and "star import" in problems[0]
