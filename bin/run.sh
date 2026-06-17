#!/usr/bin/env bash
# Run the @CryptoAIDecode bot in the FOREGROUND of this terminal.
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

# Pre-warm the local LLM and pin it in memory for 24h. Cold-loading the
# ~23GB model takes ~170s — longer than the bot's per-call timeout. Use
# OLLAMA_MODEL from .env so a model swap auto-warms the right one.
if command -v curl >/dev/null 2>&1; then
  OLLAMA_MODEL_NAME="${OLLAMA_MODEL:-fredrezones55/qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive}"
  echo "[run] Pre-warming $OLLAMA_MODEL_NAME (keep_alive=24h)..."
  # think:false matches the bot's runtime payload (qwen3.6 uncensored is a
  # thinking-mode model — without this it leaks tokens into a separate
  # `thinking` field and `response` stays empty).
  curl -fsS --max-time 300 http://localhost:11434/api/generate \
    -d "{\"model\":\"$OLLAMA_MODEL_NAME\",\"prompt\":\"ok\",\"stream\":false,\"think\":false,\"keep_alive\":\"24h\"}" \
    >/dev/null 2>&1 && echo "[run] Model warm." || echo "[run] Pre-warm failed (model not pulled yet? ollama not running?). Bot will warm on first call."
fi

# Clear stale bytecode so code changes take effect immediately.
find "$REPO_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# --- Claude self-improvement loop (operator 2026-06-17: "bring back the
# self-improvement loop using claude... part of my script ./bin/run.sh").
# Periodically runs a headless Claude session (bin/auto_improve.sh) that
# diagnoses the engine and ships ONE tested improvement via PR. Backgrounded
# here so it lives as long as the bot runs and dies with it (trap below).
# Env: ENABLE_SELF_IMPROVE_LOOP (default 1), SELF_IMPROVE_INTERVAL_HOURS
# (default 8), SELF_IMPROVE_WARMUP_SECONDS (default 1800 — first run after
# the bot settles). auto_improve.sh's own single-flight lock keeps it from
# colliding with the daily launchd agent if that's also loaded.
SELF_IMPROVE_PID=""
if [ "${ENABLE_SELF_IMPROVE_LOOP:-1}" = "1" ] && command -v claude >/dev/null 2>&1; then
  _si_interval="${SELF_IMPROVE_INTERVAL_HOURS:-8}"
  _si_warmup="${SELF_IMPROVE_WARMUP_SECONDS:-1800}"
  echo "[run] Claude self-improvement loop ON — first run in $((_si_warmup/60))m, then every ${_si_interval}h."
  (
    sleep "$_si_warmup"
    while true; do
      echo "[run] $(date '+%F %T') launching self-improvement run..." >> "$REPO_DIR/auto_improve.log"
      "$REPO_DIR/bin/auto_improve.sh" >> "$REPO_DIR/auto_improve.log" 2>&1 || true
      sleep "$(( _si_interval * 3600 ))"
    done
  ) &
  SELF_IMPROVE_PID=$!
else
  echo "[run] Self-improvement loop OFF (ENABLE_SELF_IMPROVE_LOOP=0 or 'claude' CLI not found)."
fi

# Clean up the background loop (and any in-flight improve run) when the bot
# stops — Ctrl-C, SIGTERM, or normal exit.
_cleanup() {
  [ -n "${SELF_IMPROVE_PID:-}" ] && kill "$SELF_IMPROVE_PID" 2>/dev/null || true
  pkill -f "bin/auto_improve.sh" 2>/dev/null || true
}
trap _cleanup EXIT INT TERM

echo "[run] Starting @CryptoAIDecode bot. Press Ctrl-C to stop."
echo "[run] Logs also stream to bot.log (tail -F bot.log)."
echo "────────────────────────────────────────"

# Foreground execution via uv so dependencies come from the project env.
# Output to terminal AND tee'd to bot.log so the existing log-tail flow works.
# (No `exec` — the script stays alive so the cleanup trap fires on Ctrl-C.)
uv run python main.py 2>&1 | tee -a "$REPO_DIR/bot.log"
