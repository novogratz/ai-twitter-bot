"""src/core/config: hard ceilings a live strategy file cannot lift."""
import json

from src.core import config


def test_stale_strategy_cannot_restore_quotes_or_raise_post_ceiling(monkeypatch, tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps({"caps": {"MAX_QUOTES_PER_DAY": 999,
                                          "MAX_ORIGINALS_PER_DAY": 999,
                                          "MAX_REPLIES_PER_DAY": 4}}))
    monkeypatch.setattr(config, "_LIVE_STRATEGY_FILE", str(path))
    assert config.get_live_cap("MAX_QUOTES_PER_DAY", 100) == 0
    assert config.get_live_cap("MAX_ORIGINALS_PER_DAY", 100) <= 8
    assert config.get_live_cap("MAX_REPLIES_PER_DAY", 100) == 0
