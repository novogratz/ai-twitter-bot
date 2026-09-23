---
name: stop
description: Stop the bot gracefully with bin/stop_bot.sh. Only on an explicit operator request.
disable-model-invocation: true
allowed-tools: Bash Read
---

Stop the bot. Only when the operator explicitly asks for it. See
`docs/OPERATIONS.md#stop`.

1. Check the supervisors first, or the bot comes back
   (`docs/OPERATIONS.md#supervisors`):
   - launchd: `launchctl list | grep com.kzer.ai-twitter-bot`. If loaded, ask
     the operator before unloading it (`bin/uninstall_autonomous.sh`).
   - `bin/watchdog.sh`: `pgrep -f bin/watchdog.sh`. If running,
     `touch .watchdog_off` so it stays hands-off.
2. Run `bin/stop_bot.sh`: touches `.bot_disabled`, then SIGTERMs the
   `main.py` processes whose working directory is this repo. SIGTERM counts
   as bedtime: no job starts and no write is admitted after it.
3. Wait 3 seconds, verify with `pgrep -if "python.*main\.py"`.
4. If a process from this repo remains, report it; `bin/stop.sh` escalates to
   SIGKILL but hits every `python.*main.py` on the machine, so ask first.
