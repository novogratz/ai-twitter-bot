---
name: start
description: Start the bot in the background with bin/run.sh. Only on an explicit operator request.
disable-model-invocation: true
allowed-tools: Bash Read
---

Start the bot. Only when the operator explicitly asks for it: the bot
publishes on a real account. See `docs/OPERATIONS.md#start`.

1. Check if already running: `pgrep -if "python.*main\.py"` and `cat bot.lock`.
   If it runs, show the PIDs and stop here.
2. Check the supervisors (`docs/OPERATIONS.md#supervisors`): only one should
   be active. `launchctl list | grep com.kzer.ai-twitter-bot` (launchd) and
   `pgrep -f bin/watchdog.sh` (watchdog). If one is active, it starts the bot
   by itself: report it instead of launching a second copy.
3. Start: `nohup ./bin/run.sh >/tmp/aitwitter_run.out 2>&1 &`
   - `run.sh` kills every `python.*main.py` on the machine, pre-warms the
     reply model during waking hours, then runs `uv run python main.py`
     with output appended to `bot.log`.
4. Wait 10 seconds, confirm the PID with `pgrep -if "python.*main\.py"`.
5. Show the last lines of `bot.log`. Outside 04:30–22:00 Toronto time the bot
   logs `[HOURS] Asleep. Next wake: …` and does nothing until 04:30.
