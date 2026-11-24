#!/bin/bash
# Lightweight bot watchdog — runs every 5 minutes via launchd.
# If `uv run python main.py` is dead, restart it. No Claude calls, no AI cost.
# This guarantees the bot is never dark for more than ~5 minutes.

set -euo pipefail

PROJECT_DIR="$HOME/ai-twitter-bot"
LOG_FILE="/tmp/kzer_watchdog.log"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

# AI_CLI and the model settings keep the defaults of src/core/settings.py.
export QUOTE_MODEL="${QUOTE_MODEL:-gpt-5.4-mini}"
export ROAST_MODEL="${ROAST_MODEL:-gpt-5.4-mini}"
export LLM_MIN_SECONDS_BETWEEN_CALLS="${LLM_MIN_SECONDS_BETWEEN_CALLS:-900}"
export LLM_MAX_CALLS_PER_HOUR="${LLM_MAX_CALLS_PER_HOUR:-4}"
export LLM_MAX_CALLS_PER_DAY="${LLM_MAX_CALLS_PER_DAY:-20}"

# Manual kill-switch: if /stop (or the user) created .bot_disabled, do
# NOT restart. Otherwise the watchdog defeats /stop within 5 minutes.
# /start removes this file before launching.
if [ -f "$PROJECT_DIR/.bot_disabled" ]; then
    exit 0
fi

# Check for live bot process (case-insensitive: macOS framework Python
# shows as `Python main.py` with a capital P, so plain `pgrep -f` misses it).
if pgrep -if "(uv run python|python).*main\.py" > /dev/null 2>&1; then
    # Alive — silent success (don't fill the log).
    exit 0
fi

# Dead. Restart. Do not background the bot from a launchd-managed watchdog:
# launchd can terminate child processes when the watchdog job exits. `exec`
# replaces this watchdog process with the bot so the supervised process stays
# alive and receives signals directly.
TS=$(date -Iseconds)
# 2026-11-24: start through the one launcher. A bare `uv run python main.py`
# skipped requirements-video.txt (every video cycle failed on a missing module)
# and ignored the launcher's switches.
echo "[$TS] Bot dead — execing bin/run.sh" >> "$LOG_FILE"
exec "$PROJECT_DIR/bin/run.sh" >> /tmp/aitwitter_run.out 2>> "$PROJECT_DIR/bot.err"
