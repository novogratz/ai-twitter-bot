---
name: start
description: Start the full bot in background (all 4 bots)
allowed-tools: Bash Read
---

Start the bot:

1. Check if already running: `ps aux | grep "python main.py" | grep -v grep`
2. If running, show the PID
3. If not, start it: `nohup python3 main.py > /dev/null 2>&1 &`
4. Confirm with PID
5. Show first lines of bot.log
