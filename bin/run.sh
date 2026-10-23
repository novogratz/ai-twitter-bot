#!/usr/bin/env bash
# Run the @TheAIShrink bot in the FOREGROUND of this terminal.
#
# Press Ctrl-C to stop it cleanly (graceful shutdown via SIGTERM).
# Close the terminal → bot stops too. Manual control, no system service.
#
# NO self-improvement loop (operator 2026-06-21: "disactivate the self
# improvement stuff, keep it static"). This script ONLY runs the bot — no
# headless Claude auto_improve, no autonomous code edits. auto_improve.sh is
# gated off and the launchd agent is disabled.

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

# Pre-warm the local LLM and pin it in memory for 24h. Cold-loading the
# ~23GB model takes ~170s — longer than the bot's per-call timeout. The model
# and endpoint are the bot's own, OLLAMA_MODEL and OLLAMA_BASE_URL as
# src/core/settings.py resolves them from .env, so a model swap auto-warms
# the right one.
if command -v curl >/dev/null 2>&1 && OLLAMA_TARGET="$(uv run python -c '
import sys
from src.core import settings
from src.guards.active_hours import is_active
if not is_active():
    sys.exit(1)
print(settings.get("OLLAMA_BASE_URL"), settings.get("OLLAMA_MODEL"))')"; then
  read -r OLLAMA_URL OLLAMA_MODEL_NAME <<< "$OLLAMA_TARGET"
  echo "[run] Pre-warming $OLLAMA_MODEL_NAME (keep_alive=24h)..."
  curl -fsS --max-time 300 "$OLLAMA_URL/api/generate" \
    -d "{\"model\":\"$OLLAMA_MODEL_NAME\",\"prompt\":\"ok\",\"stream\":false,\"think\":false,\"keep_alive\":\"24h\"}" \
    >/dev/null 2>&1 && echo "[run] Model warm." || echo "[run] Pre-warm failed (model not pulled yet? ollama not running?). Bot will warm on first call."
fi

# Clear stale bytecode so code changes take effect immediately.
find "$REPO_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "[run] Starting @TheAIShrink bot. Press Ctrl-C to stop."
echo "[run] Logs also stream to bot.log (tail -F bot.log)."
echo "────────────────────────────────────────"

# Foreground execution via uv so dependencies come from the project env.
# Output to terminal AND tee'd to bot.log so the existing log-tail flow works.
exec uv run python main.py 2>&1 | tee -a "$REPO_DIR/bot.log"
