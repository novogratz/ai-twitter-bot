Show and edit bot configuration:

1. Read `src/config.py` and display all current settings:
   - BOT_HANDLE
   - Daily limits (MAX_NEWS_PER_DAY, MAX_HOTAKES_PER_DAY)
   - Models (NEWS_MODEL, REPLY_MODEL, HOTAKE_MODEL)
   - Retry settings
2. Show which environment variables can override these
3. If the user wants to change a setting, edit `src/config.py` directly
4. Remind them to restart the bot for changes to take effect
