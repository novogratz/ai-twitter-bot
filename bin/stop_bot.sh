#!/bin/bash
# Stop the bot: arm the watchdog kill-switch, then SIGTERM every main.py
# process whose CWD is this repo (a bare `pkill -f main.py` would hit
# unrelated projects). Mirrors the /stop skill; used by the Claude Code
# Stop hook so the bot is never left running after an agentic session.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"

touch "$REPO/.bot_disabled"

killed=""
for pid in $(pgrep -if 'python[3]? main\.py' 2>/dev/null); do
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    if [ "$cwd" = "$REPO" ]; then
        kill "$pid" 2>/dev/null && killed="$killed $pid"
    fi
done

if [ -n "$killed" ]; then
    echo "{\"systemMessage\": \"🛑 Bot stopped (PIDs:$killed) — .bot_disabled armed\"}"
fi
exit 0
