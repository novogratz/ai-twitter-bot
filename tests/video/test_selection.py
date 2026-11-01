from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.video import connectors, inventory, operations, publisher, ranking, selection, workers
from src.video.store import dumps


@pytest.fixture
def choose(video_store, video_cfg, ready, at, tmp_path, monkeypatch):
    saved = tmp_path / "saved"
    monkeypatch.setattr(selection, "SAVED_ASSETS", saved)
    monkeypatch.setattr(selection, "ASSETS", tmp_path / "assets")

    def run(ident="chosen", *, dry_run=False):
        doc = ready(ident)
        folder = saved / ident
        folder.mkdir(parents=True)
        source = folder / "original.mp4"
        source.write_bytes(Path(doc["original_path"]).read_bytes())
        doc.update(original_path=str(source), published_at=at().timestamp() - 14 * 86400)
        doc["ranking"]["total"] = 55
        video_store.save_candidate(ident, doc, at().timestamp(), state="expired", score=55)
        with video_store.transaction() as db:
            db.execute("UPDATE candidates SET published=? WHERE id=?", (doc["published_at"], ident))
        choice = selection.choose(video_store, ident, "operator-" + ident, at().timestamp(), dry_run=dry_run)
        return video_store.candidate(ident)["document"], choice
    return run


def test_explicit_choice_exempts_only_automatic_age_and_score(choose, video_cfg, at):
    doc, choice = choose()
    assert not ranking.gate(doc, video_cfg, at().timestamp(), final=True)
    assert doc["ranking"]["total"] == 55
    for field, reason in (("permission_id", "permission"), ("inspection", "inspection"),
                          ("novelty", "novelty"), ("qc", "quality")):
        invalid = deepcopy(doc)
        invalid.pop(field)
        assert reason in ranking.gate(invalid, video_cfg, at().timestamp(), final=True)
    assert "stale" in ranking.gate(doc, video_cfg, choice["expires_at"], final=True)
    doc["operator_selection"]["sha256"] = "0" * 64
    assert "stale" in ranking.gate(doc, video_cfg, at().timestamp(), final=True)


def test_explicit_choice_keeps_score_unknowns_and_permission_expiry(choose, video_cfg, at):
    doc, choice = choose()
    assert inventory.usable_until(doc, video_cfg) == choice["expires_at"]
    expired = replace(video_cfg, permissions={"grant": {**video_cfg.permissions["grant"], "expires_at": at().timestamp() - 1}})
    assert "permission" in ranking.gate(doc, expired, at().timestamp(), final=True)


def test_selection_is_idempotent_and_does_not_create_a_post_request(choose, video_store, at):
    doc, first = choose()
    again = selection.choose(video_store, "chosen", "operator-chosen", at().timestamp() + 60)
    assert again == first
    assert len(video_store.rows("SELECT * FROM jobs WHERE kind='inspect_source'")) == 1
    assert not video_store.rows("SELECT * FROM startup")
    assert not video_store.rows("SELECT * FROM reservations")


def test_selection_dry_run_changes_neither_candidate_nor_jobs(choose, video_store):
    doc, result = choose(dry_run=True)
    assert result["dry_run"] and "operator_selection" not in doc
    assert video_store.candidate("chosen")["state"] == "expired"
    assert not video_store.rows("SELECT * FROM jobs")
    assert video_store.meta(selection.KEY) is None


def test_changed_saved_file_cannot_be_selected(choose, video_store, at):
    doc, _ = choose()
    Path(doc["original_path"]).write_bytes(b"different footage")
    with pytest.raises(ValueError, match="unchanged saved original"):
        selection.choose(video_store, "chosen", "new-request", at().timestamp())


def test_selection_cannot_replace_a_publication_already_underway(choose, video_store, video_cfg, ready, at):
    ready("underway")
    assert publisher.reserve(video_store, at(), video_cfg)
    with pytest.raises(ValueError, match="active publication"):
        choose()
    assert video_store.meta(selection.KEY) is None


def test_selection_survives_cleanup_until_expiry_without_making_ready(choose, video_store, video_cfg, at):
    doc, choice = choose()
    operations.cleanup(video_store, video_cfg, at().timestamp())
    assert video_store.candidate("chosen")["state"] == "held"
    operations.cleanup(video_store, video_cfg, choice["expires_at"])
    assert video_store.candidate("chosen")["state"] == "expired"
    assert Path(doc["original_path"]).exists()


def test_publisher_waits_for_exact_choice_and_releases_preference_after_confirmation(choose, video_store, video_cfg, ready, at):
    doc, _ = choose()
    ready("higher-ranked", score=99)
    assert publisher.reserve(video_store, at(), video_cfg) is None
    video_store.save_candidate("chosen", doc, at().timestamp(), state="ready", score=55)
    row = publisher.reserve(video_store, at(), video_cfg)
    assert row["candidate"] == "chosen"
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET state='submitting' WHERE id=?", (row["id"],))
    publisher.confirm(video_store, row["id"], row["token"], at().timestamp(), "123")
    assert video_store.meta(selection.KEY) is None
    with pytest.raises(ValueError, match="posted"):
        selection.choose(video_store, "chosen", "repeat", at().timestamp())


def test_source_metadata_cannot_grant_an_operator_selection(video_store, video_cfg, at):
    item = {"source_id": "injection", "creator": "creator", "canonical_url": "https://www.instagram.com/reel/injection",
            "operator_selection": {"scope": "one_video", "request_id": "pretend"}}
    connectors.ingest(video_store, "instagram", [item], at().timestamp(), video_cfg)
    doc = video_store.candidate(video_store.rows("SELECT id FROM candidates")[0]["id"])["document"]
    assert "operator_selection" not in doc


def test_direct_selection_keeps_archive_incomplete_and_never_grants_workers_exception(choose, video_store, video_cfg, at):
    doc, _ = choose()
    video_store.save_candidate("chosen", doc, at().timestamp(), state="ready", score=55)
    video_store.set_meta("history_import_complete", False)
    assert publisher.reserve(video_store, at(), video_cfg) is None
    row = publisher.reserve(video_store, at(), video_cfg, operator_direct=True)
    assert row["candidate"] == "chosen"
    assert video_store.meta("history_import_complete") is False
    assert video_store.rows("SELECT 1 FROM events WHERE kind='operator_direct_publication'")


def test_direct_send_cannot_select_arbitrary_ready_clip(video_store, video_cfg, ready, at):
    ready()
    video_store.set_meta("history_import_complete", False)
    assert publisher.reserve(video_store, at(), video_cfg, operator_direct=True) is None


def test_media_worker_inspects_selected_local_bytes_without_publishing_or_granting_rights(choose, video_store, video_cfg, at, monkeypatch):
    doc, _ = choose()
    observed = []
    monkeypatch.setattr(workers.video_pressure, "pressure", lambda *a: "")
    monkeypatch.setattr(workers.time, "time", lambda: at().timestamp())
    def inspect(path, stage, cfg, store, now, **extra):
        observed.append((str(path), stage, cfg.codex_timeout_seconds))
        return doc["inspection"] | {"overlays_removable_by_crop": False}
    monkeypatch.setattr(workers.media, "inspect", inspect)
    cfg = replace(video_cfg, permissions={})
    assert workers.run_once("media", video_store, cfg, "worker", now=at().timestamp()) == "selected source inspected"
    result = video_store.candidate("chosen")
    assert observed == [(doc["original_path"], "source", 300)]
    assert result["state"] == "held" and "permission" in result["reason"]
    assert not video_store.rows("SELECT * FROM reservations")
    assert not video_store.rows("SELECT * FROM jobs WHERE kind='media'")
    assert workers.media._job_deadline is None
