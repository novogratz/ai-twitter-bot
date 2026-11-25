"""Operator, 2026-11-25: outside X only, no mark but ours, underdogs on a high rating, the trend first."""
from dataclasses import replace

import pytest

from src.video import exposure, instagram_browse, media, publisher, ranking, reconcile
from src.video.security import AccessError, Deferred


def test_x_exclusive_refuses_an_x_source_and_any_copy_already_on_x(ready, video_store, video_cfg, at):
    doc, now = ready(), at().timestamp()
    cfg = replace(video_cfg, bangers_only=True)
    doc["qc"].update(doc["inspection"], opening={"hook_score": 10, "cast_visible_first_second": True,
        "action_first_second": True, "no_dead_intro": True}, opening_samples_reviewed=True,
        opening_sample_times=[0, .2, .4, .6, .8])
    doc["novelty"] = {"state": "verified_low_reach_match", "checked_at": now,
                      "matching_copies": [{"views": 120, "observed_at": now}]}
    assert not ranking.gate(doc, cfg, now, final=True)              # the earlier allowance: a small copy passes
    strict = replace(cfg, x_exclusive=True)
    assert "X novelty" in ranking.gate(doc, strict, now, final=True)
    doc["novelty"] = {"state": "checked_no_match", "checked_at": now}
    assert not ranking.gate(doc, strict, now, final=True)
    assert "outside X" in ranking.source_gate(doc | {"platform": "x"}, now, strict)


def test_output_with_another_mark_is_held_until_the_inspector_saw_none(ready, video_cfg):
    doc = ready()
    cfg = replace(video_cfg, clean_watermarks_only=True)
    assert "still visible" in ranking.output_gate(doc, cfg)          # never reviewed is not clean
    doc["qc"]["foreign_watermark_visible"] = True
    assert "still visible" in ranking.output_gate(doc, cfg)
    doc["qc"]["foreign_watermark_visible"] = False
    assert not ranking.output_gate(doc, cfg)
    assert not ranking.output_gate(ready("clip2"), video_cfg)        # other Accounts keep the old rule


def test_inspector_located_logo_joins_the_removed_regions_within_bounds():
    info = {"width": 1080, "height": 1920}
    marks = [{"x": .80, "y": .02, "w": .15, "h": .05},     # a drawn platform icon, no text for OCR
             {"x": .10, "y": .30, "w": .80, "h": .40},     # the picture itself: refused
             {"x": .95, "y": .5, "w": .2, "h": .05}, "junk", {"x": "a"}]
    boxes = media.source_logo_boxes({"ocr_evidence": [], "foreign_marks": marks}, info)
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert x > 800 and y >= 1 and x + w < 1080 and h < 160
    assert media.source_logo_boxes({"ocr_evidence": []}, info) == []


def test_inspection_asks_for_marks_only_when_the_account_wants_a_clean_output(video_cfg):
    from src.video import inspection
    cfg = replace(video_cfg, clean_watermarks_only=True)
    assert "foreign_marks" in inspection.schema(cfg, "source")["properties"]
    assert "foreign_watermark_visible" in inspection.schema(cfg, "output")["properties"]
    assert "foreign_marks" not in inspection.schema(video_cfg, "source")["properties"]
    assert "foreign_watermark_visible" not in inspection.schema(video_cfg, "output")["properties"]


@pytest.mark.parametrize("plays,likes,refused", [(6000, 50, False), (1000, 250, False), (None, 250, False),
                                                 (1000, 50, True), (None, 50, True), (60000, 10, False)])
def test_underdog_reaches_inspection_above_its_own_floor(video_cfg, plays, likes, refused):
    cfg = replace(video_cfg, audience_min_views=50000, audience_min_likes=2000, underdog_min_views=5000, underdog_min_likes=200)
    doc = {"title": "Example Star AI song", "discovery_evidence": {"method": instagram_browse.CREATOR_GRID, "views": plays},
           "source_stats": {"likes": likes}}
    assert bool(instagram_browse.lead_refusal(doc, cfg)) is refused
    closed = replace(cfg, underdog_min_views=0, underdog_min_likes=0)
    assert bool(instagram_browse.lead_refusal(doc, closed)) is (refused or plays != 60000)


def test_underdog_needs_the_high_rating_a_proven_audience_does_not(ready, video_cfg, at):
    cfg = replace(video_cfg, bangers_only=True, banger_component_min=5.5, banger_fit_min=7, banger_floors=(14, 12, 9),
                  audience_min_views=50000, audience_min_likes=2000, underdog_min_likes=200, underdog_min_editorial=75)
    doc, now = ready(), at().timestamp()
    doc["inspection"]["banger_scores"] = {key: 7 for key in doc["inspection"]["banger_scores"]}   # 70/100
    doc["source_stats"] = {"likes": 300}
    assert ranking.underdog(doc, cfg) and "underdog rating below 75" in ranking.gate(doc, cfg, now)
    doc["source_stats"] = {"likes": 90000}
    assert not ranking.underdog(doc, cfg) and not ranking.gate(doc, cfg, now)
    doc["source_stats"] = {"likes": 300}
    doc["inspection"]["banger_scores"] = {key: 8 for key in doc["inspection"]["banger_scores"]}
    assert not ranking.gate(doc, cfg, now)
    doc["source_stats"] = {}
    assert not ranking.underdog(doc, cfg)                                 # unknown audience is not an underdog
    with pytest.raises(ValueError):
        replace(cfg, underdog_min_likes=5000)                              # never above the audience floor


def test_trend_cast_goes_first_among_comparable_clips_and_in_search_turns(video_store, video_cfg):
    cfg = replace(video_cfg, targets={"performer": ["Example Star"], "other": ["Other Star"]}, trend_cast=("other",),
                  platforms={"instagram": {"browse_queries": ["example star ai", "other star ai", "tech ceo ai parody"]}})
    searches = [value for _, value, _ in instagram_browse.pages(video_store, cfg)[1]]
    assert searches == ["other star ai", "example star ai", "other star ai", "tech ceo ai parody"]
    plain = [value for _, value, _ in instagram_browse.pages(video_store, replace(cfg, trend_cast=()))[1]]
    assert plain == ["example star ai", "other star ai", "tech ceo ai parody"]
    with pytest.raises(ValueError):
        replace(cfg, trend_cast=("nobody",))


def test_one_unreadable_x_post_no_longer_holds_the_duplicate_check(ready, video_store, video_cfg, at, monkeypatch):
    # 2026-11-25: three approved clips waited all morning on a search result with no playable video.
    doc, now = ready(), at().timestamp()
    cfg = replace(video_cfg, bangers_only=True)
    fp = {"sha256": doc["original_sha256"], "visual": [["1234567890abcdef"]] * 4}
    doc["qc"].update(doc["inspection"], opening={"hook_score": 10, "cast_visible_first_second": True,
        "action_first_second": True, "no_dead_intro": True}, opening_samples_reviewed=True,
        opening_sample_times=[0, .2, .4, .6, .8])
    video_store.save_candidate("clip1", doc, now, state="held", fingerprint=fp)
    monkeypatch.setattr(exposure, "queries", lambda *a: ["fixture source query"])
    calls = []
    def unreadable(*args, **kwargs):
        calls.append(1)
        raise AccessError("native video duration unavailable")
    monkeypatch.setattr(reconcile, "media_fingerprint", unreadable)
    page = {"data": [{"id": "1", "attachments": {"media_keys": ["m1"]}}],
            "includes": {"media": [{"type": "video", "media_key": "m1", "post_url": "https://x.com/someone/status/1"}]}, "meta": {}}
    class Client:
        def search(self, *args):
            return page
    for _ in range(exposure.UNREADABLE_TRIES - 1):
        with pytest.raises(AccessError):
            exposure.check(video_store, video_store.candidate("clip1"), Client(), cfg, now)
    state = exposure.check(video_store, video_store.candidate("clip1"), Client(), cfg, now)
    assert state == "checked_no_match" and len(calls) == exposure.UNREADABLE_TRIES
    assert video_store.candidate("clip1")["document"]["novelty"]["unreadable_posts"]
    # any other read failure still fails the check
    video_store.save_candidate("clip1", doc, now, state="held", fingerprint=fp)
    monkeypatch.setattr(reconcile, "media_fingerprint", lambda *a, **k: (_ for _ in ()).throw(AccessError("X page unavailable or rate limited")))
    for _ in range(5):
        with pytest.raises(AccessError):
            exposure.check(video_store, video_store.candidate("clip1"), Client(), cfg, now)
