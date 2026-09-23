---
name: restart
description: Restart the bot so code and config changes take effect. Only on an explicit operator request.
disable-model-invocation: true
allowed-tools: Bash Read
---

Restart the bot. Only when the operator explicitly asks for it. Code, `.env`
and config changes take effect at restart.

1. Check the supervisors (`docs/OPERATIONS.md#supervisors`):
   `launchctl list | grep com.kzer.ai-twitter-bot` and
   `pgrep -f bin/watchdog.sh`. If one is active, it relaunches the bot after
   the stop: report it and let it do the start instead of step 3.
2. Stop: `bin/stop_bot.sh`, wait 3 seconds, verify with
   `pgrep -if "python.*main\.py"`.
3. Start: `nohup ./bin/run.sh >/tmp/aitwitter_run.out 2>&1 &`
4. Wait 10 seconds, confirm the new PID with `pgrep -if "python.*main\.py"`.
5. Show the last lines of `bot.log`.

`action_ledger.json` and `editorial_state.json` survive the restart: today's
posts still count and a `pending` slot stays pending.
