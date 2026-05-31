"""Autonomous Growth Agent — daily Claude Code CLI agentic strategy review.

Unlike the Python-only agents (strategy_agent, evolution_agent), this one
launches a full Claude Code CLI session with WebSearch, Bash, Read, Write,
and Edit tools. Claude investigates what's working, researches viral formats,
and rewrites directives.md + live_strategy.json, then commits and pushes.

Runs daily. Forces 'claude' provider regardless of AI_CLI setting.
"""
import json
import os
import subprocess
import traceback
from datetime import date, datetime

from .config import _PROJECT_ROOT
from .logger import log

STATE_FILE = os.path.join(_PROJECT_ROOT, "autonomous_growth_state.json")

# Model for the agentic run — Sonnet for quality + speed balance.
_AGENT_MODEL = os.environ.get("GROWTH_AGENT_MODEL", "claude-sonnet-4-6")

# Claude Code CLI tools granted to the agent.
_ALLOWED_TOOLS = [
    "WebSearch",
    "WebFetch",
    "Bash",
    "Read",
    "Write",
    "Edit",
]

AGENT_PROMPT = """\
You are the autonomous growth strategist for @AISpaceDecoder — an AI & Space
Twitter bot trying to reach 20k followers. Your job TODAY is to make it
measurably better. Work fast, be decisive, push all changes.

## Working directory
{project_root}

## Your mandate (in priority order)
1. Analyze what's working and what's not from recent engagement data.
2. Research what's trending on X right now in AI, Space, and investment.
3. Find viral tweet formats and tactics we're NOT using yet.
4. Rewrite directives.md with concrete, actionable style instructions.
5. Tune live_strategy.json caps if data justifies it.
6. Commit and push everything.

## Step 1 — Read performance data
Read these files:
- engagement_log.csv (last 300 rows) — all actions with timestamps and patterns
- performance_insights.json — top patterns, best hours, rising topics, viral examples
- learnings.json — top/worst performers
- live_strategy.json — current daily caps and cadence
- directives.md — current style guide

Look for: Which content types get the most likes? Which hours perform best?
Which topics trend up vs. down? What patterns (REPETITION, DIALOGUE, METAPHOR,
RENAME, EN_ANCHOR, UNDERSTATEMENT) win?

## Step 2 — Research current trends
Use WebSearch to find:
- "viral AI Twitter threads 2025 growth tactics"
- "space stocks trending Twitter today"
- "best performing AI influencer tweets this week"
- Current hot AI/Space news (Anthropic, OpenAI, SpaceX, RKLB, ASTS)
- What format is going viral on X right now (lists? threads? one-liners? bold claims?)

## Step 3 — Rewrite directives.md
Write a fresh directives.md that is concrete and prescriptive:
- Lead with a 1-line synthesis of what the data shows
- Give 5-8 specific, actionable rules (not vague platitudes)
- Include format cues: which patterns to lead with, sentence structures that win
- Reference specific examples from top performers if you found any
- Keep it under 400 words — short enough that every generation agent reads it fully
- Write in English (the bot's primary language is now English)

Format:
```
# Growth Directives — {today}

**Synthesis:** [1-line data-driven diagnosis]

## Apply to every tweet/reply/hot-take:
- [concrete rule 1]
- [concrete rule 2]
...

## Top patterns this week: [PATTERN_ID] > [PATTERN_ID] > [PATTERN_ID]
## Best hours: [hours]
## Rising topics: [topics]
```

## Step 4 — Tune live_strategy.json (optional)
Only if the data clearly shows imbalance (e.g. quotes underperform vs RT,
or engagement drops at night). Adjust caps conservatively (±20% max).
Keep MAX_RETWEETS_PER_DAY and MAX_QUOTES_PER_DAY high — those are our
primary surfaces now that news posts are disabled.

## Step 5 — Commit and push
```bash
cd {project_root}
git add directives.md live_strategy.json
git commit -m "Autonomous growth update — $(date +%Y-%m-%d)"
git push
```

## Rules
- Be decisive. Do NOT ask for confirmation. Make the changes and push.
- Only touch: directives.md and live_strategy.json. Do NOT edit source code.
- If data is ambiguous, default to "more aggressive engagement."
- The bot's voice: confident, data-driven, sharp, slightly audacious. Think
  quant analyst who also memes. 3 pillars: AI, Space, Investment.
- After pushing, output a 3-bullet summary of what you changed and why.
"""


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _claude_available() -> bool:
    import shutil
    return bool(shutil.which("claude"))


def run_autonomous_growth_cycle() -> None:
    state = _load_state()
    today = date.today().isoformat()

    if state.get("last_run") == today:
        log.info(f"[GROWTH_AGENT] Already ran today ({today}). Skipping.")
        return

    if not _claude_available():
        log.info("[GROWTH_AGENT] claude CLI not found. Skipping.")
        return

    # Check Claude lockout
    try:
        from .llm_client import _read_claude_lockout
        lockout = _read_claude_lockout()
        if lockout and lockout > datetime.now():
            log.info(f"[GROWTH_AGENT] Claude locked out until {lockout}. Skipping.")
            return
    except Exception:
        pass

    prompt = AGENT_PROMPT.format(project_root=_PROJECT_ROOT, today=today)

    cmd = [
        "claude",
        "-p", prompt,
        "--model", _AGENT_MODEL,
        "--no-session-persistence",
        "--allowedTools", *_ALLOWED_TOOLS,
        "--permission-mode", "bypassPermissions",
        "--output-format", "text",
    ]

    log.info(f"[GROWTH_AGENT] Launching Claude Code agentic review for {today}...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=_PROJECT_ROOT,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode != 0:
            log.info(f"[GROWTH_AGENT] Claude exited {result.returncode}. stderr: {stderr[:300]}")
            return

        log.info(f"[GROWTH_AGENT] Agent completed. Output:\n{stdout[:1000]}")

        state["last_run"] = today
        state["last_output"] = stdout[:500]
        state["last_ran_at"] = datetime.utcnow().isoformat()
        _save_state(state)

    except subprocess.TimeoutExpired:
        log.info("[GROWTH_AGENT] Claude timed out after 600s.")
    except Exception:
        log.info("[GROWTH_AGENT] Unexpected error:")
        traceback.print_exc()


def safe_run_autonomous_growth_cycle() -> None:
    from . import health
    try:
        run_autonomous_growth_cycle()
        health.record_success("growth_agent")
    except Exception:
        log.info("[GROWTH_AGENT] Unhandled error:")
        traceback.print_exc()
        health.record_failure("growth_agent")
