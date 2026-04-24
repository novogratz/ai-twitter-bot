---
name: stop
description: Stop the bot gracefully via SIGTERM
allowed-tools: Bash
---

Stop the bot:

1. Find process: `ps aux | grep "python main.py" | grep -v grep`
2. If running, send SIGTERM: `kill <PID>`
3. Wait 3 seconds, verify stopped
4. If not running, say so
