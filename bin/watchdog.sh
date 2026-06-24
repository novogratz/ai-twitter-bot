#!/usr/bin/env bash
# Watchdog agent (operator 2026-06-24: "an agent that starts the bot and
# monitors it to make sure it is always doing something").
#
# Keeps the bot ALIVE and PRODUCING:
#   - if the bot process isn't running    -> start it
#   - if bot.log hasn't moved in N minutes (stalled / hung Safari) -> restart
#
# Manual control:
#   - `touch .watchdog_off`  -> watchdog stays hands-off (won't revive the bot)
#   - stop the watchdog itself with Ctrl-C / kill to stop monitoring
# Starting the watchdog clears .bot_disabled (starting it = you want it up).
#
# Env: WATCHDOG_INTERVAL_SECONDS (default 120), WATCHDOG_STALL_MINUTES (15).

set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

INTERVAL="${WATCHDOG_INTERVAL_SECONDS:-120}"
STALL_MIN="${WATCHDOG_STALL_MINUTES:-15}"
LOG="$REPO_DIR/watchdog.log"

_log() { echo "$(date '+%F %T') [watchdog] $*" | tee -a "$LOG"; }

_bot_pids() { pgrep -f "python.*main.py" 2>/dev/null | tr '\n' ' '; }

_log_fresh() {
  # true if bot.log was modified within STALL_MIN minutes
  [ -f "$REPO_DIR/bot.log" ] && [ -n "$(find "$REPO_DIR/bot.log" -mmin -"$STALL_MIN" 2>/dev/null)" ]
}

_start_bot() {
  rm -f "$REPO_DIR/.bot_disabled"
  _log "starting bot via run.sh"
  nohup "$REPO_DIR/bin/run.sh" >/tmp/aitwitter_run.out 2>&1 &
  sleep 25
}

_restart_bot() {
  _log "restarting bot (stalled or dead)"
  pkill -INT -f "python.*main.py" 2>/dev/null || true
  sleep 5
  pkill -KILL -f "python.*main.py" 2>/dev/null || true
  sleep 2
  _start_bot
}

_log "watchdog up — interval ${INTERVAL}s, stall ${STALL_MIN}min. touch .watchdog_off to pause."
rm -f "$REPO_DIR/.bot_disabled"

while true; do
  if [ -f "$REPO_DIR/.watchdog_off" ]; then
    _log "paused (.watchdog_off present) — not touching the bot."
    sleep "$INTERVAL"; continue
  fi
  pids="$(_bot_pids)"
  if [ -z "${pids// /}" ]; then
    _log "bot not running."
    _start_bot
  elif ! _log_fresh; then
    _log "bot.log stale (> ${STALL_MIN}min) — bot is stalled."
    _restart_bot
  fi
  sleep "$INTERVAL"
done
