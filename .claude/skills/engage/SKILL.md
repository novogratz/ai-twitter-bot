---
name: engage
description: Trigger an engage cycle - follow and like target AI accounts
disable-model-invocation: true
allowed-tools: Bash
---

Trigger one engage cycle:

1. Run `python3 -c "from src.engage_bot import run_engage_cycle; run_engage_cycle()"`
2. Report which accounts were engaged with and follow status
