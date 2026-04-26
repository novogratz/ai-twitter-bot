---
name: start
description: Start the full bot in background (all 4 bots)
allowed-tools: Bash Read
---

Start the bot:

1. **First** clear the kill-switch: `rm -f .bot_disabled`
   - The watchdog (`bot_watchdog.sh`) skips restart while this file exists. /stop creates it; /start must remove it so the watchdog can resume auto-recovery.
2. Check if already running: `ps aux | grep -iE "python[3]? main\.py" | grep -v grep`
   - Case-insensitive: macOS framework Python shows as `Python main.py` (capital P).
3. If running, show the PID
4. If not, start it: `nohup python3 main.py > /dev/null 2>&1 &`
5. Confirm with PID
6. Show first lines of bot.log
