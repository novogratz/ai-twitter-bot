#!/usr/bin/env bash
# Stop the @kzer_ai bot cleanly.

set -euo pipefail

if pgrep -f "python.*main.py" >/dev/null; then
  echo "[stop] Sending SIGTERM..."
  pkill -TERM -f "python.*main.py" || true
  sleep 3
  if pgrep -f "python.*main.py" >/dev/null; then
    echo "[stop] Forcing remaining processes..."
    pkill -KILL -f "python.*main.py" || true
    sleep 1
  fi
  echo "[stop] Bot stopped."
else
  echo "[stop] No bot process running."
fi
