#!/usr/bin/env bash
# Install the @kzer_ai bot as a macOS LaunchAgent.
#
# Result: bot starts at login + auto-respawns on crash + survives reboots.
# Effectively turns the bot into a system service for this user account.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC="$REPO_DIR/launchd/com.kzer.ai-twitter-bot.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.kzer.ai-twitter-bot.plist"
LABEL="com.kzer.ai-twitter-bot"

echo "[autonomous] Repo: $REPO_DIR"

if [[ ! -f "$PLIST_SRC" ]]; then
  echo "[autonomous] ERROR: plist source not found at $PLIST_SRC"
  exit 1
fi

# 1. Stop any running bot (graceful) so launchd can take over without conflicts.
if pgrep -f "python.*main.py" >/dev/null; then
  echo "[autonomous] Stopping existing bot processes..."
  pkill -TERM -f "python.*main.py" || true
  sleep 3
  if pgrep -f "python.*main.py" >/dev/null; then
    echo "[autonomous] Forcing remaining processes..."
    pkill -KILL -f "python.*main.py" || true
    sleep 1
  fi
fi

# 2. If a previous LaunchAgent is loaded, unload it first.
if launchctl list 2>/dev/null | grep -q "$LABEL"; then
  echo "[autonomous] Unloading existing LaunchAgent..."
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# 3. Copy the plist into ~/Library/LaunchAgents.
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"
echo "[autonomous] Installed plist at $PLIST_DEST"

# 4. Load it. RunAtLoad=true means the bot starts immediately.
launchctl load "$PLIST_DEST"
echo "[autonomous] LaunchAgent loaded."

# 5. Verify it's running.
sleep 4
if launchctl list | grep -q "$LABEL"; then
  PID=$(launchctl list | awk -v lbl="$LABEL" '$3 == lbl {print $1}')
  if [[ -n "$PID" && "$PID" != "-" ]]; then
    echo "[autonomous] OK — bot is RUNNING with PID $PID."
  else
    echo "[autonomous] LaunchAgent loaded but bot not yet started — check $REPO_DIR/bot.log + bot.err"
  fi
else
  echo "[autonomous] WARNING — agent not found in launchctl list. Check $REPO_DIR/bot.err"
  exit 1
fi

cat <<EOF

────────────────────────────────────────
Bot is now FULLY AUTONOMOUS:
  - Starts when you log in.
  - Auto-respawns within ~30s if it crashes.
  - Survives reboots.

Useful commands:
  Tail logs:     tail -F $REPO_DIR/bot.log
  Stop forever:  $REPO_DIR/bin/uninstall_autonomous.sh
  Pause:         launchctl unload $PLIST_DEST
  Resume:        launchctl load $PLIST_DEST
  Check:         launchctl list | grep $LABEL
────────────────────────────────────────
EOF
