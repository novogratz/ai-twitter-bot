from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from src.core import settings, state_store
from src.video import workers


@pytest.fixture
def process(monkeypatch, tmp_path):
    class MissingProcess(Exception):
        pass
    class Denied(Exception):
        pass
    class Process:
        pid = 424242
        started = 100.0
        signals = 0
        args = ["python", str(Path(settings.PROJECT_ROOT) / "bin" / "video.py"), "worker", "media"]
        files = []
        def cmdline(self): return self.args
        def cwd(self): return settings.PROJECT_ROOT
        def create_time(self): return self.started
        def open_files(self): return [SimpleNamespace(path=path) for path in self.files]
        def terminate(self): self.signals += 1
    value = Process()
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=lambda pid: value,
        NoSuchProcess=MissingProcess, AccessDenied=Denied))
    return value


def supervisor(runtime):
    result = workers.Supervisor.__new__(workers.Supervisor)
    result.runtime, result.retiring = runtime, {}
    return result


def runtime():
    return {"fingerprint": "current", "files_modified_at": 200,
            "project_root": str(Path(settings.PROJECT_ROOT).resolve()),
            "state_root": str(Path(state_store.root()).resolve())}


def lock_file(process, tmp_path):
    path = tmp_path / "video_media.lock"
    path.write_text(str(process.pid))
    process.files = [str(path)]
    return path


def test_same_generation_external_worker_is_preserved(video_store, process, tmp_path):
    path = lock_file(process, tmp_path)
    expected = runtime()
    video_store.set_meta("worker_runtime:media", expected | {
        "pid": process.pid, "process_started_at": process.started, "owner": "fixture"})
    supervisor(expected)._handover_stale_worker(video_store, "media", path)
    assert process.signals == 0


def test_verified_obsolete_worker_receives_one_signal_and_claims_are_untouched(video_store, process, tmp_path):
    path = lock_file(process, tmp_path)
    expected = runtime()
    video_store.set_meta("worker_runtime:media", expected | {
        "fingerprint": "old", "pid": process.pid, "process_started_at": process.started})
    video_store.enqueue("media", "candidate", 100)
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET state='running',owner='old',lease=9999999999,token='fenced'")
        db.execute("INSERT INTO content_claims VALUES('candidate','unknown-send')")
    instance = supervisor(expected)
    instance._handover_stale_worker(video_store, "media", path)
    instance._handover_stale_worker(video_store, "media", path)
    assert process.signals == 1
    assert video_store.rows("SELECT state,owner,token FROM jobs") == [{"state": "running", "owner": "old", "token": "fenced"}]
    assert video_store.rows("SELECT * FROM content_claims") == [{"candidate": "candidate", "reservation": "unknown-send"}]


@pytest.mark.parametrize("change", ["wrong_script", "wrong_role", "not_lock_owner", "reused_pid", "new_legacy", "publisher"])
def test_unknown_or_current_process_is_never_signaled(video_store, process, tmp_path, change):
    path = lock_file(process, tmp_path)
    expected = runtime()
    if change == "wrong_script": process.args = ["python", "/different/repo/bin/video.py", "worker", "media"]
    elif change == "wrong_role": process.args = ["python", str(Path(settings.PROJECT_ROOT) / "bin" / "video.py"), "worker", "discovery"]
    elif change == "not_lock_owner": process.files = []
    elif change == "reused_pid": video_store.set_meta("worker_runtime:media", expected | {"pid": process.pid, "process_started_at": 99})
    elif change == "new_legacy": process.started = 201
    supervisor(expected)._handover_stale_worker(video_store, "publisher" if change == "publisher" else "media", path)
    assert process.signals == 0


def test_legacy_worker_replaced_only_after_verified_code_or_config_update(video_store, process, tmp_path):
    path = lock_file(process, tmp_path)
    instance = supervisor(runtime())
    instance._handover_stale_worker(video_store, "media", path)
    assert process.signals == 1


def test_generation_covers_effective_config_and_source_without_exposing_secret(video_cfg, monkeypatch, tmp_path, settings_override):
    monkeypatch.setattr(settings, "PROJECT_ROOT", str(tmp_path))
    (tmp_path / "src").mkdir()
    module = tmp_path / "src" / "worker.py"
    module.write_text("code version one")
    (tmp_path / ".env").write_text("PRIVATE_TOKEN=secret-canary")
    monkeypatch.setattr(settings, "ENV_FILE", str(tmp_path / ".env"))
    first = workers.runtime_generation(video_cfg)
    assert "secret-canary" not in str(first)
    assert workers.runtime_generation(replace(video_cfg, max_age_hours=730 * 24))["fingerprint"] != first["fingerprint"]
    settings_override(CODEX_REASONING_EFFORT="high")
    assert workers.runtime_generation(video_cfg)["fingerprint"] != first["fingerprint"]
    settings_override(CODEX_REASONING_EFFORT="")
    module.write_text("code version two")
    assert workers.runtime_generation(video_cfg)["fingerprint"] != first["fingerprint"]
    before_settings = workers.runtime_generation(video_cfg)
    settings_override(REPLY_MODEL="secret-model-canary")
    after_settings = workers.runtime_generation(video_cfg)
    assert after_settings["fingerprint"] != before_settings["fingerprint"]
    assert "secret-model-canary" not in str(after_settings)


def test_supervisor_waits_for_old_lock_release_before_replacement(video_store, video_cfg, process, monkeypatch):
    cfg = replace(video_cfg, publishing_transport="safari")
    monkeypatch.setattr(workers.config, "load", lambda: cfg)
    monkeypatch.setattr(workers, "Store", lambda: video_store)
    monkeypatch.setattr(workers, "runtime_generation", lambda cfg: runtime())
    path = Path(str(state_store.StatePath("video_media.lock")))
    path.write_text(str(process.pid))
    process.files = [str(path)]
    held = [True]
    actual_flock = workers.fcntl.flock
    def flock(handle, mode):
        if Path(handle.name) == path and held[0]:
            raise BlockingIOError()
        return actual_flock(handle, mode)
    monkeypatch.setattr(workers.fcntl, "flock", flock)
    starts = []
    class Child:
        def __init__(self, argv, **kwargs): starts.append(argv[-1])
        def poll(self): return 0
        def wait(self, **kwargs): return 0
    monkeypatch.setattr(workers.subprocess, "Popen", Child)
    instance = workers.Supervisor()
    try:
        instance.tick()
        assert starts == ["discovery"] and process.signals == 1
        instance.tick()
        assert starts == ["discovery"] and process.signals == 1
        held[0] = False
        instance.tick()
        assert starts == ["discovery", "media"]
        assert workers.owns_role("publisher")
    finally:
        instance.stop()
