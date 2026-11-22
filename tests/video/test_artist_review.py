"""Music-video samples retain bounded reads and evidence across the whole clip."""
from types import SimpleNamespace
import time

from src.video import artist_review, codex_session, config, repost_review, store


def test_four_minute_artist_clip_requires_observations_from_each_third(monkeypatch, settings_override):
    settings_override(REPLY_CURATED_MODE=True)
    monkeypatch.setenv("DRY_RUN", "0")
    page = dict(url="https://x.com/artist/status/2123756970683338992", text="My new AI slopcore film", media_id="123")
    frames = [dict(at=7.5+i*15, sha256="a"*64, path="unused.png") for i in range(16)]
    calls = []
    def capture(source, folder, *, max_seconds):
        calls.append(max_seconds)
        return 240, frames
    monkeypatch.setattr(repost_review, "_capture", capture)
    monkeypatch.setattr(repost_review, "_sheets", lambda *a: ["contact-sheet.png"])
    monkeypatch.setattr(config, "load", lambda: SimpleNamespace(request_budget=100, publishing_request_reserve=10))
    monkeypatch.setattr(store, "Store", lambda: SimpleNamespace(budget=lambda *a: True))
    def review(store, cfg, prompt, schema, **kwargs):
        props = schema["properties"]
        assert max(props["opening"]["properties"]["at"]["enum"]) < 80
        assert min(props["middle"]["properties"]["at"]["enum"]) >= 80
        assert min(props["ending"]["properties"]["at"]["enum"]) >= 160
        assert kwargs["images"] == ["contact-sheet.png"]
        verdict = dict(approved=True, ai_related=True, artist_work=True, style_fit=True, safe=True,
                       all_samples_reviewed=True, needs_unavailable_audio=False, quality=9, reason="Visual concept holds")
        for name in ("opening", "middle", "ending"):
            verdict[name] = dict(at=props[name]["properties"]["at"]["enum"][-1], observation="A new visual composition")
        return verdict, {"id": "isolated-review"}
    monkeypatch.setattr(codex_session, "call", review)
    evidence = artist_review.inspect(page, {"bio": "AI artist"})
    assert calls == [300]
    assert artist_review.valid(evidence, page["url"], page["text"], "123")
    evidence["verdict"]["observations"][-1]["at"] = 142.5
    assert not artist_review.valid(evidence, page["url"], page["text"], "123")


def test_exhausted_browser_budget_never_starts_sampling(monkeypatch, settings_override):
    import pytest
    from src.video.security import Deferred
    settings_override(REPLY_CURATED_MODE=True)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(config, "load", lambda: SimpleNamespace(request_budget=100, publishing_request_reserve=10))
    monkeypatch.setattr(store, "Store", lambda: SimpleNamespace(budget=lambda *a: False))
    monkeypatch.setattr(repost_review, "_capture", lambda *a, **k: pytest.fail("sampled after budget exhausted"))
    with pytest.raises(Deferred):
        artist_review.inspect({}, {})
