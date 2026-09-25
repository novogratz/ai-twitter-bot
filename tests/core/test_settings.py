"""src/core/settings: every engine setting declared once, typed and bounded,
`.env` read once at startup (#195)."""
import ast
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


def test_keys_of_modules_not_migrated_yet_and_of_the_scripts_are_accepted(fresh):
    """During the expand step (#196 to #199), the keys a module still reads
    itself must not stop the start; nor those the shell scripts source."""
    keys = sorted(settings.PENDING | settings.SCRIPT_KEYS)
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
    # Modules not migrated yet read the environment: .env reaches it, never
    # over a value the process already has.
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
            config.MAX_FOLLOWS_PER_DAY, config.FOLLOW_WHITELIST_ONLY, config.dry_run())


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
    assert config.FOLLOW_WHITELIST_ONLY is False
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
    ("ban_short_term_price_targets", "BAN_SHORT_TERM_PRICE_TARGETS", False, False),
    ("profile_llm_provider", "PROFILE_LLM_PROVIDER", " codex ", "codex"),
    ("reply_llm_provider", "REPLY_LLM_PROVIDER", "  ", None),
])
def test_a_side_effect_switch_is_a_function_its_constant_calls(settings_override, switch, name, value, served):
    settings_override(**{name: value})
    assert getattr(config, switch)() == served
    assert getattr(config, name) == served


def test_a_setting_config_derives_follows_its_override(settings_override):
    settings_override(BOT_HANDLE="Other", AI_CLI=" Codex ", REPLY_MODEL=None)
    assert config.BOT_PROFILE_URL == "https://x.com/Other"
    assert config.AI_CLI == "codex"
    assert config.REPLY_MODEL == "gpt-5.4-mini"


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
    load .env before llm_client freezes its model at import."""
    env_file = tmp_path / ".env"
    env_file.write_text("OLLAMA_MODEL=probe-model\nAI_CLI=codex\n")
    code = (
        "import importlib, os, sys\n"
        "from src.core import settings\n"
        "settings.ENV_FILE = sys.argv[1]\n"
        f"importlib.import_module({first!r})\n"
        "from src.core import llm_client\n"
        "print(llm_client.OLLAMA_MODEL, os.environ.get('AI_CLI'), settings.get('AI_CLI'))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("OLLAMA_MODEL", "AI_CLI")}
    out = subprocess.run([sys.executable, "-c", code, str(env_file)], env=env, check=True,
                         capture_output=True, text=True, cwd=ROOT)
    assert out.stdout.split() == ["probe-model", "codex", "codex"]


# --- Every key the code reads is known: the expand step stops no legit .env ----

_LITERAL_READ = re.compile(
    r'os\.(?:environ\.get|getenv)\(\s*"([A-Z0-9_]+)"|os\.environ\[\s*"([A-Z0-9_]+)"\s*\]')
_DYNAMIC_READ = re.compile(r'os\.(?:environ\.get|getenv)\((?!\s*")')
_DYNAMIC_SITES: set[str] = set()


def _engine_files():
    files = [ROOT / "main.py", *sorted((ROOT / "bin").glob("*.py")), *sorted((ROOT / "src").rglob("*.py"))]
    return [f for f in files if f.name != "settings.py" or f.parent.name != "core"]


def test_every_key_the_code_reads_is_declared_or_pending():
    read, dynamic = set(), set()
    for path in _engine_files():
        text = path.read_text()
        read |= {a or b for a, b in _LITERAL_READ.findall(text)}
        if _DYNAMIC_READ.search(text):
            dynamic.add(str(path.relative_to(ROOT)))
    assert dynamic <= _DYNAMIC_SITES, "a new environment read by computed name: teach this test its keys"
    assert "DRY_RUN" in read
    missing = sorted(read - set(settings.DECLARED) - settings.PENDING)
    assert not missing, f"read from the environment but unknown to settings: {missing}"


def test_declared_pending_and_script_keys_do_not_overlap():
    declared = set(settings.DECLARED)
    assert not declared & settings.PENDING
    assert not declared & settings.SCRIPT_KEYS
    assert not settings.PENDING & settings.SCRIPT_KEYS


def test_every_script_key_is_read_by_a_script_that_sources_env():
    scripts = "".join((ROOT / name).read_text() for name in ("operator_cycle.sh", "bot_watchdog.sh"))
    assert all(f"${{{key}" in scripts for key in settings.SCRIPT_KEYS)


def test_the_config_no_longer_reads_the_environment():
    """Only config.dry_run() still does, at call time."""
    text = (ROOT / "src/core/config.py").read_text()
    reads = {a or b for a, b in _LITERAL_READ.findall(text)}
    assert reads <= {"DRY_RUN"}
    assert not _DYNAMIC_READ.search(text)


def test_model_cli_credentials_in_env_file_do_not_stop_the_start(tmp_path):
    """A key the model CLIs read from their environment (an API key, the
    Ollama host) may sit in .env for the subprocesses; any other unknown key
    still stops the start."""
    from src.core import settings
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_BASE_URL", "OLLAMA_HOST"):
        assert settings._is_known(key), key
    assert not settings._is_known("MAX_BREAKOUTS_PER_DAY")
