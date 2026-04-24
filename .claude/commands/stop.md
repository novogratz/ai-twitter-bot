Stop the bot gracefully:

1. Find the bot process: `ps aux | grep "python main.py" | grep -v grep`
2. If running, send SIGTERM for graceful shutdown: `kill <PID>`
3. Wait 3 seconds, verify it stopped
4. If still running, warn the user (don't force kill without asking)
5. If not running, tell the user the bot is already stopped
