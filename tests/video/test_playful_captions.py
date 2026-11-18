from dataclasses import replace

import pytest

from src.video import editing, inspection, ranking, schedule


def playful(video_cfg):
    return replace(video_cfg, playful_caption=True, caption_disclosure=False,
                   targets={"performer": ["Example Star", "Example"]})


def test_reviewed_scene_and_signoff_keep_real_blank_line(ready, video_cfg, at):
    doc, cfg = ready(), playful(video_cfg)
    text = "Example turned the meeting into a dance break 😭💀\n\nAbsolute BANGER 🔥"
    doc["inspection"]["caption"] = text
    doc["qc"]["caption_accurate"] = True
    assert ranking.caption(doc, cfg, at().timestamp()) == text
    assert "caption" in inspection.schema(cfg, "source")["required"]
    assert "caption_accurate" in inspection.schema(cfg, "output")["required"]


@pytest.mark.parametrize("failure", ["unreviewed", "unattributed", "three_paragraphs", "link", "hashtag"])
def test_caption_cannot_bypass_cast_review_or_format(ready, video_cfg, at, failure):
    doc, cfg = ready(), playful(video_cfg)
    text = "Example turned the meeting into a dance break 😭💀\n\nAbsolute BANGER 🔥"
    doc["qc"]["caption_accurate"] = failure != "unreviewed"
    if failure == "unattributed":
        text = text.replace("Example", "SomeoneElse")
    elif failure == "three_paragraphs":
        text += "\n\nAnother line"
    elif failure == "link":
        text += " https://example.com"
    elif failure == "hashtag":
        text += " #viral"
    doc["inspection"]["caption"] = text
    with pytest.raises(ValueError):
        ranking.caption(doc, cfg, at().timestamp())


def test_playful_caption_policy_invalidates_cached_edit_review(video_cfg):
    assert editing.policy_revision(playful(video_cfg)) != editing.policy_revision(video_cfg)
    with pytest.raises(ValueError):
        replace(video_cfg, one_line_caption=True, playful_caption=True)


def test_four_daily_video_windows_and_target(video_cfg):
    cfg = replace(video_cfg, windows=("08:30", "12:30", "17:30", "21:30"),
                  paired_windows=(), scheduled_daily_cap=4, daily_target_min=3)
    assert schedule.clocks(cfg) == cfg.windows
    with pytest.raises(ValueError):
        replace(cfg, daily_target_min=5)
    with pytest.raises(ValueError):
        schedule.clocks(replace(cfg, windows=()))
