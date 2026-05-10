---
name: stop
description: Stop the bot gracefully via SIGTERM
allowed-tools: Bash
---

Stop the bot:

1. **First** create the kill-switch file: `touch .bot_disabled`
   - Without this, the launchd watchdog (`bot_watchdog.sh`, every 5 min) will restart the bot and silently undo /stop. The watchdog checks for this file and skips restart when present.
2. Find process: `ps aux | grep -iE "python[3]? main\.py" | grep -v grep`
   - Case-insensitive: macOS framework Python shows as `Python main.py` (capital P), so a plain lowercase grep MISSES it and you'll wrongly conclude the bot is stopped.
3. If running, send SIGTERM to ALL matching PIDs: `kill <PID1> <PID2> ...`
   - Multiple `main.py` processes are normal (parent + workers). Kill them all.
4. Wait 3 seconds, verify stopped with the same case-insensitive grep
5. If not running, still create `.bot_disabled` so the watchdog doesn't bring it back, then say so
