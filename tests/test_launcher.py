"""Exercise the real launcher with fake processes in a disposable repository."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "repo"
    scripts = root / "bin"
    scripts.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "bin/run.sh", scripts / "run.sh")
    core = root / "src/core"
    core.mkdir(parents=True)
    (core / "config.py").write_text('BOT_HANDLE = "ConfiguredBot"\n')
    (core / "settings.py").write_text(
        'import os\n'
        'if os.environ.get("TEST_BAD_CONFIG"):\n'
        '    raise ValueError("invalid launcher test configuration")\n'
        'def get(name):\n'
        '    assert name == "VIDEO_ENABLED", name\n'
        '    return os.environ["TEST_VIDEO_ENABLED"] == "1"\n'
    )
    (root / "main.py").write_text(
        'import os, sys\n'
        'print(f"fake main reached; terminal={sys.stdout.isatty()}", flush=True)\n'
        'code = int(os.environ.get("TEST_MAIN_EXIT", "0"))\n'
        'if code:\n'
        '    print("fake main startup failure", file=sys.stderr)\n'
        'raise SystemExit(code)\n'
    )
    commands = tmp_path / "commands"
    commands.mkdir()
    trace = tmp_path / "commands.jsonl"

    def command(name, body):
        path = commands / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    record = (
        'import json, os, sys\n'
        'with open(os.environ["TEST_COMMAND_TRACE"], "a") as trace:\n'
        '    trace.write(json.dumps(sys.argv) + "\\n")\n'
    )
    command("uv", record +
            'args = sys.argv[1:]\n'
            'assert args.pop(0) == "run"\n'
            'while args[0] == "--with-requirements":\n'
            '    del args[:2]\n'
            'assert args.pop(0) == "python"\n'
            'os.execv(sys.executable, [sys.executable, *args])\n')
    command("pgrep", record + 'raise SystemExit(1)\n')
    command("find", record)
    for name in ("curl", "ollama", "codex", "pkill", "tee"):
        command(name, record + 'raise SystemExit("unexpected external command")\n')

    def run(video="0", *, bad_config=False, exit_code=0, startup=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE):
        env = dict(os.environ, PATH=f"{commands}{os.pathsep}{os.environ['PATH']}",
                   TEST_COMMAND_TRACE=str(trace), TEST_VIDEO_ENABLED=video,
                   TEST_MAIN_EXIT=str(exit_code), TEST_BAD_CONFIG="1" if bad_config else "")
        env.pop("STARTUP_PUBLICATIONS", None)
        if startup is not None:
            env["STARTUP_PUBLICATIONS"] = startup
        result = subprocess.run(["/bin/bash", str(scripts / "run.sh")], cwd=tmp_path,
                                env=env, text=True, stdout=stdout, stderr=stderr, timeout=10)
        calls = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        return result, calls

    return run


@pytest.mark.parametrize("video, requirements", [("0", "requirements.txt"), ("1", "requirements-video.txt")])
def test_launcher_reaches_main_without_any_model_warmup(launcher, video, requirements):
    result, calls = launcher(video)
    assert result.returncode == 0, result.stderr
    assert "[run] Starting @ConfiguredBot bot." in result.stdout
    assert "fake main reached" in result.stdout
    assert [Path(call[0]).name for call in calls] == ["uv", "pgrep", "find", "uv"]
    assert calls[-1][1:] == ["run", "--with-requirements", requirements, "python", "-u", "main.py"]
    assert "news + video requested first" not in result.stdout


def test_launcher_explicit_startup_opt_in(launcher):
    result, calls = launcher(startup="1")
    assert result.returncode == 0 and "--startup-publications" in calls[-1]


def test_bad_startup_setting_cannot_touch_running_processes(launcher):
    result, calls = launcher(startup="oops")
    assert result.returncode == 2 and calls == []


def test_launcher_preserves_startup_failure_and_exit_code(launcher):
    result, _ = launcher(exit_code=37)
    assert result.returncode == 37
    assert "fake main startup failure" in result.stderr


def test_bad_configuration_stops_before_touching_a_running_bot(launcher):
    result, calls = launcher(bad_config=True)
    assert result.returncode != 0
    assert "invalid launcher test configuration" in result.stderr
    assert "Starting" not in result.stdout
    assert [Path(call[0]).name for call in calls] == ["uv"]


def test_launcher_keeps_the_terminal_attached(launcher):
    import errno
    import pty

    master, slave = pty.openpty()
    try:
        result, _ = launcher(stdout=slave, stderr=slave)
        # macOS can discard unread output when the last slave closes.
        # The child has exited; drain available bytes before closing ours.
        os.set_blocking(master, False)
        output = b""
        while True:
            try:
                chunk = os.read(master, 4096)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            output += chunk
        assert result.returncode == 0
        assert b"fake main reached; terminal=True" in output
    finally:
        os.close(master)
        os.close(slave)
