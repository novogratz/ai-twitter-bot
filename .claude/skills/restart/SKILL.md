---
name: restart
description: Restart the bot - stop then start
disable-model-invocation: true
allowed-tools: Bash Read
---

Restart the bot:

1. Find and kill: `ps aux | grep "python main.py" | grep -v grep`, then `kill <PID>`
2. Wait 3 seconds
3. Start: `nohup python3 main.py > /dev/null 2>&1 &`
4. Confirm new PID
5. Show bot.log activity
