---
name: status
description: Quick bot health check - is it running, counters, errors
disable-model-invocation: true
allowed-tools: Bash Read
---

Quick health check:

1. Check if running: `ps aux | grep "python main.py" | grep -v grep`
2. Read `daily_state.json` for counters
3. Read last 20 lines of `bot.log` for recent activity
4. Read `followed_accounts.json` for follow count

Report:
- Bot running? (yes/no + PID)
- Today: X news, Y hot takes (out of limits)
- Last activity timestamp
- Any errors in recent logs
- Accounts followed
