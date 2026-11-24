"""Instagram's own pages supply leads: web search found two in three weeks (2026-11-23)."""
from contextlib import nullcontext
from dataclasses import replace
import json

import pytest

from src.video import connectors, instagram_browse, native_source, source_browser


def cfg_for(video_cfg, **options):
    return replace(video_cfg, platforms={"instagram": {"safari_player": True, "safari_browse": True,
        "creators": ["creator"], "browse_queries": ["ai example star dance"], **options}})


def safari_page(monkeypatch, payload):
    from src.x import safari, safari_video
    calls = []
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda url: calls.append(("open", url)) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: calls.append(("close",)))
    monkeypatch.setattr(safari, "_run_js", lambda js, **kw: calls.append(("js", kw.get("target_url"))) or (
        "scrolled" if "scrollBy" in js else json.dumps(payload(kw.get("target_url")) if callable(payload) else payload)))
    monkeypatch.setattr(instagram_browse.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(native_source.time, "sleep", lambda seconds: None)
    return calls


@pytest.mark.parametrize("text,value", [("87K", 87000), ("59.2K", 59200), ("2,782", 2782), ("729", 729),
    ("1.2M", 1_200_000), ("1,2 M", 1_200_000), ("", None), ("Reel", None), ("12 likes", None)])
def test_displayed_counter_is_read_as_its_lower_bound(text, value):
    assert instagram_browse.count(text) == value


def test_creator_grid_keeps_only_this_creators_most_played_new_reels():
    items = [{"href": "/creator/reel/AAAAA1/", "text": "87K"}, {"href": "/creator/reel/BBBBB2/", "text": "1.7M"},
             {"href": "/creator/reel/CCCCC3/", "text": "729"},           # below the audience floor
             {"href": "/creator/reel/KNOWN01/", "text": "900K"},         # already a candidate
             {"href": "/someone_else/reel/DDDDD4/", "text": "5M"},       # another account's reel
             {"href": "/creator/reel/EEEEE5/", "text": ""},              # counter unreadable
             {"href": "/creator/", "text": "2M"}, {"href": "https://evil.test/reel/FFFFF6/", "text": "2M"}, "junk"]
    found = instagram_browse.leads(items, "creator", "creator", {"KNOWN01"}, {"browse_min_views": 20000}, 1000)
    assert [(lead["source_id"], lead["discovery_evidence"]["views"]) for lead in found] == [("BBBBB2", 1_700_000), ("AAAAA1", 87000)]
    assert found[0]["canonical_url"] == "https://www.instagram.com/reel/BBBBB2" and found[0]["creator"] == "creator"
    assert found[0]["published_at"] is None  # a grid never proves an upload time


def test_search_grid_takes_reels_only_and_claims_no_creator_or_counter():
    items = [{"href": "/p/AAAAA1/", "text": "", "reel": True}, {"href": "/p/PHOTO01/", "text": "", "reel": False},
             {"href": "/reel/BBBBB2/", "text": "9M", "reel": True}]
    found = instagram_browse.leads(items, "search", "ai example star dance", set(), {}, 1000)
    assert [lead["source_id"] for lead in found] == ["AAAAA1", "BBBBB2"]
    assert all(lead["creator"] == "" and lead["discovery_evidence"]["views"] is None and "metrics" not in lead for lead in found)


def test_leads_per_read_is_bounded():
    items = [{"href": f"/creator/reel/CODE{n:03d}/", "text": f"{30 + n}K"} for n in range(40)]
    assert len(instagram_browse.leads(items, "creator", "creator", set(), {"browse_leads_per_read": 6}, 1)) == 6
    assert len(instagram_browse.leads(items, "creator", "creator", set(), {"browse_leads_per_read": 999}, 1)) == 24


def test_browse_reads_one_page_per_interval_and_alternates_creator_and_search(video_store, video_cfg, at, monkeypatch):
    now = at().timestamp()
    cfg = cfg_for(video_cfg)
    grid = {"path": "/creator/reels/", "login": False, "items": [{"href": "/creator/reel/AAAAA1/", "text": "87K"}]}
    calls = safari_page(monkeypatch, grid)
    assert instagram_browse.browse_next(video_store, cfg, now) == "instagram leads read"
    assert calls[0] == ("open", "https://www.instagram.com/creator/reels/") and calls[-1] == ("close",)
    assert instagram_browse.browse_next(video_store, cfg, now + 60) is None          # one page per interval
    row = video_store.rows("SELECT * FROM candidates")[0]
    assert (row["platform"], row["source_id"], row["state"]) == ("instagram", "AAAAA1", "held")
    assert json.loads(video_store.rows("SELECT payload FROM observations")[0]["payload"])["views"] == 87000
    assert not video_store.rows("SELECT * FROM jobs") and not video_store.rows("SELECT * FROM reservations")
    calls.clear()
    assert instagram_browse.browse_next(video_store, cfg, now + 901) == "instagram leads read"
    assert calls[0] == ("open", "https://www.instagram.com/explore/search/keyword/?q=ai%20example%20star%20dance")
    assert ("js", "https://www.instagram.com/explore/search/keyword/") in calls       # confined to that tab


def test_signed_out_instagram_is_not_an_empty_catalog(video_store, video_cfg, at, monkeypatch):
    now = at().timestamp()
    safari_page(monkeypatch, {"path": "/accounts/login/", "login": True, "items": []})
    assert instagram_browse.browse_next(video_store, cfg_for(video_cfg), now) == "instagram page unavailable"
    assert video_store.meta("instagram_browse")["reason"] == "Instagram session is signed out"
    assert video_store.meta("next_instagram_browse") == now + 21600
    assert not video_store.rows("SELECT * FROM candidates")


def test_browse_is_opt_in_and_obeys_the_platform_switch(video_store, video_cfg, at, monkeypatch):
    now = at().timestamp()
    calls = safari_page(monkeypatch, {"items": []})
    assert instagram_browse.browse_next(video_store, cfg_for(video_cfg, safari_browse=False), now) is None
    video_store.set_meta("platform_disabled:instagram", True)
    assert instagram_browse.browse_next(video_store, cfg_for(video_cfg), now) is None
    assert not calls


def test_creator_with_an_inspected_target_parody_joins_the_grid_rotation(video_store, video_cfg, at):
    now = at().timestamp()
    cfg = cfg_for(video_cfg, creators=[])
    for code, creator, review in (("AAAAA1", "found.creator", {"synthetic_parody": True, "cast": ["performer"]}),
                                  ("BBBBB2", "other", {"synthetic_parody": True, "cast": []}),
                                  ("CCCCC3", "real_news", {"synthetic_parody": False, "cast": ["performer"]})):
        connectors.ingest(video_store, "instagram", [{"source_id": code, "creator": creator,
            "canonical_url": "https://www.instagram.com/reel/" + code}], now, cfg)
        row = video_store.rows("SELECT id,document FROM candidates WHERE source_id=?", (code,))[0]
        video_store.save_candidate(row["id"], json.loads(row["document"]) | {"inspection": review}, now, state="held")
    assert instagram_browse.learned_creators(video_store, cfg) == ["found.creator"]
    assert instagram_browse.choose(video_store, cfg, 0)[:2] == ("creator", "found.creator")
    assert instagram_browse.choose(video_store, cfg, 1)[0] == "search"


def reel_payload(now, code, **changes):
    return {"canonical_url": f"https://www.instagram.com/reel/{code}/", "id": code, "published": now - 3600,
            "creator": "creator", "title": "Example Star AI dance", "views": None,
            "stats": {"views": None, "likes": 1200, "duration": 20.5, "bound_code": code},
            "media": ["https://instagram.fxyz1-1.fna.fbcdn.net/o1/v/t2/f2/m86/clip.mp4?token=1"],
            "user_agent": "Fixture Safari"} | changes


def test_reel_is_captured_from_the_redirected_reels_player_and_bound_by_shortcode(video_store, video_cfg, at, monkeypatch):
    """Instagram redirects /reel/ID and /p/ID to /reels/ID: the old read found no tab and no media."""
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"instagram": {"safari_player": True}})
    connectors.ingest(video_store, "instagram", [{"canonical_url": "https://www.instagram.com/p/AAAAA1",
        "source_id": "AAAAA1", "creator": "creator", "permission_id": "grant"}], now, cfg)
    redirected = "https://www.instagram.com/reels/AAAAA1"
    calls = safari_page(monkeypatch, lambda tab: reel_payload(now, "AAAAA1") if tab == redirected else {})
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
    assert ("js", redirected) in calls and all(tab is not None for kind, *rest in calls if kind == "js" for tab in rest)
    row = video_store.rows("SELECT * FROM candidates")[0]
    doc = json.loads(row["document"])
    assert row["state"] == "discovered" and doc["published_at"] == now - 3600
    assert doc["source_download"]["media"] == reel_payload(now, "AAAAA1")["media"]
    assert doc["source_stats"] == {"views": None, "likes": 1200, "observed_at": now}
    assert video_store.rows("SELECT kind,state FROM jobs") == [{"kind": "media", "state": "pending"}]


@pytest.mark.parametrize("change,reason", [
    ({"stats": {"bound_code": "OTHER01"}}, "another reel"),
    ({"canonical_url": "https://www.instagram.com/reel/OTHER01/"}, "canonical identity"),
    ({"media": ["https://evil.test/clip.mp4"]}, "no supported source video"),
    ({"published": ""}, "publication timestamp unavailable")])
def test_reel_capture_fails_closed_on_another_reel_host_or_missing_date(video_store, video_cfg, at, monkeypatch, change, reason):
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"instagram": {"safari_player": True}})
    connectors.ingest(video_store, "instagram", [{"canonical_url": "https://www.instagram.com/reel/AAAAA1",
        "source_id": "AAAAA1", "creator": "creator", "permission_id": "grant"}], now, cfg)
    safari_page(monkeypatch, reel_payload(now, "AAAAA1", **change))
    assert source_browser.capture_next(video_store, cfg, now) == "source player unavailable"
    assert reason in video_store.rows("SELECT reason FROM candidates")[0]["reason"]
    assert not video_store.rows("SELECT * FROM jobs")


def test_search_lead_without_a_target_or_parody_caption_is_refused_once(video_store, video_cfg, at, monkeypatch):
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"instagram": {"safari_player": True}},
                  permissions={"all": {"operator_attested": True, "all_creators": True, "valid_until_revoked": True,
                      "enabled": True, "platforms": ["instagram"], "video": True, "audio": True, "editing": True,
                      "x_publication": True, "overlay_removal": True, "evidence": "fixture attestation"}})
    lead = instagram_browse.leads([{"href": "/p/AAAAA1/", "reel": True}], "search", "ai example star dance", set(), {}, now)
    connectors.ingest(video_store, "instagram", lead, now, cfg)
    calls = safari_page(monkeypatch, reel_payload(now, "AAAAA1", title="my cat on a skateboard"))
    assert source_browser.capture_next(video_store, cfg, now) == "source lead refused"
    row = video_store.rows("SELECT state,reason FROM candidates")[0]
    assert row["state"] == "held" and row["reason"].startswith("lead refused")
    assert not video_store.rows("SELECT * FROM jobs")
    calls.clear()
    assert source_browser.capture_next(video_store, cfg, now + 86400) is None  # a decision, never reopened
    assert not calls


@pytest.mark.parametrize("caption,refused", [("Example Star sings", False), ("示例 跳舞", False),
    ("#AIDance tech titans", False), ("AI科技天团", False), ("deepfake boy band", False), ("my holiday", True)])
def test_search_lead_caption_rule(video_cfg, caption, refused):
    doc = {"title": caption, "discovery_evidence": {"method": instagram_browse.KEYWORD_SEARCH}}
    assert bool(instagram_browse.lead_refusal(doc, video_cfg)) is refused
    assert not instagram_browse.lead_refusal({"title": caption, "discovery_evidence": {"method": instagram_browse.CREATOR_GRID}}, video_cfg)


def test_most_played_unopened_lead_is_captured_first(video_store, video_cfg, at, monkeypatch):
    now = at().timestamp()
    cfg = replace(cfg_for(video_cfg, safari_browse=False), permissions={"grant": video_cfg.permissions["grant"]})
    items = [{"href": "/creator/reel/SMALL01/", "text": "30K"}, {"href": "/creator/reel/HUGE001/", "text": "1.7M"}]
    for lead in instagram_browse.leads(items, "creator", "creator", set(), {}, now):
        connectors.ingest(video_store, "instagram", [lead | {"permission_id": "grant"}], now, cfg)
    calls = safari_page(monkeypatch, reel_payload(now, "HUGE001"))
    source_browser.capture_next(video_store, cfg, now)
    assert calls[0] == ("open", "https://www.instagram.com/reel/HUGE001")


def test_page_script_reads_this_reels_embedded_data_only():
    script = native_source.script("instagram", "AAAAA1")
    assert 'o.code===id&&Array.isArray(o.video_versions)' in script and 'script[type="application/json"]' in script
    assert "fetch(" not in script and "XMLHttpRequest" not in script and "document.cookie" not in script


def test_live_account_browses_instagram_and_pins_its_codex_model():
    from src.video import config
    cfg = config.load()
    options = cfg.platforms["instagram"]
    assert options["safari_browse"] is True and options["browse_queries"] and options["browse_seconds"] >= 300
    # Blank reused REPLY_MODEL; after Replies moved to Grok, Codex refused every inspection.
    assert cfg.codex_model and not cfg.codex_model.startswith("grok")


def test_codex_never_receives_another_providers_reply_model(video_cfg, settings_override):
    from src.video import codex_session
    from src.video.security import AccessError
    settings_override(REPLY_LLM_PROVIDER="grok", REPLY_MODEL="grok-4.7-build-fast")
    with pytest.raises(AccessError, match="codex_model is required"):
        codex_session.model(video_cfg)
    assert codex_session.model(replace(video_cfg, codex_model="pinned-codex-model")) == "pinned-codex-model"
    settings_override(REPLY_LLM_PROVIDER="codex", REPLY_MODEL="gpt-6.1-sol")
    assert codex_session.model(video_cfg) == "gpt-6.1-sol"


# --- 2026-11-23: an audience proves the banger; floors are the Operator's settings ---

@pytest.mark.parametrize("plays,likes,refused", [(1_700_000, 100, False), (None, 5000, False), (10_000, 5000, False),
    (10_000, 100, True), (None, 100, True), (10_000, None, True), (None, None, False)])
def test_reel_needs_plays_or_likes_when_either_is_known(video_cfg, plays, likes, refused):
    cfg = replace(video_cfg, audience_min_views=50000, audience_min_likes=2000)
    doc = {"title": "Example Star AI song", "discovery_evidence": {"method": instagram_browse.CREATOR_GRID, "views": plays},
           "source_stats": {"likes": likes}}
    assert bool(instagram_browse.lead_refusal(doc, cfg)) is refused
    assert not instagram_browse.lead_refusal(doc, video_cfg)  # other Accounts keep no audience floor


def review(**scores):
    base = {"hook_payoff": 6, "performance": 6.5, "fit": 8, "quality": 6.5, "novelty": 3}
    return {"banger_scores": base | scores, "brand_fit": True, "language_dependent": False, "banger_reason": "fixture",
            "fit_score": 16, "entertainment_score": 13, "quality_score": 10}


def test_banger_floors_are_settings_with_the_strict_defaults(video_cfg):
    from src.video import bangers, editing
    strict = replace(video_cfg, bangers_only=True, auto_edit=True)
    calibrated = replace(strict, banger_component_min=5.5, banger_fit_min=7, banger_floors=(14, 12, 9))
    assert "8/10" in editing.banger_refusal(review(), strict)
    assert editing.banger_refusal(review(), calibrated) == ""
    assert "fit 7/10" in editing.banger_refusal(review(fit=6.5), calibrated)
    assert "5.5/10" in editing.banger_refusal(review(performance=5), calibrated)
    assert editing.banger_refusal(review() | {"quality_score": 8.5}, calibrated) == "performance does not meet banger quality floors"
    assert editing.banger_refusal(review() | {"brand_fit": False}, calibrated) == "brand fit or non-hostile parody unverified"
    assert bangers.review_refusal(review()) and not bangers.review_refusal(review(), calibrated)


@pytest.mark.parametrize("change", [{"banger_component_min": 4.9}, {"banger_fit_min": 11}, {"banger_floors": (11, 12, 9)},
    {"banger_floors": (14, 12)}, {"banger_min_score": 59}, {"min_hook_score": 4}, {"audience_min_views": -1},
    {"editorial_taste": "x" * 1501}])
def test_floors_cannot_be_configured_below_their_bounds(video_cfg, change):
    with pytest.raises(ValueError):
        replace(video_cfg, **change)


def test_operator_taste_and_floors_rebind_the_editing_policy(video_cfg):
    from src.video import editing
    before = editing.policy_revision(video_cfg)
    assert editing.policy_revision(replace(video_cfg, editorial_taste="Example Star must look good")) != before
    assert editing.policy_revision(replace(video_cfg, banger_fit_min=7)) != before


def subtitles(band_y, frames=range(0, 20)):
    return [{"at": at, "texts": [{"box": [0.3, band_y, 0.4, 0.05], "confidence": 1, "text": "lyric line"}]} for at in frames]


def test_handle_is_never_stamped_over_measured_source_subtitles():
    """2026-11-23: '@handle' was rendered across every bottom lyric line of a rendered reel."""
    from src.video.inspection import clear_watermark_position as place
    assert place({"watermark_position": "bottom", "ocr_evidence": subtitles(0.89)}) == "top"
    assert place({"watermark_position": "top", "ocr_evidence": subtitles(0.05)}) == "bottom"
    assert place({"watermark_position": "bottom", "ocr_evidence": subtitles(0.5)}) == "bottom"      # mid-frame text
    assert place({"watermark_position": "top", "ocr_evidence": []}) == "top"                         # model's action call kept
    assert place({"watermark_position": "bottom", "ocr_evidence": subtitles(0.89) + subtitles(0.05)}) == "bottom"
    # only the proposed cut counts: subtitles outside it do not move the handle
    cut = {"start_seconds": 10, "end_seconds": 19}
    assert place({"watermark_position": "bottom", "edit": cut, "ocr_evidence": subtitles(0.89, range(0, 9))}) == "bottom"
    corner = [{"at": 1, "texts": [{"box": [0.02, 0.9, 0.1, 0.05], "confidence": 1, "text": "logo"}]}]
    assert place({"watermark_position": "bottom", "ocr_evidence": corner}) == "bottom"              # clear of the centre stamp
    assert place({"watermark_position": None}) is None


def test_both_retained_overlay_match_paths_survive_a_cut_offset():
    """2026-11-23: the exact same-sample match has no `source_at`; a cut clip with subtitles raised KeyError."""
    from src.video.inspection import source_time
    assert source_time({"method": "same_sample_pixels", "source_sample_at": 3}, 2)["source_sample_at"] == 5
    assert source_time({"method": "native_frame_pixels", "source_at": 3.5}, 2)["source_at"] == 5.5


def test_post_only_start_keeps_the_video_job_and_drops_replies(settings_override, promotion_account):
    """Operator, 2026-11-23: videos only while away."""
    import main
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True, REPLY_REVIEW_ONLY=False,
                      VIDEO_ENABLED=True, VIDEO_LIVE=True, VIDEO_WITH_REPLIES=True)
    assert [job.id for job in main.build_scheduler(post_only=True).get_jobs()] == ["video_health_job"]


def test_creator_of_a_big_reel_joins_the_rotation_before_any_inspection(video_store, video_cfg, at):
    """2026-11-24: 258K-like search finds were captured once and their creators never read again."""
    now = at().timestamp()
    cfg = replace(cfg_for(video_cfg, creators=[]), audience_min_likes=2000)
    for code, creator, likes, reason in (("AAAAA1", "big.creator", 258000, ""), ("BBBBB2", "small", 3000, ""),
                                         ("CCCCC3", "off.topic", 90000, "lead refused: caption")):
        connectors.ingest(video_store, "instagram", [{"source_id": code, "creator": creator,
            "canonical_url": "https://www.instagram.com/reel/" + code}], now, cfg)
        row = video_store.rows("SELECT id,document FROM candidates WHERE source_id=?", (code,))[0]
        video_store.save_candidate(row["id"], json.loads(row["document"]) | {"source_stats": {"likes": likes}}, now,
                                   state="held", reason=reason)
    assert instagram_browse.learned_creators(video_store, cfg) == ["big.creator"]
    assert instagram_browse.learned_creators(video_store, replace(cfg, audience_min_likes=0)) == []


def test_capture_reopens_a_source_tab_that_vanished_and_names_a_page_that_never_stays(video_store, video_cfg, at, monkeypatch):
    """2026-11-24: beside Replies the reel tab was gone on every poll; twelve reels ended in a bare ValueError."""
    from src.x import safari, safari_video
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"instagram": {"safari_player": True}})
    connectors.ingest(video_store, "instagram", [{"canonical_url": "https://www.instagram.com/reel/AAAAA1",
        "source_id": "AAAAA1", "creator": "creator", "permission_id": "grant"}], now, cfg)
    opens = []
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda url: opens.append(url) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(native_source.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(safari, "_run_js", lambda js, **kw: json.dumps(reel_payload(now, "AAAAA1"))
                        if len(opens) == 2 and kw.get("target_url", "").endswith("/reels/AAAAA1") else "")
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
    assert len(opens) == 2
    connectors.ingest(video_store, "instagram", [{"canonical_url": "https://www.instagram.com/reel/BBBBB2",
        "source_id": "BBBBB2", "creator": "creator", "permission_id": "grant"}], now, cfg)
    opens.clear()
    monkeypatch.setattr(safari, "_run_js", lambda js, **kw: "missing value")
    assert source_browser.capture_next(video_store, cfg, now + 120) == "source player unavailable"
    assert len(opens) == 3   # the first open and two more, never an endless loop
    assert "did not stay open" in video_store.rows("SELECT reason FROM candidates WHERE source_id='BBBBB2'")[0]["reason"]


def test_capture_follows_a_redirect_that_happens_after_the_first_answer(video_store, video_cfg, at, monkeypatch):
    """2026-11-24, the real cause: /reel/ID answered once without media, Instagram moved the tab to
    /reels/ID, and the read kept asking the old address until it gave up."""
    from src.x import safari, safari_video
    now = at().timestamp()
    cfg = replace(video_cfg, platforms={"instagram": {"safari_player": True}})
    connectors.ingest(video_store, "instagram", [{"canonical_url": "https://www.instagram.com/reel/AAAAA1",
        "source_id": "AAAAA1", "creator": "creator", "permission_id": "grant"}], now, cfg)
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda url: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(native_source.time, "sleep", lambda seconds: None)
    polls = []
    def page(js, **kw):
        tab = kw.get("target_url", "")
        polls.append(tab)
        if len(polls) == 2 and tab.endswith("/reel/AAAAA1"):      # before the redirect: shell only
            return json.dumps(reel_payload(now, "AAAAA1", media=[], published=None))
        if len(polls) > 2 and tab.endswith("/reels/AAAAA1"):      # after it
            return json.dumps(reel_payload(now, "AAAAA1"))
        return ""
    monkeypatch.setattr(safari, "_run_js", page)
    assert source_browser.capture_next(video_store, cfg, now) == "source media captured"
