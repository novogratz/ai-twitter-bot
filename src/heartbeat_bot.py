"""Heartbeat tick — proves the bot is alive even between cycles.

When the bot is fully autonomous, the user has no terminal session to
watch. They might glance at bot.log once a day. If 30 min pass without
ANY log line because all 28 schedulers are mid-sleep, that looks like
a hang. This bot writes one log line every 60s — a cheap alive signal.

Also doubles as a write to autonomous_log.md (the audit trail of what
the bot has been doing while running unattended).
"""
import os
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT
from .logger import log

AUTONOMOUS_LOG = os.path.join(_PROJECT_ROOT, "autonomous_log.md")


def run_heartbeat():
    log.info(f"[HEARTBEAT] alive {datetime.now().strftime('%H:%M:%S')}")


def safe_run_heartbeat():
    try:
        run_heartbeat()
    except Exception:
        log.info("[HEARTBEAT] error:")
        traceback.print_exc()
