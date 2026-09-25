"""src/core measurement and state stores: history, engagement log, JSON
safety, Safari health counter."""
import json
import os

from src.core import config
from src.guards import replied_store as rs


def test_save_tweet_idempotent():
    import src.core.history as history
    history.save_tweet("same text")
    history.save_tweet("same text")
    assert len(history.load_history()) == 1


def test_json_safety_strips_lone_surrogates_before_utf8_write(tmp_path):
    from src.core.json_safety import sanitize_for_json

    payload = {
        "items": [{
            "title": "AI math \ud835 signal",
            "url": "https://x.com/u/status/1",
        }]
    }
    safe = sanitize_for_json(payload)
    assert "\ud835" not in safe["items"][0]["title"]

    out = tmp_path / "signal.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2, ensure_ascii=False)
    assert "AI math  signal" in out.read_text(encoding="utf-8")


def test_engagement_log_records_the_provider_and_model_it_is_given(monkeypatch, settings_override, tmp_path):
    """Issue #176: a row carries the provider and model that wrote the
    text, as the caller passes them from the model's answer. The configured
    provider is no guess at it: the Replies force their own, and a fallback
    answers under another."""
    import csv
    from src.core import engagement_log as el
    p = tmp_path / "engagement_log.csv"
    monkeypatch.setattr(el, "ENGAGEMENT_LOG_FILE", str(p))
    settings_override(AI_CLI="claude", PROFILE_LLM_PROVIDER="gemini")
    el.log_reply("https://x.com/someone/status/123", "test reply", "reply", source="TEST",
                 provider="codex", model="gpt-5.4-mini")
    rows = list(csv.reader(open(p)))
    assert rows[0][-2:] == ["provider", "model"]
    assert rows[1][7:] == ["codex", "gpt-5.4-mini"]


def test_unreadable_state_never_restarts_safari(monkeypatch, tmp_path):
    from src.core import health
    restarts = []
    monkeypatch.setattr(health, "_restart_safari", lambda: restarts.append(1) or True)
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        try:
            rs.load_replied()
        except Exception:
            assert health.record_failure("direct_reply") is False
    assert restarts == [], "a corrupt store is not a Safari failure"
    assert not os.path.exists(health.HEALTH.path), "the failure counter is left alone"
