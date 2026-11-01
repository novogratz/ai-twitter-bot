from dataclasses import replace
import json

from src.video import inspection, preparation, publisher, ranking, reconcile


def test_preparation_starts_thirty_minutes_before_and_is_restart_idempotent(video_store, video_cfg, at):
    cfg = replace(video_cfg, windows=("07:00", "09:00", "12:00", "17:00", "19:00", "21:00"),
                  paired_windows=("07:00", "21:00"), platforms={"bilibili": {"enabled": True}})
    before = at(18, 29, 59, day=1)
    preparation.prepare_upcoming(video_store, cfg, before.timestamp())
    assert not video_store.rows("SELECT * FROM jobs")
    now = at(18, 30, day=1)
    preparation.prepare_upcoming(video_store, cfg, now.timestamp())
    preparation.prepare_upcoming(video_store, cfg, now.timestamp() + 1)
    assert len(video_store.rows("SELECT * FROM jobs WHERE kind='discovery'")) == 1
    assert len(video_store.rows("SELECT * FROM events WHERE kind='preparation_started'")) == 1
    assert len(video_store.rows("SELECT * FROM events WHERE kind='supply_warning'")) == 1
    assert not video_store.rows("SELECT * FROM reservations")
    assert not video_store.rows("SELECT * FROM startup")


def test_bounded_history_is_explicit_and_never_labels_archive_complete(video_store, video_cfg, at, ready):
    doc = ready()
    video_store.set_meta("history_import_complete", False)
    video_store.set_meta("history_cursor", {"offset": 6})
    cfg = replace(video_cfg, initial_history_pages=6)
    assert not reconcile.history_ready(video_store, cfg)
    with video_store.transaction() as db:
        db.execute("INSERT INTO history VALUES('old',?,?)", (at().timestamp(), json.dumps({"text": "old"})))
    assert not reconcile.history_ready(video_store, video_cfg)
    assert reconcile.history_ready(video_store, cfg)
    assert not video_store.meta("history_import_complete")
    assert publisher.reserve(video_store, at(), cfg)


def test_unknown_momentum_fallback_preserves_scores_and_all_quality_gates(video_store, video_cfg, ready, at):
    doc = ready()
    cfg = replace(video_cfg, allow_unknown_momentum=True)
    doc['ranking'] = ranking.score(doc, [], [], at().timestamp(), cfg)
    assert doc['ranking']['total'] < 80 and doc['ranking']['components']['momentum'] is None
    assert ranking.gate(doc, video_cfg, at().timestamp(), final=True) == 'below score threshold'
    assert not ranking.gate(doc, cfg, at().timestamp(), final=True)
    doc['qc']['audio_sync'] = False
    assert ranking.gate(doc, cfg, at().timestamp(), final=True) == 'output quality uncertain'
    doc['qc']['audio_sync'] = True
    doc['novelty']['state'] = 'unchecked'
    assert 'novelty' in ranking.gate(doc, cfg, at().timestamp(), final=True)


def test_cast_attribution_needs_actual_source_provenance_and_does_not_prove_performance(video_cfg):
    doc = {'title': 'Example Star music parody', 'creator': 'creator', 'canonical_url': 'https://example.test/video'}
    assert not inspection.cast_context(doc, video_cfg)
    doc['publication_evidence'] = {'method': 'fixture actual source page'}
    context = inspection.cast_context(doc, video_cfg)
    assert context['cast'] == {'performer': 'Example Star'}
    assert 'not face identification' in context['basis']
    assert 'confidence' not in context and 'performance' not in context


def test_ready_imminent_slot_does_not_start_a_routine_browser_read(video_store, video_cfg, ready, at, monkeypatch):
    from src.video import workers, schedule
    now = at(6, 58)
    ready(when=now)
    cfg = replace(video_cfg, publishing_transport='safari')
    monkeypatch.setattr(schedule, 'utc_now', lambda: now)
    monkeypatch.setattr(workers.publisher, 'publish_tick', lambda *a: 'waiting')
    calls = []
    monkeypatch.setattr(workers, '_x_work', lambda *a: calls.append(True))
    assert workers.run_once('publisher', video_store, cfg, 'test', now=now.timestamp()) == 'waiting'
    assert calls == []


def test_normal_stop_does_not_trip_provider_circuit(video_store, video_cfg, at, monkeypatch):
    from src.video import workers
    from src.x import safari_video
    from src.guards.active_hours import OutsideActiveHours
    class Client:
        def __init__(self, *a):
            pass
        def preflight(self, **kw):
            raise OutsideActiveHours('operator stop')
    monkeypatch.setattr(safari_video, 'SafariVideoClient', Client)
    assert workers._x_work(video_store, replace(video_cfg, publishing_transport='safari'), 'test', at().timestamp()) == 'interaction cooldown'
    assert video_store.rows('SELECT * FROM circuits') == []
