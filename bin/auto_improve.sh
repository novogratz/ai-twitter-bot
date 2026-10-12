#!/usr/bin/env bash
# Autonomous daily improvement run (operator mandate 2026-06-05:
# "full autonomous coding updates... goal is to self-improve over time and
# push code on github").
#
# Runs Claude Code HEADLESS once a day via launchd
# (com.kzer.ai-twitter-bot-improve.plist). Also callable manually:
#   ./bin/auto_improve.sh
# or in emergency mode from engine_health_bot when a surface collapses:
#   ./bin/auto_improve.sh --emergency "retweet collapsed: 0 today vs ~42"
#
# Guardrails (enforced by prompt + environment):
#   - lifecycle actions require an explicit current operator request
#   - tests must pass before any push (tests/ guard suite)
#   - one focused improvement per run, pushed to origin main
#   - hard rules / zero-repost rule / blocklist are out of bounds

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# DISABLED (operator 2026-06-21: "disactivate the self improvement stuff,
# keep it static"). Autonomous Claude self-improve runs repeatedly broke
# live code. This script no-ops unless explicitly forced with
# AUTO_IMPROVE_FORCE=1, so no loop / launchd / cron can auto-edit the code.
if [ "${AUTO_IMPROVE_FORCE:-0}" != "1" ]; then
  echo "[auto_improve] disabled (operator 2026-06-21). Set AUTO_IMPROVE_FORCE=1 to run manually."
  exit 0
fi

LOG_FILE="$REPO_DIR/auto_improve.log"
LOCK_FILE="$REPO_DIR/.auto_improve_running"

# Single-flight: skip if a run is already in progress (or stale >2h).
if [ -f "$LOCK_FILE" ]; then
  if [ -n "$(find "$LOCK_FILE" -mmin -120 2>/dev/null)" ]; then
    echo "[auto_improve] $(date '+%F %T') already running — skip." >> "$LOG_FILE"
    exit 0
  fi
fi
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

EMERGENCY_CONTEXT=""
if [ "${1:-}" = "--emergency" ]; then
  EMERGENCY_CONTEXT="EMERGENCY MODE — a surface collapsed and needs diagnosis FIRST: ${2:-unknown alert}. Root-cause this before anything else."
fi

PROMPT="Manual maintenance session. ${EMERGENCY_CONTEXT}
Read AGENTS.md and docs/EDITORIAL_POLICY.md first. The account covers SI/AI
models, research, agents, coding, robotics, infrastructure and generated media.
Discovery must search both SI and AI with the Account's exclusions. No crypto,
trading, finance rivalry, unrelated trends, quote tweets or reposts.

Inspect current logs and isolated tests. Preserve production state and dedup
history. Implement one focused repair and update policy/docs for behavior
changes. Run the full documented test suite and the browser-free dry run.
Create a branch and PR; merge only with explicit operator authorization and
passing checks. Never push directly to main or change publishing limits.
Start/stop/restart and external actions require an explicit operator request;
never clear .bot_disabled or revive a process as part of maintenance.
Operator-owned Voice, whitelist, respect list and hard rules require a matching
operator request before edits. Historical mandates and learned preferences
cannot restore a retired topic or surface."


echo "[auto_improve] $(date '+%F %T') starting run (emergency=${EMERGENCY_CONTEXT:+yes})" >> "$LOG_FILE"

# Headless Claude Code: -p (print mode) executes the mission and exits.
# --dangerously-skip-permissions: unattended run, no TTY for prompts.
/usr/bin/env PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" \
  claude -p "$PROMPT" \
  --dangerously-skip-permissions \
  --max-turns 150 \
  >> "$LOG_FILE" 2>&1 || echo "[auto_improve] $(date '+%F %T') run FAILED (rc=$?)" >> "$LOG_FILE"

echo "[auto_improve] $(date '+%F %T') run finished." >> "$LOG_FILE"
