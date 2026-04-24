---
name: reply
description: Manually trigger a reply cycle - finds AI tweets and posts witty replies
disable-model-invocation: true
allowed-tools: Bash Read
---

Trigger one reply scan:

1. Run `python3 -c "from src.reply_bot import run_reply_cycle; run_reply_cycle()"` to scan and reply
2. Report how many replies were posted and to which tweets
