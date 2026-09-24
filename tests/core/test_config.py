"""src/core/config: hard ceilings a live strategy file cannot lift."""
import json

from src.core import config


def test_stale_strategy_cannot_restore_quotes_or_raise_post_ceiling(monkeypatch, tmp_path):
    path = tmp_path / "live_strategy.json"
    path.write_text(json.dumps({"caps": {"MAX_QUOTES_PER_DAY": 999,
                                          "MAX_ORIGINALS_PER_DAY": 999,
                                          "MAX_REPLIES_PER_DAY": 4}}))
    assert config.get_live_cap("MAX_QUOTES_PER_DAY", 100) == 0
    assert config.get_live_cap("MAX_ORIGINALS_PER_DAY", 100) <= 8
    assert config.get_live_cap("MAX_REPLIES_PER_DAY", 100) == 0


def test_post_spacing_floor_is_twenty_minutes():
    """2026-09-23: 09:30 and 10:00 sit thirty minutes apart and the Startup
    post can land next to any Slot; `.env` may lengthen the gap, never
    shorten it below twenty minutes."""
    import os
    import subprocess
    import sys
    code = "from src.core import config; print(config.MIN_SECONDS_BETWEEN_POSTS)"
    def floor(value):
        env = {**os.environ, "MIN_SECONDS_BETWEEN_POSTS": value}
        out = subprocess.run([sys.executable, "-c", code], env=env, check=True,
                             capture_output=True, text=True, cwd=config._PROJECT_ROOT)
        return int(out.stdout.strip().splitlines()[-1])
    assert floor("60") == 1200
    assert floor("3600") == 3600
