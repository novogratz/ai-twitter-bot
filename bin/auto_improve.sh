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
#   - NEVER starts the bot (operator-only); leaves .bot_disabled untouched
#   - tests must pass before any push (tests/ guard suite)
#   - one focused improvement per run, pushed to origin main
#   - hard rules / 48h repost rule / blocklist are out of bounds

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

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

PROMPT="Autonomous improvement session for the ai-twitter-bot repo (operator mandate 2026-06-05 — see memory project-autonomous-daily-improvement). ${EMERGENCY_CONTEXT}

Mission, in order:
1. DIAGNOSE: read engagement_log.csv per-action daily counts, engine_health_alerts.json, and the tail of bot.log. Find the weakest surface, any collapse, or the highest-leverage improvement. Quote-RT is the validated winner — protect and strengthen it.
2. IMPROVE: implement ONE concrete, focused change (fix > feature). Match existing code style and invariants (CLAUDE.md).
3. TEST: run '.venv/bin/python -m pytest tests/ -q' — must pass. Add a test if your change touches guard logic. NEVER start the bot (operator starts it himself; leave .bot_disabled alone).
4. SHIP VIA PR (operator mandate 2026-06-05 — PR flow, never direct push to main from this run):
   a. git checkout -b improve/$(date +%Y-%m-%d)-<short-slug>   (branch from up-to-date main)
   b. Commit ONLY your improvement files there (update CLAUDE.md+CODEX.md, +README if user-facing, in the same commit). Do NOT commit unrelated dirty bot-state .json files — the running bot syncs those itself on main.
   c. git push -u origin <branch>
   d. gh pr create --fill --body including: what was diagnosed, what changed, test results, and the standard Claude Code footer.
   e. gh pr merge --auto --squash --delete-branch   (auto-merges once the guard-tests CI check passes; main stays green by construction)
   f. git checkout main
5. RECORD: save learnings to auto-memory.

Hard limits: never touch core_identity.md voice pillars, BLOCKLIST, respect_list defaults, HARD_RULES_BLOCK, or the 48h REPOST_MAX_AGE_HOURS rule. Keep the change small enough to review in one diff."

echo "[auto_improve] $(date '+%F %T') starting run (emergency=${EMERGENCY_CONTEXT:+yes})" >> "$LOG_FILE"

# Headless Claude Code: -p (print mode) executes the mission and exits.
# --dangerously-skip-permissions: unattended run, no TTY for prompts.
/usr/bin/env PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" \
  claude -p "$PROMPT" \
  --dangerously-skip-permissions \
  --max-turns 80 \
  >> "$LOG_FILE" 2>&1 || echo "[auto_improve] $(date '+%F %T') run FAILED (rc=$?)" >> "$LOG_FILE"

echo "[auto_improve] $(date '+%F %T') run finished." >> "$LOG_FILE"
