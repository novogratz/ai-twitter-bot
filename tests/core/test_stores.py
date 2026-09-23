"""src/core measurement and state stores: history, engagement log, JSON
safety, Safari health counter."""
import json
import os

import pytest

from src.core import config
from src.guards import replied_store as rs


@pytest.mark.usefixtures("isolate_dedup")
def test_save_tweet_idempotent(monkeypatch, tmp_path):
    import src.core.history as history
    import src.core.config as config
    hist_file = str(tmp_path / "hist.json")
    monkeypatch.setattr(history, "HISTORY_FILE", hist_file)
    history.save_tweet("same text")
    history.save_tweet("same text")
    assert len(history.load_history()) == 1


@pytest.mark.usefixtures("isolate_dedup")
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


@pytest.mark.usefixtures("isolate_dedup")
def test_engagement_log_records_provider_column(monkeypatch, tmp_path):
    """2026-07-19 (all-ollama switch): every engagement_log row must carry
    the provider configured for its surface at write time, so provider
    switches are judged on likes-per-post data instead of vibes. Profile
    surfaces tag PROFILE_LLM_PROVIDER; replies tag the AI_CLI default."""
    import csv
    from src.core import engagement_log as el
    p = tmp_path / "engagement_log.csv"
    monkeypatch.setattr(el, "ENGAGEMENT_LOG_FILE", str(p))
    monkeypatch.setenv("PROFILE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AI_CLI", "codex")
    el.log_post("test post", source="TEST")
    el.log_reply("https://x.com/someone/status/123", "test reply", "reply", source="TEST")
    rows = list(csv.reader(open(p)))
    assert rows[0][-1] == "provider"
    post_row = next(r for r in rows[1:] if r[1] == "post")
    reply_row = next(r for r in rows[1:] if r[1] == "reply")
    assert post_row[7] == "ollama", "profile surface must tag PROFILE_LLM_PROVIDER"
    assert reply_row[7] == "codex", "reply surface must tag the AI_CLI default"


def test_unreadable_state_never_restarts_safari(monkeypatch, tmp_path):
    from src.core import health
    monkeypatch.setattr(health, "HEALTH_FILE", str(tmp_path / "safari_health.json"))
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
    assert not os.path.exists(health.HEALTH_FILE), "the failure counter is left alone"
