"""Operator, 2026-11-25: no account watermark on any video the bot posts."""
from dataclasses import replace

from src.video import config, inspection, ranking


def test_live_account_stamps_nothing_and_still_refuses_foreign_marks():
    cfg = config.load()
    assert cfg.stamp_watermark is False and cfg.clean_watermarks_only and cfg.remove_source_logos


def test_output_gate_wants_no_watermark_at_all_when_stamping_is_off(ready, video_cfg):
    doc = ready()
    assert not ranking.output_gate(doc, video_cfg)                       # stamped Accounts: unchanged
    off = replace(video_cfg, stamp_watermark=False)
    assert "rendered again" in ranking.output_gate(doc, off)             # an older stamped render is held
    doc["qc"]["watermark_present"] = False
    assert not ranking.output_gate(doc, off)
    assert "uncertain" in ranking.output_gate(doc, video_cfg)            # and a stamped Account still needs its mark


def test_render_draws_no_overlay_and_needs_no_placement_when_stamping_is_off():
    import inspect
    from src.video import media
    source = inspect.getsource(media.render)
    assert "if stamping else" in source and "if stamping and (not cfg.watermark" in source


def test_inspector_is_told_and_the_output_review_is_cached_apart(video_cfg):
    assert "no mark at all" in inspection.NO_STAMP
