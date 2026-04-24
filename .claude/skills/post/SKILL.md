---
name: post
description: Manually trigger a post cycle - generates and posts an AI news tweet or hot take
allowed-tools: Bash Read
---

Trigger one post cycle:

1. Read `src/bot.py` to understand current logic
2. Run `python3 -c "from src.bot import run_bot_cycle; run_bot_cycle()"` to trigger one post
3. Report what was posted (news or hot take) and the daily counter status
