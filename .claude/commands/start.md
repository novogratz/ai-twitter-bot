Start the full bot in the background. Launches all 4 bots (post, reply, engage, notify + boost):

1. Check if the bot is already running: `ps aux | grep "python main.py" | grep -v grep`
2. If already running, tell the user and show the PID
3. If not running, start it: `nohup python main.py > /dev/null 2>&1 &`
4. Confirm it started with the PID
5. Show the first few lines of bot.log to confirm activity
