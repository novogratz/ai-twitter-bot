#!/bin/bash
# Lightweight bot watchdog — runs every 5 minutes via launchd.
# If `python3 main.py` is dead, restart it. No Claude calls, no AI cost.
# This guarantees the bot is never dark for more than ~5 minutes.

set -euo pipefail

PROJECT_DIR="$HOME/ai-twitter-bot"
LOG_FILE="/tmp/kzer_watchdog.log"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$PROJECT_DIR"

# Manual kill-switch: if /stop (or the user) created .bot_disabled, do
# NOT restart. Otherwise the watchdog defeats /stop within 5 minutes.
# /start removes this file before launching.
if [ -f "$PROJECT_DIR/.bot_disabled" ]; then
    exit 0
fi

# Check for live bot process (case-insensitive: macOS framework Python
# shows as `Python main.py` with a capital P, so plain `pgrep -f` misses it).
if pgrep -if "python.*main\.py" > /dev/null 2>&1; then
    # Alive — silent success (don't fill the log).
    exit 0
fi

# Dead. Restart.
TS=$(date -Iseconds)
echo "[$TS] Bot dead — restarting" >> "$LOG_FILE"
nohup python3 main.py > /tmp/kzer_bot.out 2>&1 &
NEW_PID=$!

sleep 3

if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo "[$TS] Restart OK — new PID $NEW_PID" >> "$LOG_FILE"
    exit 0
else
    echo "[$TS] RESTART FAILED — investigate /tmp/kzer_bot.out" >> "$LOG_FILE"
    exit 1
fi
