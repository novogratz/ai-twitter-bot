#!/bin/bash
# Autonomous operator cycle — runs every 4h via launchd.
# Spins up a fresh `codex exec` subprocess that reads operator_prompt.md and
# executes the meta-improvement checklist on the live bot.
#
# Lives on the user's local Mac (not Anthropic cloud) so it has direct access to:
#   - bot.log (tail)
#   - the running python3 main.py process (restart)
#   - local git credentials (push)
#   - the Codex CLI subscription (no API key)

set -euo pipefail

PROJECT_DIR="/Users/benoitfloch/ai-twitter-bot"
LOG_FILE="/tmp/kzer_operator.log"
CODEX_BIN="${CODEX_BIN:-/opt/homebrew/bin/codex}"

cd "$PROJECT_DIR"

# Make sure PATH lets the operator find python3, git, etc.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

export AI_CLI="${AI_CLI:-codex}"
export NEWS_MODEL="${NEWS_MODEL:-gpt-5.4}"
export REPLY_MODEL="${REPLY_MODEL:-gpt-5.4-mini}"
export HOTAKE_MODEL="${HOTAKE_MODEL:-gpt-5.4-mini}"
export QUOTE_MODEL="${QUOTE_MODEL:-gpt-5.4-mini}"
export ROAST_MODEL="${ROAST_MODEL:-gpt-5.4-mini}"
export LLM_MIN_SECONDS_BETWEEN_CALLS="${LLM_MIN_SECONDS_BETWEEN_CALLS:-60}"
export LLM_MAX_CALLS_PER_HOUR="${LLM_MAX_CALLS_PER_HOUR:-30}"
export ENABLE_AI_MAINTENANCE="${ENABLE_AI_MAINTENANCE:-0}"
export ENABLE_AI_DISCOVERY="${ENABLE_AI_DISCOVERY:-0}"

TS=$(date -Iseconds)
echo "" >> "$LOG_FILE"
echo "===== OPERATOR CYCLE START $TS =====" >> "$LOG_FILE"

PROMPT="$(cat "$PROJECT_DIR/operator_prompt.md")"

# Pipe stdout+stderr into the rolling log so the user can `tail -f /tmp/kzer_operator.log`
# on return to see what every cycle did. Use mini + read-only by default:
# this operator is advisory in Plus-safe mode, not an autonomous heavy worker.
"$CODEX_BIN" exec \
  --model "${OPERATOR_MODEL:-gpt-5.4-mini}" \
  --sandbox read-only \
  --ask-for-approval never \
  --ephemeral \
  - <<< "$PROMPT" \
  >> "$LOG_FILE" 2>&1 || echo "[operator_cycle.sh] codex exited non-zero $?" >> "$LOG_FILE"

echo "===== OPERATOR CYCLE END $(date -Iseconds) =====" >> "$LOG_FILE"
