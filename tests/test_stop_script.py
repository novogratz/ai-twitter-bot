"""Real disposable Python processes; never target the live repository."""
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("flags", [[], ["-u"], ["-B", "-u"]])
def test_stop_handles_interpreter_flags_and_preserves_other_repositories(tmp_path, flags):
    if not shutil.which("lsof") or not shutil.which("pgrep"):
        pytest.skip("stop script requires lsof and pgrep")
    repo, other = tmp_path / "repo", tmp_path / "other"
    (repo / "bin").mkdir(parents=True)
    other.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "bin/stop_bot.sh", repo / "bin/stop_bot.sh")
    code = "from pathlib import Path\nimport time\nPath('ready').touch()\ntime.sleep(30)\n"
    for folder in (repo, other):
        (folder / "main.py").write_text(code)
    processes = [subprocess.Popen([sys.executable, *flags, "main.py"], cwd=folder) for folder in (repo, other)]
    try:
        deadline = time.monotonic() + 5
        while not all((folder / "ready").exists() for folder in (repo, other)) and time.monotonic() < deadline:
            time.sleep(.01)
        assert all((folder / "ready").exists() for folder in (repo, other))
        result = subprocess.run(["/bin/bash", str(repo / "bin/stop_bot.sh")], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        assert processes[0].wait(timeout=5) != 0
        assert processes[1].poll() is None
        assert (repo / ".bot_disabled").exists()
        assert not (other / ".bot_disabled").exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
