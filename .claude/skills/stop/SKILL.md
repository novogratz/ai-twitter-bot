---
name: stop
description: Stop the bot gracefully via SIGTERM
allowed-tools: Bash
---

Stop the bot:

1. Find process: `ps aux | grep -iE "python[3]? main\.py" | grep -v grep`
   - Case-insensitive: macOS framework Python shows as `Python main.py` (capital P), so a plain lowercase grep MISSES it and you'll wrongly conclude the bot is stopped.
2. If running, send SIGTERM to ALL matching PIDs: `kill <PID1> <PID2> ...`
   - Multiple `main.py` processes are normal (parent + workers). Kill them all.
3. Wait 3 seconds, verify stopped with the same case-insensitive grep
4. If not running, say so
