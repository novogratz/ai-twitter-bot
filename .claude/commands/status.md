Check the current status of the bot. Quick health check:

1. Check if `main.py` is currently running: `ps aux | grep "python main.py" | grep -v grep`
2. Read `daily_state.json` for today's counters
3. Check the last 20 lines of `bot.log` for recent activity and any errors
4. Read `followed_accounts.json` to count follows
5. Report:
   - Is the bot running? (yes/no)
   - Today's stats: X news, Y hot takes, out of limits
   - Last activity timestamp from logs
   - Any errors in recent logs
   - Number of accounts followed
