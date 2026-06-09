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

Mission, in order. BE DECISIVE — you have a turn budget; spend most of it
SHIPPING, not exploring. Pick the FIRST clearly-worthwhile change you find;
do not survey everything.
1. DIAGNOSE (fast — a few turns max): read engagement_log.csv per-action
   daily counts, engine_health_alerts.json, and the tail of bot.log. The
   account is AI-PRIMARY (AI labs/models/chips/stocks + AI-crypto + AI-vs-BTC
   feud; the therapist voice frames AI replies). Quote-RT of AI virals +
   reply volume are the validated winners — protect and strengthen them.
2. IMPROVE: implement ONE SMALL, concrete change (fix > feature), target
   ≤~40 lines of diff. Match existing code style and invariants (CLAUDE.md).
   If you can't find a clear win, a focused test or a doc-accuracy fix counts
   — shipping something small and correct beats a sprawling change that
   times out.
3. TEST: run '.venv/bin/python -m pytest tests/ -q' — must pass. Add a test
   if your change touches guard logic. NEVER start the bot (operator starts
   it himself; leave .bot_disabled alone).
4. SHIP VIA PR (operator mandate — PR flow, never direct push to main here):
   a. git checkout -b improve/$(date +%Y-%m-%d)-<short-slug>   (branch from up-to-date main)
   b. Commit ONLY your improvement files (update CLAUDE.md+CODEX.md, +README if user-facing, same commit). Do NOT commit unrelated dirty bot-state .json files — the running bot syncs those on main.
   c. git push -u origin <branch>
   d. gh pr create --fill --body including: what was diagnosed, what changed, test results, and the standard Claude Code footer.
   e. CI wait — BOUNDED so you don't burn the turn budget polling: 'sleep 90 && gh pr checks <pr-number>'. If green → step f. If still pending, 'sleep 90 && gh pr checks <pr-number>' ONCE more. If FAILED → fix on the branch, push, and repeat this bounded wait at most ONE more time.
   f. gh pr merge <pr-number> --squash --delete-branch   (NOT --auto; the repo has no required-checks branch protection — that would block the bot's state pushes)
   g. git checkout main && git pull --rebase
5. RECORD: save learnings to auto-memory.

FALLBACK (do this if you're running low on turns BEFORE a merge): make sure
the branch is pushed and the PR is OPEN with a clear body, then STOP and note
in auto-memory that a PR is awaiting review. A pushed PR for human review is
a successful run — never end with uncommitted work or a half-applied change
on a branch.

Hard limits: never touch core_identity.md voice pillars, BLOCKLIST,
respect_list defaults, HARD_RULES_BLOCK, or the 48h REPOST_MAX_AGE_HOURS rule.
Keep the change small enough to review in one diff."

echo "[auto_improve] $(date '+%F %T') starting run (emergency=${EMERGENCY_CONTEXT:+yes})" >> "$LOG_FILE"

# Headless Claude Code: -p (print mode) executes the mission and exits.
# --dangerously-skip-permissions: unattended run, no TTY for prompts.
/usr/bin/env PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" \
  claude -p "$PROMPT" \
  --dangerously-skip-permissions \
  --max-turns 150 \
  >> "$LOG_FILE" 2>&1 || echo "[auto_improve] $(date '+%F %T') run FAILED (rc=$?)" >> "$LOG_FILE"

echo "[auto_improve] $(date '+%F %T') run finished." >> "$LOG_FILE"
