# CODEX.md

Project context for **Codex CLI** sessions. Mirror of [`CLAUDE.md`](CLAUDE.md). Use whichever CLI you have authenticated.

> 🤖 **Infos IA et Crypto, avant tout le monde. Analyses pointues. Zéro bullshit, zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison.** ⚡

> **Mandate 2026-05-13:** FR only. Scope = IA + Crypto only (no bourse / actions / macro). Goal = thousands of followers + likes.

---

## Quick context

This repo is **kzer**, an autonomous Twitter/X growth agent. ~30 concurrent micro-bots managed by APScheduler in `main.py`. Browser-driven via Safari + AppleScript — no Twitter API key.

**Default AI provider: OpenCode** (`AI_CLI=opencode`). No auth needed — free and ready to go.

Switch providers at any time:

```bash
AI_CLI=claude  ./bin/run.sh    # one-off
echo "AI_CLI=claude" >> .env   # persistent
```

The same models run across all generation surfaces (news, replies, hot takes, threads, breakouts). The CLI adapter (`src/llm_client.py`) handles each provider transparently. If the primary returns a hard failure (non-zero exit, empty stdout) **or a soft refusal** (exit 0 but body like `[no need to search for external sources…]`), the same fallback ladder fires: `LLM_FALLBACK_CLI` / `LLM_FALLBACK_MODEL`, then `OPENCODE_FALLBACK2_MODEL`. Refusal patterns live in `_REFUSAL_PATTERNS` in `src/llm_client.py`.

News bursts are tuned via `NEWS_POSTS_PER_CYCLE` (default `3`); set to `1` when the LLM is flaky so each cycle skips fast instead of grinding for 6+ min on bad output.

LLM budgets are soft by default: `LLM_ENFORCE_BUDGET=0` means usage is logged
but production content is not blocked by local hourly/daily counters. Set it to
`1` only when you explicitly want hard caps. News/replies should use the LLM;
research, scoring, RSS/HN/X signal collection, and maintenance should stay
deterministic or feature-gated.

---

## Setup

```bash
git clone <repo>
cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env       # then edit caps + handle
opencode auth              # or claude/gemini login — set AI_CLI accordingly
./bin/run.sh               # foreground start, Ctrl-C to stop
```

For full operations playbook see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## Skills

User-invokable slash commands live under `.codex/skills/` (mirror of `.claude/skills/`). 24 skills, each is a directory with a `SKILL.md` file:

- **Lifecycle**: `start`, `stop`, `restart`, `status`, `run-agent`
- **Manual triggers**: `post`, `reply`, `engage`, `boost`, `hotake`, `news`, `tweet`, `thread`, `dryrun`
- **Account ops**: `follow`, `like`, `accounts`, `history`
- **Telemetry**: `logs`, `stats`, `config`, `reset`, `improve`

Skill format (frontmatter YAML):

```markdown
---
name: post
description: Trigger one post cycle
allowed-tools: Bash Read
---

Trigger one post cycle:
1. ...
2. ...
```

The `.codex/skills/` directory is a verbatim mirror of `.claude/skills/`. If/when Codex's CLI adopts a different skill format, update both directories together.

---

## Project conventions

(Identical across CLI providers — see [`CLAUDE.md`](CLAUDE.md) for the full set; quick reference below.)

### Hard rules — stamped into every prompt

1. No illegal content of any kind.
2. No trolling US government / federal agencies (Fed, SEC, IRS, etc.).
3. No criticism by name of anyone in `respect_list.json`.

### Safety lattice

- **`BLOCKLIST`** in `src/config.py` — hard list (never engage).
- **`respect_list.py`** — soft list (engage but never criticize by name). Output scrubs at every content bot's post path.
- **`personality_store.HARD_RULES_BLOCK`** — hard rules block injected into every generation prompt.
- **`suppression_watch_bot`** — pauses aggressive bots if engagement collapses.
- **`health.py`** — Safari watchdog auto-restarts after 3 cycle failures.
- **`safari_hygiene.py`** — preventive Safari quit+relaunch every 2h. Stops Safari from wedging after hours of automation; cookies + localStorage persist so login survives.

### Voice

Defined in `core_identity.md`. Stable. Never auto-rewritten. Loaded into every prompt as the ideological spine. Four pillars:

1. **Before anyone else** — ship first or SKIP.
2. **In-depth analysis** — sharp angle, exact figure, named causality.
3. **Zero bullshit, zero fluff** — every word earns its slot.
4. **You'll hate me until I'm right** — confident-arrogant, signs the take.

### Comedy patterns (`pattern_tags.py`)

Every generated tweet carries `[PATTERN: <ID>]` metadata. Six patterns:
- `REPETITION` / `DIALOGUE` / `METAPHOR` / `RENAME` / `EN_ANCHOR` / `UNDERSTATEMENT`

Plus `FR_ANCHOR` for FR-mode runs and `OTHER` as fallback. The metadata line is stripped before posting and logged into `engagement_log.csv` column 6 for bandit attribution.

---

## Files of note

| File | Purpose |
|---|---|
| `main.py` | Scheduler entry point — boots all bots |
| `src/config.py` | Central config + live-cap reader |
| `src/llm_client.py` | CLI adapter (OpenCode / Codex / Claude / Gemini) |
| `src/twitter_client.py` | Safari + AppleScript browser automation |
| `src/agent.py`, `hotake_agent.py`, etc. | Generation modules |
| `core_identity.md` | Stable voice anchor |
| `personality.json` | Per-account dossiers (rewritten by reflection_agent when maintenance is enabled) |
| `bot_self.json` | Bot's evolving mood (rewritten by self_evolution_agent when maintenance is enabled) |
| `live_strategy.json` | Daily caps + cadence (rewritten by meta_strategy_agent when maintenance is enabled) |
| `directives.md` | Style guide (rewritten by evolution_agent when maintenance is enabled) |
| `engagement_log.csv` | Append-only action log (the source of truth for ROI math) |

For the full module catalog see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Adding a new bot

See [`docs/ARCHITECTURE.md#adding-a-new-bot`](docs/ARCHITECTURE.md#6-adding-a-new-bot).

---

## Differences vs Claude

The runtime behavior is identical regardless of CLI provider — `src/llm_client.py` normalises the JSON envelopes, command flags, and tool-permission semantics so generation modules don't care which CLI is wrapping the model.

Codex-specific notes:
- Default models are `gpt-5.4-mini` across routine surfaces. Set `NEWS_MODEL=gpt-5.4` or `PRIORITY_REPLY_MODEL=gpt-5.4` only for a deliberate high-quality run.
- In Codex mode, `NEWS_CANDIDATES` defaults to `1` so one news post costs one generation call. Raising it to `2` or `3` also enables the judge call when multiple candidates survive.
- The 4-hour `operator_cycle.sh` Codex agent is skipped unless `ENABLE_AI_MAINTENANCE=1` or `ENABLE_CODEX_OPERATOR=1`.
- Codex's `--output-format json` produces an envelope that `unwrap_text` extracts via the `result` field (same as Claude).
- WebSearch tool permission flag is the same `--allowed-tools` flag.

---

## Memory model

This file is read by Codex CLI agentic sessions when working on the bot's source. It exists to give the AI context about the project so first-time edits don't break invariants. The same content lives in `CLAUDE.md` for Claude Code sessions. Keep them in sync when you edit either.
