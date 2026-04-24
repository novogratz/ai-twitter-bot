Restart the bot. Stop it gracefully then start it again:

1. Find the bot process: `ps aux | grep "python main.py" | grep -v grep`
2. If running, send SIGTERM: `kill <PID>` and wait 3 seconds
3. Verify it stopped
4. Start it again: `nohup python main.py > /dev/null 2>&1 &`
5. Confirm the new PID
6. Show the first few lines of bot.log to confirm activity
