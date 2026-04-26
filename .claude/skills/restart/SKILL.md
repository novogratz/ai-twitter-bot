---
name: restart
description: Restart the bot - stop then start
allowed-tools: Bash Read
---

Restart the bot:

1. Find and kill: `ps aux | grep -iE "python[3]? main\.py" | grep -v grep`, then `kill <PID1> <PID2> ...` for ALL matches.
   - Case-insensitive: macOS framework Python shows as `Python main.py` (capital P). Multiple PIDs are normal — kill them all.
2. Wait 3 seconds
3. Start: `nohup python3 main.py > /dev/null 2>&1 &`
4. Confirm new PID
5. Show bot.log activity
