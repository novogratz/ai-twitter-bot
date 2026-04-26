---
name: status
description: Quick bot health check - is it running, counters, errors
allowed-tools: Bash Read
---

Quick health check:

1. Check if running: `ps aux | grep -iE "python[3]? main\.py" | grep -v grep`
   - Case-insensitive: macOS framework Python shows as `Python main.py` (capital P).
2. Read `daily_state.json` for counters
3. Read last 20 lines of `bot.log` for recent activity
4. Read `followed_accounts.json` for follow count

Report:
- Bot running? (yes/no + PID)
- Today: X news, Y hot takes (out of limits)
- Last activity timestamp
- Any errors in recent logs
- Accounts followed
