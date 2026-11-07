from copy import deepcopy
from dataclasses import replace
import json

import pytest

from src.video import bangers, config, connectors, discovery_plan, exposure, handoff, media, memory, preparation, ranking
from src.video.security import Deferred


@pytest.fixture
def qualified(ready, video_store, video_cfg, at):
    doc = ready()
    doc["original_fingerprint"] = {"sha256": doc["original_sha256"], "visual": [["1234567890abcdef"]] * 4}
    doc["output_fingerprint"] = doc["original_fingerprint"]
    doc["qc"].update(doc["inspection"], opening={"hook_score": 10, "cast_visible_first_second": True,
        "action_first_second": True, "no_dead_intro": True}, opening_samples_reviewed=True,
        opening_sample_times=[0, .2, .4, .6, .8])
    video_store.save_candidate("clip1", doc, at().timestamp(), state="ready", fingerprint=doc["original_fingerprint"])
    return doc


def test_old_exceptional_clip_can_qualify_with_explicit_neutral_prior(qualified, at):
    qualified["published_at"] = at().timestamp() - 400 * 86400
    result = bangers.score(qualified, at().timestamp())
    assert result["total"] == 90.5 and result["status"] == "qualified"
    assert result["scores"]["engagement"] == 5 and result["measured_momentum"] is None
    assert qualified["ranking"].get("components", {}).get("momentum") is None
    qualified["qc"]["banger_scores"] = {k: 8 for k in bangers.JUDGMENTS}
    assert bangers.score(qualified, at().timestamp())["total"] < 82


@pytest.mark.parametrize("change", [
    {"brand_fit": False}, {"language_dependent": True}, {"banger_reason": ""},
    {"banger_scores": {k: 7 for k in bangers.JUDGMENTS}},
    {"banger_scores": {k: float("nan") for k in bangers.JUDGMENTS}},
])
def test_missing_or_weak_evidence_never_gets_a_rubric_score(qualified, at, change):
    qualified["qc"].update(change)
    assert bangers.score(qualified, at().timestamp())["status"] == "hold"


def test_cinematic_reveal_is_eligible_but_generic_other_cast_is_not(qualified, video_cfg, at):
    cfg = replace(video_cfg, bangers_only=True)
    qualified["inspection"]["performance"] = qualified["qc"]["performance"] = "cinematic_parody"
    assert ranking.gate(qualified, cfg, at().timestamp(), final=True) == ""
    qualified["inspection"]["cast"] = ["unverified_background_guest"]
    assert ranking.gate(qualified, cfg, at().timestamp(), final=True)


def test_good_output_cannot_erase_missing_source_language_evidence(qualified, video_cfg, at):
    cfg = replace(video_cfg, bangers_only=True)
    qualified["inspection"]["language_dependent"] = True
    assert "transcript" in ranking.gate(qualified, cfg, at().timestamp(), final=True)


def test_copy_queries_preserve_chinese_titles_and_source_supported_song(qualified, video_cfg):
    qualified["title"] = '特朗普和马斯克合唱《What Is Love》'
    queries = exposure.queries(qualified, video_cfg)
    assert any("特朗普和马斯克合唱" in q for q in queries)
    assert any('"Example Star" "What Is Love"' in q for q in queries)
    assert not any("from:creator" in q for q in queries)


def test_seed_history_is_idempotent_permanent_and_explicitly_partial(video_store, at):
    cfg = config.load()
    memory.import_seed(video_store, cfg, at().timestamp())
    count = len(video_store.rows("SELECT * FROM personal_memory"))
    memory.import_seed(video_store, cfg, at().timestamp() + 10)
    assert len(video_store.rows("SELECT * FROM personal_memory")) == count >= 20
    for url in ("https://www.instagram.com/reel/DfaamAusdla", "https://x.com/DFF6769/status/2118753368755827140"):
        assert "delivered" in memory.refusal(video_store, {"canonical_url": url})
    assert "rejected" in memory.refusal(video_store, {"title": "WE WERE ALWAYS BLUE!"})
    assert not memory.refusal(video_store, {"title": "A different What Is Love performance"})
    assert "partial" in json.dumps(video_store.meta("personal_memory_coverage")).lower()


def test_delivery_memory_survives_changed_url_and_media_cleanup(video_store, qualified, at):
    memory.remember(video_store, video_store.candidate("clip1"), "delivered", at().timestamp())
    changed = deepcopy(qualified)
    changed.update(canonical_url="https://www.tiktok.com/@another/video/123456789", source_id="different")
    assert "delivered" in memory.refusal(video_store, changed)
    with video_store.transaction() as db:
        db.execute("DELETE FROM candidates")
    assert "delivered" in memory.refusal(video_store, changed)


@pytest.mark.parametrize("platform,url,expected", [
    ("youtube", "https://youtu.be/Abcd1234567?t=3", "https://www.youtube.com/watch?v=Abcd1234567"),
    ("youtube", "https://www.youtube.com/shorts/Abcd1234567", "https://www.youtube.com/watch?v=Abcd1234567"),
    ("douyin", "https://www.douyin.com/video/71234567890?x=1", "https://www.douyin.com/video/71234567890"),
])
def test_additional_platforms_are_real_leads_without_claiming_download_capability(platform, url, expected):
    assert connectors.canonical(platform, url) == expected
    cfg = config.load()
    assert cfg.platforms[platform]["public_search"]
    assert not cfg.platforms[platform].get("safari_player")
    assert not ranking.permission({"platform": platform, "creator": "any"}, cfg, 1790000000)


def test_discovery_hour_budget_reopens_next_hour_and_weights_available_sources(video_store, video_cfg, at):
    cfg = replace(video_cfg, adaptive_discovery=True, platforms={
        "instagram": {"public_search": True, "weight": 40}, "bilibili": {"public_search": True, "weight": 30}})
    now = at().timestamp()
    with pytest.raises(Deferred, match="next bounded turn"):
        discovery_plan.admission(video_store, cfg, "bilibili", now)
    for _ in range(3):
        discovery_plan.admission(video_store, cfg, "instagram", now, fresh=True)
    with pytest.raises(Deferred, match="hourly"):
        discovery_plan.admission(video_store, cfg, "instagram", now, fresh=True)
    assert discovery_plan.admission(video_store, cfg, "instagram", now + 3600, fresh=True)
    video_store.set_meta("platform_disabled:instagram", True)
    assert discovery_plan.admission(video_store, cfg, "bilibili", now + 3600)


def test_modes_deep_pass_and_profile_progress_persist(video_store, at):
    cfg = config.load()
    now = at().timestamp()
    cursor, modes, deep = {}, [], 0
    for _ in range(10):
        plan, cursor = discovery_plan.plan(video_store, cfg, "instagram", {"creators": ["verified_seed"]}, cursor, now)
        modes.append(plan["mode"])
        deep += plan["deep"]
        discovery_plan.completed(video_store, "instagram", plan, now)
    assert (modes.count("fresh"), modes.count("archive"), modes.count("new_creators"), deep) == (6, 3, 1, 1)
    assert cursor["turn"] == 10 and cursor["profiles"]["verified_seed"]["passes"] >= 1


def _page(counts, now):
    data, videos = [], []
    for index, views in enumerate(counts):
        ident = str(9000 + index)
        url = "https://x.com/creator/status/" + ident
        data.append({"id": ident, "url": url, "attachments": {"media_keys": [ident]},
                     "view_observation": {"post_id": ident, "url": url, "views": views, "at": now}})
        videos.append({"type": "video", "media_key": ident, "post_url": url})
    return {"data": data, "includes": {"media": videos}, "meta": {}}


def _expose(video_store, cfg, doc, now, page, monkeypatch):
    from src.video import reconcile
    monkeypatch.setattr(exposure, "queries", lambda *a: ["fixture source query"])
    monkeypatch.setattr(reconcile, "media_fingerprint", lambda *a, **k: doc["original_fingerprint"])
    class Client:
        def search(self, *args):
            return page
    for _ in range(10):
        try:
            return exposure.check(video_store, video_store.candidate("clip1"), Client(), cfg, now)
        except Deferred as exc:
            assert "saved matching-copy" in str(exc)
    pytest.fail("bounded exposure pass did not complete")


@pytest.mark.parametrize("counts,state", [
    ([], "checked_no_match"), ([1000, 2000], "verified_low_reach_match"),
    ([1000, 50001], "known_high_reach_match"), ([1000, None], "unknown_or_stale"),
])
def test_exposure_uses_maximum_of_all_matched_copies(video_store, video_cfg, qualified, at, monkeypatch, counts, state):
    cfg = replace(video_cfg, bangers_only=True)
    now = at().timestamp()
    assert _expose(video_store, cfg, qualified, now, _page(counts, now), monkeypatch) == state
    doc = video_store.candidate("clip1")["document"]
    assert doc["novelty"]["highest_observed_views"] == max((v for v in counts if v is not None), default=None)
    assert doc["handoff"]["status"] == ("QUALIFIED" if state in ("checked_no_match", "verified_low_reach_match") else "HOLD")


def test_large_matching_copy_cannot_disappear_on_next_search(video_store, video_cfg, qualified, at, monkeypatch):
    cfg = replace(video_cfg, bangers_only=True)
    now = at().timestamp()
    assert _expose(video_store, cfg, qualified, now, _page([90000], now), monkeypatch) == "known_high_reach_match"
    assert _expose(video_store, cfg, qualified, now + 10, _page([100], now + 10), monkeypatch) == "known_high_reach_match"
    assert _expose(video_store, cfg, qualified, now + 20, _page([], now + 20), monkeypatch) == "known_high_reach_match"


def test_view_evidence_must_belong_to_exact_status(video_store, video_cfg, qualified, at, monkeypatch):
    cfg = replace(video_cfg, bangers_only=True)
    now = at().timestamp()
    page = _page([100], now)
    page["data"][0]["view_observation"]["post_id"] = "borrowed-other-post"
    assert _expose(video_store, cfg, qualified, now, page, monkeypatch) == "unknown_or_stale"


def test_stale_low_reach_and_personal_history_hold_handoff(video_store, video_cfg, qualified, at, monkeypatch):
    cfg = replace(video_cfg, bangers_only=True)
    now = at().timestamp()
    assert _expose(video_store, cfg, qualified, now, _page([100], now - 21601), monkeypatch) == "unknown_or_stale"
    memory.remember(video_store, video_store.candidate("clip1"), "shown", now)
    result = handoff.build(video_store, video_store.candidate("clip1"), qualified, cfg, now)
    assert result["status"] == "HOLD" and "shown" in result["hold_reason"]


def test_truncated_exposure_search_never_claims_no_match(video_store, video_cfg, qualified, at, monkeypatch):
    cfg = replace(video_cfg, bangers_only=True)
    page = _page([], at().timestamp())
    page["meta"]["next_token"] = "more-results"
    assert _expose(video_store, cfg, qualified, at().timestamp(), page, monkeypatch) == "unknown_or_stale"
    assert video_store.candidate("clip1")["document"]["novelty"]["truncated"] is True


@pytest.mark.parametrize("posted", [False, True])
def test_higher_resolution_same_performance_reaches_review_only_when_unposted(
        video_store, video_cfg, qualified, at, tmp_path, monkeypatch, posted):
    cfg = replace(video_cfg, bangers_only=True)
    now = at().timestamp()
    monkeypatch.setattr(media.time, "time", lambda: now)
    monkeypatch.setattr(media, "ASSETS", tmp_path / "managed")
    qualified["probe"].update(width=480, height=360)
    video_store.save_candidate("clip1", qualified, now, state="ready", fingerprint=qualified["original_fingerprint"])
    if posted:
        with video_store.transaction() as db:
            db.execute("INSERT INTO history VALUES(?,?,?)", ("12345", now, json.dumps(qualified)))
    original = tmp_path / "upgrade.mp4"
    original.write_bytes(b"fixture larger-encoded source; decoding and semantics mocked")
    item = {"source_id": "upgrade", "creator": "creator", "canonical_url": "https://www.instagram.com/reel/upgrade",
            "published_at": now - 100, "publication_evidence": "fixture source timestamp", "permission_id": "grant",
            "local_file": str(original)}
    connectors.ingest(video_store, "instagram", [item], now, cfg)
    job = video_store.claim("media", "fixture-worker", now, cfg)
    monkeypatch.setattr(media, "probe", lambda *a, **k: {"duration": 20, "width": 1440, "height": 1080})
    from src.video.security import sha256
    monkeypatch.setattr(media, "fingerprint", lambda path, *a: qualified["original_fingerprint"] | {"sha256": sha256(path)})
    reviews = []
    def inspect(*args, **kwargs):
        reviews.append(True)
        raise Deferred("fixture ends at required independent inspection")
    monkeypatch.setattr(media, "inspect", inspect)
    if posted:
        media.process(video_store, job, now, cfg)
        assert video_store.candidate(job["item"])["state"] == "duplicate" and not reviews
    else:
        with pytest.raises(Deferred, match="required independent"):
            media.process(video_store, job, now, cfg)
        saved = video_store.candidate(job["item"])["document"]
        assert reviews and saved["content_cluster"] == "clip1"
        assert saved["verified_source_variants"][0]["native_detail_verified"] is False


def test_reserve_refreshes_expiring_reach_without_resetting_failed_media(video_store, video_cfg, qualified, at):
    now = at().timestamp()
    cfg = replace(video_cfg, bangers_only=True, adaptive_discovery=True,
                  platforms={"instagram": {"enabled": True, "public_search": True}})
    qualified["novelty"]["checked_at"] = now - cfg.x_reach_max_age_seconds - 1
    video_store.save_candidate("clip1", qualified, now, state="ready", fingerprint=qualified["original_fingerprint"])
    video_store.enqueue("novelty", "clip1", now)
    video_store.enqueue("media", "clip1", now)
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET state='done' WHERE kind='novelty'")
        db.execute("UPDATE jobs SET state='dead',attempts=4 WHERE kind='media'")
    preparation.maintain_reserve(video_store, cfg, now)
    assert video_store.rows("SELECT state FROM jobs WHERE kind='novelty'") == [{"state": "pending"}]
    assert video_store.rows("SELECT state,attempts FROM jobs WHERE kind='media'") == [{"state": "dead", "attempts": 4}]
    assert video_store.meta("reserve-health")["eligible_distinct"] == 0
    assert video_store.candidate("clip1")["state"] == "held"
    preparation.maintain_reserve(video_store, cfg, now + 10)
    assert len(video_store.rows("SELECT * FROM jobs WHERE kind='novelty'")) == 1


def test_mirrored_footage_is_duplicate_but_shared_song_is_not():
    left = {"sha256": "left", "visual": [["0000000000000000"]] * 4,
            "mirrored_visual": [["ffffffffffffffff"]] * 4, "audio": [1, 2, 3, 4]}
    right = {"sha256": "right", "visual": [["ffffffffffffffff"]] * 4, "audio": [4, 3, 2, 1]}
    assert media.duplicate(left, right)
    right.update(visual=[["aaaaaaaaaaaaaaaa"]] * 4, audio=left["audio"])
    assert not media.duplicate(left, right)
