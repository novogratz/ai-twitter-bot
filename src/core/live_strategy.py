"""live_strategy.json, read by config.get_live_*.

Declared here rather than in config: state_store imports config.
"""
from .state_store import DISPOSABLE, StateFile

# Disposable: the fixed ceilings in config apply whatever the file holds.
LIVE_STRATEGY = StateFile("live_strategy.json", {}, DISPOSABLE)
