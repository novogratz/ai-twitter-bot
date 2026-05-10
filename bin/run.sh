#!/usr/bin/env bash
# Run the @kzer_ai bot in the FOREGROUND of this terminal.
#
# Press Ctrl-C to stop it cleanly (graceful shutdown via SIGTERM).
# Close the terminal → bot stops too. Manual control, no system service.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

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

echo "[run] Starting @kzer_ai bot. Press Ctrl-C to stop."
echo "[run] Logs also stream to bot.log (tail -F bot.log)."
echo "────────────────────────────────────────"

# Foreground execution. Output to terminal AND tee'd to bot.log so the
# existing log-tail flow works.
exec "$REPO_DIR/.venv/bin/python3" main.py 2>&1 | tee -a "$REPO_DIR/bot.log"
