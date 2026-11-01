from contextlib import nullcontext
from dataclasses import replace

import pytest

from src.video import reconcile
from src.video.security import Deferred
from src.video.store import Store
from src.x import safari_video as browser


def test_bounded_novelty_records_actual_search_scope_without_claiming_global_absence(video_store, video_cfg, ready, at):
    doc = ready()
    video_store.save_candidate("clip1", doc, at().timestamp(), state="held",
                               fingerprint={"sha256": doc["original_sha256"], "visual": []})
    class Search:
        scope = "fixture bounded results; global absence is not established"
        calls = 0
        def search(self, query, cursor):
            self.calls += 1
            return {"data": [], "meta": {"next_token": str(self.calls)}}
    client = Search()
    assert reconcile.novelty(video_store, video_store.candidate("clip1"), client, video_cfg,
                             at().timestamp()) == "checked_no_match"
    result = video_store.candidate("clip1")["document"]["novelty"]
    assert client.calls == 6 and result["truncated"] is True
    assert "global absence is not established" in result["scope"]


def post(ident):
    return {"id": ident, "text": "fixture", "created_at": "2026-11-01T12:00:00Z", "urls": [],
            "url": f"https://x.com/example/status/{ident}", "video": False}


def snapshot(ids, **extra):
    return {"posts": [post(ident) for ident in ids], "height": 5000, "bottom": False,
            "loading": False, "empty": False, "error": False, **extra}


@pytest.fixture
def scan(monkeypatch, video_store, video_cfg):
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(browser.time, "sleep", lambda *a: None)
    monkeypatch.setattr(browser.safari, "open_url", lambda *a: True)
    monkeypatch.setattr(browser.safari, "_run_js", lambda *a: "scrolled")
    closed = []
    monkeypatch.setattr(browser.safari, "close_front_tab", lambda: closed.append(True))
    def run(pages, cursor):
        pages = iter(pages)
        monkeypatch.setattr(browser, "_json", lambda *a: next(pages))
        client = browser.SafariVideoClient(video_store, replace(video_cfg, publishing_transport="safari"))
        result = client.timeline(cursor)
        assert closed
        return result
    return run


def test_replayed_viewports_are_collected_before_scrolling(scan):
    result = scan([snapshot(["1"]), snapshot(["2"]), snapshot(["3"]), snapshot(["4"])],
                  {"offset": 2, "last": []})
    assert [row["id"] for row in result["data"]] == ["1", "2", "3", "4"]
    assert result["meta"]["next_token"]["offset"] == 3


@pytest.mark.parametrize("bottom,loading", [(False, False), (True, True)])
def test_stable_viewport_is_not_proof_of_timeline_end(scan, bottom, loading):
    page = snapshot(["1"], bottom=bottom, loading=loading)
    result = scan([page, page], {"offset": 0, "last": ["1"]})
    assert result["meta"]["next_token"]


def test_only_repeated_stable_nonloading_bottom_closes_scan(scan):
    page = snapshot(["1"], bottom=True)
    result = scan([page, page, page], {"offset": 0, "last": ["1"]})
    assert "next_token" not in result["meta"]


def test_late_loaded_posts_keep_history_open(scan):
    page = snapshot(["1"], bottom=True)
    result = scan([page, page, snapshot(["1", "2"], bottom=True, height=6000)],
                  {"offset": 0, "last": ["1"]})
    assert result["meta"]["next_token"]
    assert len(result["data"]) == 2


def test_deferred_fingerprints_resume_exact_saved_page_after_restart(video_store, video_cfg, at, monkeypatch):
    video_store.set_meta("history_import_complete", False)
    class Client:
        calls = 0
        def preflight(self):
            pass
        def timeline(self, cursor):
            self.calls += 1
            assert self.calls == 1, "unfinished page must survive reflow/restart"
            return {"data": [dict(post("1"), attachments={"media_keys": ["v"]}), post("2")],
                    "includes": {"media": [{"media_key": "v", "type": "video"}]}, "meta": {}}
    client = Client()
    def pending(*args, **kwargs):
        raise Deferred("sample pending")
    monkeypatch.setattr(reconcile, "media_fingerprint", pending)
    with pytest.raises(Deferred):
        reconcile.import_history(video_store, client, video_cfg, at().timestamp())
    assert not video_store.meta("history_import_complete")
    monkeypatch.setattr(reconcile, "media_fingerprint", lambda *a, **k: {"visual": ["fixture"]})
    restarted = Store(video_store.path)
    reconcile.import_history(restarted, client, video_cfg, at().timestamp())
    assert len(restarted.rows("SELECT * FROM history")) == 2
    assert restarted.meta("history_import_complete")
    assert restarted.meta("history_pending_page") is None


def test_three_video_batch_does_not_drop_unprocessed_page_tail(video_store, video_cfg, at, monkeypatch):
    video_store.set_meta("history_import_complete", False)
    class Client:
        def preflight(self):
            pass
        def timeline(self, cursor):
            return {"data": [dict(post(str(i)), attachments={"media_keys": ["v"]}) for i in range(4)],
                    "includes": {"media": [{"media_key": "v", "type": "video"}]}, "meta": {}}
    client = Client()
    monkeypatch.setattr(reconcile, "media_fingerprint", lambda *a, **k: {"visual": ["fixture"]})
    reconcile.import_history(video_store, client, video_cfg, at().timestamp())
    assert len(video_store.rows("SELECT * FROM history")) == 3
    assert not video_store.meta("history_import_complete")
    reconcile.import_history(Store(video_store.path), client, video_cfg, at().timestamp())
    assert len(video_store.rows("SELECT * FROM history")) == 4
    assert video_store.meta("history_import_complete")


@pytest.mark.parametrize("seconds,passes,complete", [(0, 1, False), (60, 2, True)])
def test_history_cli_retries_reads_without_activation(video_store, video_cfg, monkeypatch, capsys, seconds, passes, complete):
    from types import SimpleNamespace
    from src.video import cli, workers
    video_store.set_meta("history_import_complete", False)
    monkeypatch.setattr(cli, "Store", lambda: video_store)
    monkeypatch.setattr(cli.config, "load", lambda: replace(video_cfg, publishing_transport="safari"))
    monkeypatch.setattr(cli.state_store, "require_migrated", lambda: None)
    calls = []
    def read(store, client, cfg, now):
        assert workers.owns_role("publisher")
        calls.append(now)
        if len(calls) == 1:
            raise Deferred("saved samples", retry_after=0)
        store.set_meta("history_import_complete", True)
    monkeypatch.setattr(reconcile, "import_history", read)
    cli._execute(SimpleNamespace(command="check-history", max_seconds=seconds))
    assert len(calls) == passes
    assert video_store.meta("history_import_complete") is complete
    assert not video_store.rows("SELECT * FROM startup")
    assert not video_store.rows("SELECT * FROM reservations")
    assert '"imported": 0' in capsys.readouterr().out


@pytest.mark.parametrize("seconds", ["-1", "3601"])
def test_history_cli_bounds_continuation_interval(seconds):
    from src.video import cli
    with pytest.raises(SystemExit) as error:
        cli.main(["check-history", "--max-seconds", seconds])
    assert error.value.code == 2
