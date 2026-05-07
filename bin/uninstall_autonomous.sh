#!/usr/bin/env bash
# Uninstall the @kzer_ai bot LaunchAgent. Bot will stop and not auto-respawn.

set -euo pipefail

PLIST_DEST="$HOME/Library/LaunchAgents/com.kzer.ai-twitter-bot.plist"
LABEL="com.kzer.ai-twitter-bot"

if [[ -f "$PLIST_DEST" ]]; then
  echo "[autonomous] Unloading LaunchAgent..."
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
  rm "$PLIST_DEST"
  echo "[autonomous] Removed plist."
fi

# Belt-and-suspenders: also kill any lingering python main.py process.
if pgrep -f "python.*main.py" >/dev/null; then
  echo "[autonomous] Stopping bot processes..."
  pkill -TERM -f "python.*main.py" || true
  sleep 2
  pkill -KILL -f "python.*main.py" 2>/dev/null || true
fi

echo "[autonomous] Uninstalled. Bot will not auto-start anymore."
echo "[autonomous] Re-install anytime: $(dirname "$0")/install_autonomous.sh"
