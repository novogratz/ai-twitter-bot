#!/usr/bin/env bash
# 2026-11-08: no automatic startup post. News is off; only ultra-qualified videos.
# The existing video publisher can post exceptional finds after all checks pass.
# Startup requests are an explicit opt-in and cannot enable disabled features.
STARTUP_PUBLICATIONS="${STARTUP_PUBLICATIONS:-0}"
# Run the configured Account's bot in the FOREGROUND of this terminal.
#
# Press Ctrl-C to stop it cleanly (graceful shutdown via SIGTERM).
# Close the terminal → bot stops too. Manual control, no system service.
#
# NO self-improvement loop (operator 2026-06-21: "disactivate the self
# improvement stuff, keep it static"). This script ONLY runs the bot — no
# headless Claude auto_improve, no autonomous code edits. auto_improve.sh is
# gated off and the launchd agent is disabled.

set -euo pipefail
case "$STARTUP_PUBLICATIONS" in
  0|1) ;;
  *) echo "[run] STARTUP_PUBLICATIONS must be 0 or 1." >&2; exit 2 ;;
esac

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Resolve startup settings before touching a running process. A bad .env
# must fail visibly, not be mistaken for disabled video support.
RUN_CONFIG="$(uv run --with-requirements requirements.txt python -c '
from src.core import config, settings
print(config.BOT_HANDLE, int(settings.get("VIDEO_ENABLED")))')"
read -r RUN_HANDLE RUN_VIDEO_ENABLED <<< "$RUN_CONFIG"
REQUIREMENTS_FILE=requirements.txt
if [[ "$RUN_VIDEO_ENABLED" == "1" ]]; then
  REQUIREMENTS_FILE=requirements-video.txt
fi

# Make sure no other instance is already running (would race on Safari).
if pgrep -f "python.*main.py" >/dev/null; then
  echo "[run] Another bot is already running. Stopping it first..."
  pkill -TERM -f "python.*main.py" || true
  sleep 2
  if pgrep -f "python.*main.py" >/dev/null; then
    pkill -KILL -f "python.*main.py" || true
    sleep 1
  fi
fi

# Clear stale bytecode so code changes take effect immediately.
find "$REPO_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "[run] Starting @$RUN_HANDLE bot. Press Ctrl-C to stop."
set --
if [[ "$STARTUP_PUBLICATIONS" == "1" ]]; then
  set -- --startup-publications
  echo "[run] Startup: news + video requested first; actual receipts confirm publication."
fi
echo "[run] Logs are also written to bot.log (tail -F bot.log)."
echo "────────────────────────────────────────"

# Keep the terminal attached: the logger owns both console output and bot.log.
# A scalar requirements path also works with Bash 3.2's nounset handling.
exec uv run --with-requirements "$REQUIREMENTS_FILE" python -u main.py "$@"
