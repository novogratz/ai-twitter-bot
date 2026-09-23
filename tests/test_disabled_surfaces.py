"""No live module can reach a quote, repost or thread write (issue #107).

The 2026-09-20 policy sets these surfaces to zero. Caps at zero kept the old
branches silent; this test pins that the branches themselves are gone, so a
config change cannot bring them back. It reads the source with `ast`: every
module under `src/` that `main.py` reaches through imports, at any depth,
except `twitter_client`, which defines the chokepoints.

The legacy modules that drove those surfaces stay out of reach too, and no
other live module borrows a private helper from `reply_bot` (issue #108).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

DISABLED_WRITES = {
    "quote_tweet", "quote_tweet_with_gif",
    "retweet_post", "retweet_own_latest", "reboost_tweet",
    "post_thread", "reply_to_own_latest",
}


def _imported_src_modules(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            in_src = node.level == 1 or (not node.level and (node.module or "").split(".")[0] == "src")
            if not in_src:
                continue
            parts = (node.module or "").split(".")
            if not node.level:
                parts = parts[1:]
            if parts and parts[0]:
                found.add(parts[0])
            else:
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "src" and len(parts) > 1:
                    found.add(parts[1])
    return {name for name in found if (SRC / f"{name}.py").is_file()}


def live_modules():
    seen, todo = set(), list(_imported_src_modules(ROOT / "main.py"))
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo += _imported_src_modules(SRC / f"{name}.py")
    return seen


def _disabled_write_references(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Name) and node.id in DISABLED_WRITES:
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute) and node.attr in DISABLED_WRITES:
            yield node.lineno, node.attr
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in DISABLED_WRITES:
                    yield node.lineno, alias.name


def test_live_modules_never_reference_a_disabled_write():
    modules = live_modules()
    assert {"direct_reply", "feed_sweeper_bot", "notify_bot", "reply_bot"} <= modules
    problems = [f"src/{name}.py:{line}: {ref}"
                for name in sorted(modules - {"twitter_client"})
                for line, ref in _disabled_write_references(SRC / f"{name}.py")]
    assert not problems, (
        "A module reached from main.py names a quote, repost or thread write "
        "(2026-09-20 policy: zero):\n  " + "\n  ".join(problems))


def test_legacy_surface_modules_are_unreachable_from_main():
    reached = live_modules() & {"btc_blitz", "quote_tweet_bot", "retweet_bot"}
    assert not reached, f"main.py reaches legacy modules: {sorted(reached)}"


def _private_reply_bot_imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[-1] == "reply_bot"):
            for alias in node.names:
                if alias.name.startswith("_"):
                    yield node.lineno, alias.name


def test_live_modules_never_borrow_a_private_reply_bot_helper():
    problems = [f"src/{name}.py:{line}: {ref}"
                for name in sorted(live_modules() - {"reply_bot"})
                for line, ref in _private_reply_bot_imports(SRC / f"{name}.py")]
    assert not problems, (
        "A live module imports a private reply_bot helper; move it to the "
        "module that owns its concern:\n  " + "\n  ".join(problems))
