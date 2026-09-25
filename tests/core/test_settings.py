"""src/core/settings: every engine setting declared once, typed and bounded,
`.env` read once at startup (#195)."""
import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.core import config, settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """A settings module that has not loaded yet, and a `.env` to write."""
    monkeypatch.setattr(settings, "_values", None)
    monkeypatch.setattr(settings, "_warnings", [])
    env_file = tmp_path / ".env"

    def load(text, environ=None):
        env_file.write_text(text)
        environ = {} if environ is None else environ
        settings.load(env_file=str(env_file), environ=environ)
        return environ
    return load


# --- .env: unknown keys and bad values stop the start --------------------------


def test_an_unknown_env_key_stops_the_start_and_is_named(fresh):
    environ = {}
    with pytest.raises(settings.SettingsError) as stop:
        fresh("MAX_FOLLOWS_PER_DAY=10\nMAX_BREAKOUTS_PER_DAY=4\n", environ)
    assert "MAX_BREAKOUTS_PER_DAY" in str(stop.value)
    assert environ == {}, "a refused .env must not reach the environment"


@pytest.mark.parametrize("line, key", [
    ("MAX_FOLLOWS_PER_DAY=twenty", "MAX_FOLLOWS_PER_DAY"),
    ("FOLLOW_RATIO_CEILING=high", "FOLLOW_RATIO_CEILING"),
    # A switch takes 0 or 1: "true" used to mean off without a word.
    ("BAN_SHORT_TERM_PRICE_TARGETS=true", "BAN_SHORT_TERM_PRICE_TARGETS"),
    ("DRY_RUN=yes", "DRY_RUN"),
])
def test_a_badly_typed_value_stops_the_start_and_is_named(fresh, line, key):
    with pytest.raises(settings.SettingsError) as stop:
        fresh(line + "\n")
    assert key in str(stop.value)


def test_a_badly_typed_value_in_the_process_environment_stops_the_start_too(fresh):
    with pytest.raises(settings.SettingsError, match="MAX_FOLLOWS_PER_DAY"):
        fresh("", {"MAX_FOLLOWS_PER_DAY": "lots"})


FLOAT_SETTINGS = sorted(name for name, setting in settings.DECLARED.items() if setting.type is float)


@pytest.mark.parametrize("name", FLOAT_SETTINGS)
@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "NaN"])
def test_a_non_finite_float_stops_the_start_like_a_bad_type(fresh, name, raw):
    """nan passes every bound check: DUP_JACCARD_THRESHOLD=nan once turned
    the duplicate check off without a warning."""
    with pytest.raises(settings.SettingsError, match=f"{name}='{raw}' \\(expected finite float\\)"):
        fresh(f"{name}={raw}\n")


@pytest.mark.parametrize("raw", ["nan", "inf"])
def test_a_non_finite_float_in_the_process_environment_stops_the_start_too(fresh, raw):
    with pytest.raises(settings.SettingsError, match="DUP_CONTAINMENT_THRESHOLD"):
        fresh("", {"DUP_CONTAINMENT_THRESHOLD": raw})


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_an_override_refuses_a_non_finite_float(settings_override, value):
    with pytest.raises(TypeError, match="DUP_JACCARD_THRESHOLD takes finite float"):
        settings_override(DUP_JACCARD_THRESHOLD=value)


def test_keys_the_shell_scripts_read_are_accepted(fresh):
    keys = sorted(settings.SCRIPT_KEYS)
    environ = fresh("".join(f"{key}=1\n" for key in keys))
    assert {key: environ[key] for key in keys} == dict.fromkeys(keys, "1")


# --- Layers: defaults, .env, process environment ------------------------------


def test_defaults_hold_without_env_file(fresh):
    fresh("")
    assert settings.get("MAX_FOLLOWS_PER_DAY") == 20
    assert settings.get("FOLLOW_WHITELIST_ONLY") is True
    assert settings.get("FOLLOW_RATIO_CEILING") == 0.8
    assert settings.get("NEWS_MODEL") is None


def test_env_file_values_are_typed(fresh):
    fresh('MAX_FOLLOWS_PER_DAY=12\nFOLLOW_GROWTH_MODE=1\nFOLLOW_RATIO_CEILING=0.5\nBOT_HANDLE="Other"\n')
    assert settings.get("MAX_FOLLOWS_PER_DAY") == 12
    assert settings.get("FOLLOW_GROWTH_MODE") is True
    assert settings.get("FOLLOW_RATIO_CEILING") == 0.5
    assert settings.get("BOT_HANDLE") == "Other"


def test_the_process_environment_wins_over_env_file_as_before(fresh):
    environ = fresh("MAX_FOLLOWS_PER_DAY=5\nOLLAMA_MODEL=from-file\nLIKE_BOT_PER_CYCLE=3\n",
                    {"MAX_FOLLOWS_PER_DAY": "7", "OLLAMA_MODEL": "from-process"})
    assert settings.get("MAX_FOLLOWS_PER_DAY") == 7
    # config.dry_run() and the model CLIs read the environment: .env reaches
    # it, never over a value the process already has.
    assert environ["OLLAMA_MODEL"] == "from-process"
    assert environ["LIKE_BOT_PER_CYCLE"] == "3"


def test_the_first_occurrence_of_a_duplicated_key_wins(fresh):
    fresh("MAX_FOLLOWS_PER_DAY=5\nMAX_FOLLOWS_PER_DAY=9\n")
    assert settings.get("MAX_FOLLOWS_PER_DAY") == 5


def test_env_file_is_read_once(fresh, tmp_path):
    fresh("MAX_FOLLOWS_PER_DAY=5\n")
    other = tmp_path / "other.env"
    other.write_text("MAX_FOLLOWS_PER_DAY=9\n")
    settings.load(env_file=str(other), environ={})
    assert settings.get("MAX_FOLLOWS_PER_DAY") == 5


# --- Bounds: applied once, with a startup warning ------------------------------


@pytest.mark.parametrize("line, name, bound", [
    ("MAX_ORIGINALS_PER_DAY=12", "MAX_ORIGINALS_PER_DAY", 8),
    ("MIN_SECONDS_BETWEEN_POSTS=60", "MIN_SECONDS_BETWEEN_POSTS", 1200),
    ("POST_JITTER_SECONDS=-900", "POST_JITTER_SECONDS", 0),
])
def test_a_value_past_its_bound_is_brought_back_with_a_warning(fresh, line, name, bound):
    fresh(line + "\n")
    assert settings.get(name) == bound
    assert [w for w in settings.startup_warnings() if w.startswith(name)]


def test_a_stricter_value_is_kept_without_warning(fresh):
    fresh("MAX_ORIGINALS_PER_DAY=5\nMIN_SECONDS_BETWEEN_POSTS=3600\n")
    assert settings.get("MAX_ORIGINALS_PER_DAY") == 5
    assert settings.get("MIN_SECONDS_BETWEEN_POSTS") == 3600
    assert settings.startup_warnings() == []


# The Operator's bounds (2026-09-25, #201): name, a value past the bound, the
# bound, a value stricter than the default.
OPERATOR_BOUNDS = [
    ("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "9", 4, 2),
    ("MIN_SECONDS_BETWEEN_REPLIES", "0", 8, 30),
    ("REPLY_JITTER_SECONDS", "-5", 0, 3),
    ("LIKE_BOT_PER_CYCLE", "22", 10, 5),
    ("LIKE_BOT_DAILY_CAP", "1800", 500, 200),
    ("FOLLOW_TOTAL_CAP", "5000", 3500, 200),
    ("MAX_FOLLOWS_PER_DAY", "40", 20, 10),
    ("FOLLOWBACK_CAP", "30", 8, 4),
    ("FOLLOW_ENGAGERS_PER_DAY", "25", 10, 5),
    ("FOLLOW_ENGAGERS_PER_CYCLE", "5", 2, 1),
    ("BAN_SHORT_TERM_PRICE_TARGETS", "0", True, True),
    ("DUP_JACCARD_THRESHOLD", "0.9", 0.45, 0.3),
    ("DUP_CONTAINMENT_THRESHOLD", "0.95", 0.6, 0.5),
    ("DUP_SHARED_BIGRAMS", "10", 3, 2),
    ("DUP_TOPIC_WINDOW_HOURS", "6", 24.0, 72.0),
    ("DUP_TOPIC_SHARED_WORDS", "8", 3, 2),
    ("DUP_TEXT_WINDOW_HOURS", "12", 48.0, 96.0),
    ("REPLY_MIN_CHARS", "5", 25, 40),
]


@pytest.mark.parametrize("name, past, bound, stricter", OPERATOR_BOUNDS)
def test_an_operator_bound_brings_env_back_to_it_with_a_warning(fresh, name, past, bound, stricter):
    fresh(f"{name}={past}\n")
    assert settings.get(name) == bound
    assert [w for w in settings.startup_warnings() if w.startswith(f"{name}=")]


@pytest.mark.parametrize("name, past, bound, stricter", OPERATOR_BOUNDS)
def test_a_value_stricter_than_the_default_is_kept(fresh, name, past, bound, stricter):
    fresh(f"{name}={settings.show(settings.DECLARED[name], stricter)}\n")
    assert settings.get(name) == stricter
    assert settings.startup_warnings() == []


@pytest.mark.parametrize("name, past, bound, stricter", OPERATOR_BOUNDS)
def test_an_override_cannot_pass_an_operator_bound(settings_override, name, past, bound, stricter):
    settings_override(**{name: settings._parse(settings.DECLARED[name], past)})
    assert settings.get(name) == bound


# Volume and count settings with a floor, and the floor a negative is brought
# back to: FOLLOWBACK_CAP=-1 once sliced 49 candidates out of 50.
COUNT_FLOORS = [
    ("MAX_ORIGINALS_PER_DAY", 0),
    ("FOLLOW_TOTAL_CAP", 0),
    ("MAX_FOLLOWS_PER_DAY", 0),
    ("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", 0),
    # At 0, any recent Original would make every new one a duplicate.
    ("DUP_SHARED_BIGRAMS", 1),
    ("DUP_TOPIC_SHARED_WORDS", 0),
    ("LIKE_BOT_PER_CYCLE", 0),
    ("LIKE_BOT_DAILY_CAP", 0),
    ("FOLLOWBACK_CAP", 0),
    ("FOLLOW_ENGAGERS_PER_DAY", 0),
    ("FOLLOW_ENGAGERS_PER_CYCLE", 0),
]


@pytest.mark.parametrize("name, floor", COUNT_FLOORS)
def test_a_negative_count_is_brought_back_to_its_floor_with_a_warning(fresh, name, floor):
    fresh(f"{name}=-1\n")
    assert settings.get(name) == floor
    assert settings.startup_warnings() == [f"{name}=-1 is below its floor: using {floor}."]


def test_every_int_setting_with_a_ceiling_has_a_floor():
    assert [name for name, setting in settings.DECLARED.items()
            if setting.type is int and setting.ceiling is not None and setting.floor is None] == []


def test_the_price_target_ban_stays_on_and_says_so(fresh):
    fresh("BAN_SHORT_TERM_PRICE_TARGETS=0\n")
    assert settings.startup_warnings() == ["BAN_SHORT_TERM_PRICE_TARGETS=0 is below its floor: using 1."]


def test_the_price_target_switch_serves_on_whatever_the_override(settings_override):
    settings_override(BAN_SHORT_TERM_PRICE_TARGETS=False)
    assert config.ban_short_term_price_targets() is True


def test_a_stricter_follow_total_cap_above_its_default_is_kept(fresh):
    """The default stays 300; the ceiling of 3500 is the Operator's."""
    fresh("FOLLOW_TOTAL_CAP=3000\n")
    assert settings.get("FOLLOW_TOTAL_CAP") == 3000
    assert settings.DECLARED["FOLLOW_TOTAL_CAP"].default == 300
    assert settings.startup_warnings() == []


def test_the_dry_run_shows_every_bounded_value_and_the_warnings(monkeypatch, settings_override, capsys):
    import json
    import main
    monkeypatch.setattr(settings, "_warnings", ["LIKE_BOT_DAILY_CAP=1800 is above its ceiling: using 500."])
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    settings_override(LIKE_BOT_DAILY_CAP=200, MIN_SECONDS_BETWEEN_REPLIES=30)
    main.main()
    shown = json.loads(capsys.readouterr().out)
    bounded = shown["bounded_settings"]
    assert set(bounded) == {s.name for s in settings.DECLARED.values()
                            if s.floor is not None or s.ceiling is not None}
    assert {name for name, *_ in OPERATOR_BOUNDS} <= set(bounded)
    assert bounded["LIKE_BOT_DAILY_CAP"] == {"value": 200, "floor": 0, "ceiling": 500}
    assert bounded["MIN_SECONDS_BETWEEN_REPLIES"] == {"value": 30, "floor": 8}
    assert bounded["BAN_SHORT_TERM_PRICE_TARGETS"] == {"value": True, "floor": True}
    assert shown["settings_warnings"] == ["LIKE_BOT_DAILY_CAP=1800 is above its ceiling: using 500."]


def test_main_logs_the_bound_warnings_at_startup(monkeypatch):
    import main
    logged = []
    monkeypatch.setattr(settings, "_warnings", ["MAX_ORIGINALS_PER_DAY=12 is above its ceiling: using 8."])
    monkeypatch.setattr(main.log, "warning", logged.append)
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    main.main()
    assert logged == ["[SETTINGS] MAX_ORIGINALS_PER_DAY=12 is above its ceiling: using 8."]


# --- The override fixture ------------------------------------------------------


def _read_by_the_code():
    return (settings.get("MAX_FOLLOWS_PER_DAY"), settings.get("FOLLOW_GROWTH_MODE"),
            config.MAX_FOLLOWS_PER_DAY, config.follow_whitelist_only(), config.dry_run())


@pytest.fixture
def restored_afterwards():
    """Set up before `settings_override`, so torn down after it."""
    before = _read_by_the_code()
    yield
    assert _read_by_the_code() == before


def test_the_override_fixture_applies_then_restores(restored_afterwards, settings_override):
    settings_override(MAX_FOLLOWS_PER_DAY=3, FOLLOW_GROWTH_MODE=True)
    assert settings.get("MAX_FOLLOWS_PER_DAY") == 3
    assert settings.get("FOLLOW_GROWTH_MODE") is True


def test_the_override_fixture_reaches_what_the_config_serves(restored_afterwards, settings_override):
    settings_override(MAX_FOLLOWS_PER_DAY=3, FOLLOW_WHITELIST_ONLY=False, DRY_RUN=True)
    assert config.MAX_FOLLOWS_PER_DAY == 3
    assert config.follow_whitelist_only() is False
    assert config.dry_run() is True


def test_dry_run_reads_the_environment_at_call_time_unless_overridden(monkeypatch, settings_override):
    monkeypatch.setenv("DRY_RUN", "1")
    assert config.dry_run() is True
    monkeypatch.setenv("DRY_RUN", "0")
    assert config.dry_run() is False
    settings_override(DRY_RUN=True)
    assert config.dry_run() is True


@pytest.mark.parametrize("switch, name, value, served", [
    ("follow_whitelist_only", "FOLLOW_WHITELIST_ONLY", False, False),
    ("followback_bypass_whitelist", "FOLLOWBACK_BYPASS_WHITELIST", False, False),
    ("follow_enforce_ratio", "FOLLOW_ENFORCE_RATIO", True, True),
    ("follow_growth_mode", "FOLLOW_GROWTH_MODE", True, True),
    ("profile_llm_provider", "PROFILE_LLM_PROVIDER", " codex ", "codex"),
    ("reply_llm_provider", "REPLY_LLM_PROVIDER", "  ", None),
])
def test_a_side_effect_switch_is_a_function_read_at_call_time(settings_override, switch, name, value, served):
    settings_override(**{name: value})
    assert getattr(config, switch)() == served


@pytest.mark.parametrize("name, value, served", [
    ("PROFILE_LLM_PROVIDER", " codex ", "codex"),
    ("REPLY_LLM_PROVIDER", "  ", None),
])
def test_the_provider_switches_keep_their_constant(settings_override, name, value, served):
    settings_override(**{name: value})
    assert getattr(config, name) == served


@pytest.mark.parametrize("name", [
    "FOLLOW_WHITELIST_ONLY", "FOLLOWBACK_BYPASS_WHITELIST", "FOLLOW_ENFORCE_RATIO",
    "FOLLOW_GROWTH_MODE", "BAN_SHORT_TERM_PRICE_TARGETS"])
def test_a_switch_constant_nothing_read_is_gone(name):
    """#200: only the function serves these switches."""
    assert not hasattr(config, name)


def test_a_setting_config_derives_follows_its_override(settings_override):
    from src.core.config import REPLY_MODEL  # a copy made at import, as src/replies still does
    settings_override(BOT_HANDLE="Other", AI_CLI=" Codex ", REPLY_MODEL=None)
    assert config.BOT_PROFILE_URL == "https://x.com/Other"
    assert config.AI_CLI == "codex"
    assert REPLY_MODEL.for_provider("claude") == "claude-haiku-4-5-20251001"
    settings_override(REPLY_MODEL="set-model")
    assert REPLY_MODEL.for_provider("claude") == "set-model"


def test_undoing_a_config_monkeypatch_leaves_a_global_behind():
    """Why tests/conftest.py drops these globals after every test: monkeypatch
    sets back the value it read instead of deleting the attribute."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "MAX_FOLLOWS_PER_DAY", 5)
        assert config.MAX_FOLLOWS_PER_DAY == 5
    assert vars(config)["MAX_FOLLOWS_PER_DAY"] == settings.get("MAX_FOLLOWS_PER_DAY")


def test_no_test_starts_with_a_global_hiding_a_setting(settings_override):
    """Runs after the test above, and after every test that patched config."""
    assert not set(vars(config)) & set(config._READ_AT_ACCESS)
    settings_override(MAX_FOLLOWS_PER_DAY=4)
    assert config.MAX_FOLLOWS_PER_DAY == 4


def test_an_override_ends_with_its_block_even_on_error():
    before = settings.get("MAX_FOLLOWS_PER_DAY")
    with pytest.raises(RuntimeError):
        with settings.overriding() as override:
            override(MAX_FOLLOWS_PER_DAY=3)
            with settings.overriding() as inner:
                inner(MAX_FOLLOWS_PER_DAY=4)
                assert settings.get("MAX_FOLLOWS_PER_DAY") == 4
            assert settings.get("MAX_FOLLOWS_PER_DAY") == 3
            raise RuntimeError
    assert settings.get("MAX_FOLLOWS_PER_DAY") == before


def test_an_override_is_typed_and_bounded_like_env(settings_override):
    with pytest.raises(TypeError, match="MAX_FOLLOWS_PER_DAY"):
        settings_override(MAX_FOLLOWS_PER_DAY="3")
    with pytest.raises(KeyError, match="NOT_A_SETTING"):
        settings_override(NOT_A_SETTING=1)
    settings_override(MAX_ORIGINALS_PER_DAY=12, FOLLOW_RATIO_CEILING=1)
    assert settings.get("MAX_ORIGINALS_PER_DAY") == 8
    assert settings.get("FOLLOW_RATIO_CEILING") == 1.0


def test_reading_an_undeclared_setting_fails():
    with pytest.raises(KeyError, match="NOT_A_SETTING"):
        settings.get("NOT_A_SETTING")


# --- .env is loaded before any model call, whatever is imported first ---------


def test_main_loads_settings_before_any_other_project_import():
    body = ast.parse((ROOT / "main.py").read_text()).body

    def project_import(node):
        if isinstance(node, ast.ImportFrom):
            return (node.module or "").split(".")[0] == "src"
        return isinstance(node, ast.Import) and any(a.name.split(".")[0] == "src" for a in node.names)

    def loads(node):
        return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value) == "settings.load()")

    imports = [i for i, node in enumerate(body) if project_import(node)]
    load = next(i for i, node in enumerate(body) if loads(node))
    first = body[imports[0]]
    assert isinstance(first, ast.ImportFrom) and first.module == "src.core"
    assert [a.name for a in first.names] == ["settings"]
    assert all(i > load for i in imports[1:])


@pytest.mark.parametrize("first", [
    "src.core.llm_client", "src.core.logger", "src.core.state_store", "src.core.config"])
def test_env_file_reaches_the_llm_client_whatever_is_imported_first(tmp_path, first):
    """The logger no longer imports the config: nothing may depend on it to
    load .env before llm_client reads its model."""
    env_file = tmp_path / ".env"
    env_file.write_text("OLLAMA_MODEL=probe-model\nAI_CLI=codex\n")
    code = (
        "import importlib, os, sys\n"
        "from src.core import settings\n"
        "settings.ENV_FILE = sys.argv[1]\n"
        f"importlib.import_module({first!r})\n"
        "from src.core import llm_client\n"
        "print(llm_client._ollama_model(llm_client.TEXT_PROFILE), os.environ.get('AI_CLI'), "
        "settings.get('AI_CLI'))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("OLLAMA_MODEL", "AI_CLI")}
    out = subprocess.run([sys.executable, "-c", code, str(env_file)], env=env, check=True,
                         capture_output=True, text=True, cwd=ROOT)
    assert out.stdout.split() == ["probe-model", "codex", "codex"]


# --- No module reads the environment but settings and config.dry_run() --------

_ENV_NAMES = {"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"}
_OS_MODULES = {"os", "posix", "nt"}
_ENV_FILE_PATH = re.compile(r"(?:^|[/\\])\.env$")


def _dry_run(tree):
    """The top-level `dry_run` function of `tree`, if any."""
    return next((node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == "dry_run"), None)


def _env_reads(tree, allow_dry_run=False):
    """Line numbers of every environment access in `tree`, outside the
    top-level `dry_run` function when `allow_dry_run`: `os.environ`,
    `os.getenv`, whatever the module is bound to, `from os import environ`
    or `*`, the name as a string (`getattr(os, "environ")`,
    `vars(os)["environ"]`), the os module handed over as a value
    (`getattr(os, name)`, `vars(os)`, `os.__dict__`), and a second read of
    `.env` (`settings._read_env_file`, a `.env` path literal)."""
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    os_names = {(a.asname or a.name).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for a in node.names if a.name.split(".")[0] in _OS_MODULES}
    skipped = set()
    if allow_dry_run and (function := _dry_run(tree)):
        skipped = {id(n) for n in ast.walk(function)}
    return sorted(node.lineno for node in ast.walk(tree)
                  if id(node) not in skipped and _reads_env(node, parents.get(id(node)), os_names))


def _reads_env(node, parent, os_names) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in _ENV_NAMES | {"_read_env_file"}
    if isinstance(node, ast.ImportFrom):
        return any(a.name in _ENV_NAMES | {"_read_env_file"}
                   or (a.name == "*" and node.module in _OS_MODULES) for a in node.names)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in _ENV_NAMES or bool(_ENV_FILE_PATH.search(node.value))
    if isinstance(node, ast.Name):
        if node.id == "_read_env_file":
            return True
        return (node.id in os_names and isinstance(node.ctx, ast.Load)
                and not (isinstance(parent, ast.Attribute) and parent.attr != "__dict__"))
    return False


def _dry_run_keys(tree):
    """The keys the top-level `dry_run` reads from the environment; None
    stands for a read whose key is not a string literal."""
    function = _dry_run(tree)
    parents = {id(child): node for node in ast.walk(function) for child in ast.iter_child_nodes(node)}
    keys = set()
    for node in ast.walk(function):
        if not (isinstance(node, ast.Attribute) and node.attr in _ENV_NAMES):
            continue
        parent = parents.get(id(node))
        key = None
        if node.attr == "environ" and isinstance(parent, ast.Subscript):
            key = parent.slice
        elif node.attr == "environ" and isinstance(parent, ast.Attribute) and parent.attr == "get":
            call = parents.get(id(parent))
            key = call.args[0] if isinstance(call, ast.Call) and call.args else None
        elif node.attr == "getenv" and isinstance(parent, ast.Call) and parent.args:
            key = parent.args[0]
        keys.add(key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None)
    return keys


def _code_files():
    files = [ROOT / "main.py", *sorted((ROOT / "bin").glob("*.py")),
             *sorted((ROOT / "scripts").glob("*.py")), *sorted((ROOT / "src").rglob("*.py"))]
    return [f for f in files if f != ROOT / "src/core/settings.py"]


def test_no_module_reads_the_environment_but_settings_and_dry_run():
    reads = {}
    for path in _code_files():
        name = str(path.relative_to(ROOT))
        if lines := _env_reads(ast.parse(path.read_text()), allow_dry_run=name == "src/core/config.py"):
            reads[name] = lines
    assert not reads, f"read a setting through src/core/settings.py instead: {reads}"


@pytest.mark.parametrize("code", [
    "import os\nX = os.environ.get('X')",
    "import os\ndef f():\n    return os.getenv('X')",
    "import os as system\nX = system.environ['X']",
    "from os import environ\n",
    "from os import getenv as read\n",
    "import os\nX = getattr(os, 'environ')",
    "from os import *\nX = environ['X']",
    "import os\nX = vars(os)['environ']['X']",
    "import os\nX = os.__dict__['environ']['X']",
    "import os\nname = 'env' + 'iron'\nX = getattr(os, name)",
    "from src.core import settings\nX = settings._read_env_file('/tmp/x')",
    "from src.core.settings import _read_env_file\n",
    "with open('.env') as f:\n    X = f.read()",
    "from pathlib import Path\nX = (Path(__file__).parent / '.env').read_text()",
    "import os\ndef dry_run():\n    pass\ndef other():\n    return os.environ",
    "import os\nclass Switch:\n    def dry_run(self):\n        return os.environ.get('DRY_RUN')",
    "import os\ndef outer():\n    def dry_run():\n        return os.environ.get('DRY_RUN')",
])
def test_the_environment_check_catches_every_form(code):
    assert _env_reads(ast.parse(code), allow_dry_run=True)


def test_the_environment_check_lets_text_about_env_through():
    code = "import os\nX = os.path.join('a', 'b')\nDOC = 'set it in `.env`, then restart'\n"
    assert not _env_reads(ast.parse(code))


def test_config_reads_the_environment_in_dry_run_only():
    tree = ast.parse((ROOT / "src/core/config.py").read_text())
    assert _env_reads(tree) and not _env_reads(tree, allow_dry_run=True)
    assert _dry_run_keys(tree) == {"DRY_RUN"}


@pytest.mark.parametrize("code", [
    "import os\ndef dry_run():\n    return os.environ.get('DRY_RUN') or os.environ.get('LIVE')",
    "import os\ndef dry_run():\n    return os.getenv('DRY_RUN') == os.environ['LIVE']",
    "import os\nKEY = 'DRY_RUN'\ndef dry_run():\n    return os.environ.get(KEY)",
    "import os\ndef dry_run():\n    return dict(os.environ)",
])
def test_the_dry_run_check_catches_any_other_key(code):
    assert _dry_run_keys(ast.parse(code)) != {"DRY_RUN"}


def test_script_keys_are_not_declared():
    assert not set(settings.DECLARED) & settings.SCRIPT_KEYS


def test_every_script_key_is_read_by_a_script_that_sources_env():
    scripts = "".join((ROOT / name).read_text() for name in ("operator_cycle.sh", "bot_watchdog.sh"))
    assert all(f"${{{key}" in scripts for key in settings.SCRIPT_KEYS)


# --- docs/CONFIGURATION.md and .env.example agree with the declarations ------

_KEY_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_KEY_ASSIGNMENT = re.compile(r"^\s*(?:#\s*)?(?:export\s+)?([A-Z][A-Z0-9_]*)=", re.MULTILINE)
# Named in the doc without being `.env` keys: the ceilings of
# src/core/config.py, the table of per-provider models, the policy file.
_NOT_KEYS = {name for name in dir(config) if name.isupper()} | {"MODEL_DEFAULTS", "EDITORIAL_POLICY"}


def _configuration_doc():
    spec = importlib.util.spec_from_file_location("configuration_doc", ROOT / "bin/configuration_doc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_configuration_reference_is_generated_from_the_declarations():
    doc = _configuration_doc()
    text = (ROOT / "docs/CONFIGURATION.md").read_text()
    assert doc.current(text) == doc.render(), "run: uv run python bin/configuration_doc.py --write"


def test_the_configuration_reference_lists_every_setting_with_its_default_and_bounds():
    rendered = _configuration_doc().render()
    for setting in settings.DECLARED.values():
        row = next(line for line in rendered.splitlines() if line.startswith(f"| `{setting.name}` |"))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if setting.name in settings.MODEL_DEFAULTS:
            assert "MODEL_DEFAULTS" in cells[2]
        elif setting.default not in (None, ""):
            assert cells[2] == f"`{settings.show(setting, setting.default)}`", setting.name
        for bound in (setting.floor, setting.ceiling):
            if bound is not None:
                assert f"`{settings.show(setting, bound)}`" in cells[3], setting.name
    for name, table in settings.MODEL_DEFAULTS.items():
        row = next(line for line in rendered.splitlines()
                   if line.startswith(f"| `{name}` |") and "MODEL_DEFAULTS" not in line)
        assert all(f"`{model}`" in row for model in table.values()), name


def _unknown_keys(text):
    named = set(_KEY_TOKEN.findall(text)) | set(_KEY_ASSIGNMENT.findall(text))
    return sorted(k for k in named - _NOT_KEYS if not settings._is_known(k))


def test_the_configuration_doc_names_no_unknown_key():
    """A key the engine does not know stops the start: the doc must not offer
    one, in backticks, in plain text or in a `KEY=value` line."""
    unknown = _unknown_keys((ROOT / "docs/CONFIGURATION.md").read_text())
    assert not unknown, unknown


@pytest.mark.parametrize("text", [
    "Set `MAX_NEWS_PER_DAY` to 5.",
    "Set MAX_NEWS_PER_DAY to 5.",
    "```env\nMAX_NEWS_PER_DAY=5\n```",
    "```env\nVERBOSE=1\n```",
    "```sh\nexport VERBOSE=1\n```",
])
def test_the_unknown_key_check_catches_every_form(text):
    assert _unknown_keys(text)


def _env_example():
    return settings._read_env_file(str(ROOT / ".env.example"))


def test_env_example_starts_within_every_bound(fresh):
    fresh((ROOT / ".env.example").read_text())
    assert settings.startup_warnings() == []


def test_env_example_describes_the_account_with_the_declared_defaults():
    """The defaults carry the policy values: the example sets no other, so
    it cannot offer more than the policy allows. No setting without effect
    either, nor a key only an older account used."""
    example = _env_example()
    assert example["BOT_ACCOUNT"] == "theaishrink"
    assert not {"BOT_HANDLE", "CONTENT_LANG_PRIMARY"} & set(example), "the Account carries them"
    assert not set(example) & settings.UNUSED
    assert set(example) <= set(settings.DECLARED) | {"ENABLE_AI_MAINTENANCE", "ENABLE_CODEX_OPERATOR"}
    for key, raw in example.items():
        if key in settings.DECLARED:
            setting = settings.DECLARED[key]
            assert settings._parse(setting, raw) == setting.default, key


def test_model_cli_credentials_in_env_file_do_not_stop_the_start(tmp_path):
    """A key the model CLIs read from their environment (an API key, the
    Ollama host) may sit in .env for the subprocesses; any other unknown key
    still stops the start."""
    from src.core import settings
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_BASE_URL", "OLLAMA_HOST"):
        assert settings._is_known(key), key
    assert not settings._is_known("MAX_BREAKOUTS_PER_DAY")
