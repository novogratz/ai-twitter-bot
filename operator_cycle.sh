#!/bin/bash
# Autonomous operator cycle — runs every 4h via launchd.
# Spins up a fresh `claude -p` subprocess that reads operator_prompt.md and
# executes the meta-improvement checklist on the live bot.
#
# Lives on the user's local Mac (not Anthropic cloud) so it has direct access to:
#   - bot.log (tail)
#   - the running python3 main.py process (restart)
#   - local git credentials (push)
#   - the claude CLI subscription (no API key)

set -euo pipefail

PROJECT_DIR="/Users/benoitfloch/ai-twitter-bot"
LOG_FILE="/tmp/kzer_operator.log"
CLAUDE_BIN="/opt/homebrew/bin/claude"

cd "$PROJECT_DIR"

# Make sure PATH lets the operator find python3, git, etc.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

TS=$(date -Iseconds)
echo "" >> "$LOG_FILE"
echo "===== OPERATOR CYCLE START $TS =====" >> "$LOG_FILE"

PROMPT="$(cat "$PROJECT_DIR/operator_prompt.md")"

# Pipe stdout+stderr into the rolling log so the user can `tail -f /tmp/kzer_operator.log`
# on return to see what every cycle did.
"$CLAUDE_BIN" -p "$PROMPT" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
  --model claude-opus-4-6 \
  >> "$LOG_FILE" 2>&1 || echo "[operator_cycle.sh] claude exited non-zero $?" >> "$LOG_FILE"

echo "===== OPERATOR CYCLE END $(date -Iseconds) =====" >> "$LOG_FILE"
