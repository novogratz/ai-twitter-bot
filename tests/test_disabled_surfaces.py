"""No live module can reach a quote, repost or thread write (issues #107, #111).

The 2026-09-20 policy sets these surfaces to zero. Caps at zero kept the old
branches silent; this test pins that the branches themselves are gone, so a
config change cannot bring them back. It reads the source with `ast`: every
module under `src/` that `main.py` reaches through imports, at any depth,
`twitter_client` included. `twitter_client` no longer defines these write
functions at all (issue #111): bringing one back takes new code.

No live module borrows a private helper from `reply_bot` (issue #108), and
every module under `src/` is reached from `main.py`, so legacy code cannot
pile up again (issue #110). The walk follows function-local imports too:
`reply_bot` is reached only through the `ENABLE_REPLY_SEARCH` branch. It
enters the packages under `src/` (`core`, `x`…): modules are named by their
dotted path below `src`, such as `x.twitter_client`.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

DISABLED_WRITES = {
    "quote_tweet", "quote_tweet_with_gif", "post_tweet_with_gif",
    "retweet_post", "retweet_own_latest", "reboost_tweet",
    "post_thread", "reply_to_own_latest", "reply_to_reply",
}


def _file(name):
    """Source file of the module or package `name`, dotted below `src`."""
    path = SRC.joinpath(*name.split("."))
    return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")


def src_module_names():
    names = set()
    for path in SRC.rglob("*.py"):
        parts = path.relative_to(SRC).with_suffix("").parts
        if "__pycache__" in parts:
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            names.add(".".join(parts))
    return names


def _imported_src_modules(path):
    package = list(path.relative_to(SRC).parts[:-1]) if SRC in path.parents else None
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if package is None:
                    continue
                parts = package[: len(package) - (node.level - 1)]
                parts = parts + (node.module.split(".") if node.module else [])
            elif (node.module or "").split(".")[0] == "src":
                parts = node.module.split(".")[1:]
            else:
                continue
            found.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
            found.update(".".join(parts + [alias.name]) for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "src":
                    found.update(".".join(parts[1:i]) for i in range(2, len(parts) + 1))
    return {name for name in found if name and _file(name).is_file()}


def live_modules():
    seen, todo = set(), list(_imported_src_modules(ROOT / "main.py"))
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo += _imported_src_modules(_file(name))
    return seen


def _disabled_write_references(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in DISABLED_WRITES:
            yield node.lineno, node.name
        elif isinstance(node, ast.Name) and node.id in DISABLED_WRITES:
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute) and node.attr in DISABLED_WRITES:
            yield node.lineno, node.attr
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in DISABLED_WRITES:
                    yield node.lineno, alias.name


def test_live_modules_never_reference_a_disabled_write():
    modules = live_modules()
    assert {"replies.direct_reply", "replies.feed_sweeper_bot", "replies.notify_bot",
            "replies.reply_bot"} <= modules
    assert {"x.twitter_client", "x.safari_hygiene", "core.llm_client"} <= modules
    problems = [f"{_file(name).relative_to(ROOT)}:{line}: {ref}"
                for name in sorted(modules)
                for line, ref in _disabled_write_references(_file(name))]
    assert not problems, (
        "A module reached from main.py defines or names a quote, repost, "
        "thread or GIF write (2026-09-20 policy: zero):\n  " + "\n  ".join(problems))


def test_twitter_client_exposes_no_disabled_write():
    from src.x import twitter_client

    present = sorted(name for name in DISABLED_WRITES if hasattr(twitter_client, name))
    assert not present, f"twitter_client still exposes {present}"


def test_every_src_module_is_reached_from_main():
    modules = src_module_names()
    assert {"core", "core.config", "x", "x.twitter_client", "replies", "replies.direct_reply",
            "account", "account.engage_bot"} <= modules
    unreached = sorted(modules - live_modules())
    assert not unreached, (
        "Modules under src/ that no import chain from main.py reaches; wire "
        "them into a job or delete them:\n  " + "\n  ".join(unreached))


# Jobs sit on top: no package below them imports them, and account jobs
# never import reply jobs (#116). A shared helper goes down to core.
_MAY_IMPORT = {"replies": {"replies", "account"}, "account": {"account"}}


def test_packages_never_import_the_job_packages_above_them():
    problems = []
    for name in sorted(src_module_names()):
        package = name.split(".")[0]
        for target in sorted(_imported_src_modules(_file(name))):
            above = target.split(".")[0]
            if above in _MAY_IMPORT and above not in _MAY_IMPORT.get(package, set()):
                problems.append(f"{_file(name).relative_to(ROOT)} imports {target}")
    assert not problems, (
        "A lower package imports a job package; move the shared code down to "
        "src/core:\n  " + "\n  ".join(problems))


def _private_reply_bot_imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[-1] == "reply_bot"):
            for alias in node.names:
                if alias.name.startswith("_"):
                    yield node.lineno, alias.name


def test_live_modules_never_borrow_a_private_reply_bot_helper():
    problems = [f"{_file(name).relative_to(ROOT)}:{line}: {ref}"
                for name in sorted(live_modules() - {"replies.reply_bot"})
                for line, ref in _private_reply_bot_imports(_file(name))]
    assert not problems, (
        "A live module imports a private reply_bot helper; move it to the "
        "module that owns its concern:\n  " + "\n  ".join(problems))
