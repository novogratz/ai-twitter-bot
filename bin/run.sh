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

if [[ -f "$REPO_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_DIR/.env"
  set +a
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

# Pre-warm the local LLMs and pin them in memory for 24h. Cold-loading these
# models can exceed per-call timeouts. OLLAMA_MODEL drives profile/original
# posts; OLLAMA_REPLY_MODEL optionally overrides replies only.
if command -v curl >/dev/null 2>&1; then
  OLLAMA_MODEL_NAME="${OLLAMA_MODEL:-orcarouter/Qwen3.8-27B-Uncensored}"
  OLLAMA_REPLY_MODEL_NAME="${OLLAMA_REPLY_MODEL:-}"
  _models=("$OLLAMA_MODEL_NAME")
  if [[ -n "$OLLAMA_REPLY_MODEL_NAME" && "$OLLAMA_REPLY_MODEL_NAME" != "$OLLAMA_MODEL_NAME" ]]; then
    _models+=("$OLLAMA_REPLY_MODEL_NAME")
  fi
  for _model in "${_models[@]}"; do
    echo "[run] Pre-warming $_model (keep_alive=24h)..."
    if ! curl -fsS --max-time 300 http://localhost:11434/api/generate \
      -d "{\"model\":\"$_model\",\"prompt\":\"ok\",\"stream\":false,\"think\":false,\"keep_alive\":\"24h\"}" \
      >/dev/null 2>&1; then
      echo "[run] Pre-warm failed for $_model. Refusing to start with any other model."
      exit 1
    fi
    echo "[run] Model warm: $_model"
  done
fi

# Clear stale bytecode so code changes take effect immediately.
find "$REPO_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "[run] Starting @TheAIShrink bot. Press Ctrl-C to stop."
echo "[run] Logs also stream to bot.log (tail -F bot.log)."
echo "────────────────────────────────────────"

# Foreground execution via uv so dependencies come from the project env.
# Output to terminal AND tee'd to bot.log so the existing log-tail flow works.
exec uv run python main.py 2>&1 | tee -a "$REPO_DIR/bot.log"
