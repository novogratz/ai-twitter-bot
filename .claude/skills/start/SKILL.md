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
2. Check the supervisors (`docs/OPERATIONS.md#supervisors`):
   `launchctl list com.kzer.ai-twitter-bot` exits 0 (launchd job loaded) or
   `pgrep -f bin/watchdog.sh` prints a PID. If one is active, it starts the
   bot by itself: report it instead of launching a second copy.
3. Start: `nohup ./bin/run.sh >/tmp/aitwitter_run.out 2>&1 &`
   - If the operator requested **video first, then replies**, first run
     `uv run --with-requirements requirements-video.txt python bin/video.py resume-workers`
     and `uv run --with-requirements requirements-video.txt python bin/video.py activate --live --before-replies --request-id STABLE_OPERATOR_REQUEST_ID`.
     A blocked preflight must retain the interaction hold. Start only with that
     hold armed; never fall through to ordinary replying. The publisher releases
     it after the startup video is confirmed. See `docs/VIDEO_PIPELINE.md`.
   - `run.sh` validates configuration, stops other matching `python.*main.py`
     processes, selects the existing requirements file (including video
     dependencies when enabled), then runs `main.py`. It performs no model
     warm-up; the logger writes `bot.log`.
4. Wait 10 seconds, confirm the PID with `pgrep -if "python.*main\.py"`.
5. Show the last lines of `bot.log`. Started Overnight, the bot logs
   `[HOURS] Asleep. Next wake: …`; interactions wait until waking hours, while
   isolated video discovery/media can continue. A video-first hold remains until
   the startup video is confirmed.
