# CLAUDE.md

Project context for **Claude Code** sessions. Mirror of [`CODEX.md`](CODEX.md). Use whichever CLI you have authenticated.

> 🤖 **AI, Crypto, and Stock Market news, before anyone else. In-depth analysis. Zero bullshit, zero fluff. You'll hate me until I'm right.** ⚡

---

## Quick context

This repo is **kzer**, an autonomous Twitter/X growth agent. ~30 concurrent micro-bots managed by APScheduler in `main.py`. Browser-driven via Safari + AppleScript — no Twitter API key.

**Default AI provider: Codex CLI** (`AI_CLI=codex`) for bot content. Authenticate with `codex login`.

To use Claude Code instead:

```bash
claude login
echo "AI_CLI=claude" >> .env
```

The `src/llm_client.py` adapter handles each provider transparently.

---

## Setup

```bash
git clone <repo>
cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env       # edit caps + handle
codex login                # or claude login / gemini login
./bin/run.sh               # foreground start, Ctrl-C to stop
```

For full operations playbook see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## Skills

User-invokable slash commands live under `.claude/skills/` (mirrored at `.codex/skills/`). 24 skills, each is a directory with a `SKILL.md` file:

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

---

## Project conventions

### Hard rules — stamped into every prompt

1. No illegal content of any kind.
2. No trolling US government / federal agencies (Fed, SEC, IRS, etc.).
3. No criticism by name of anyone in `respect_list.json`.

These three are baked into `personality_store.HARD_RULES_BLOCK` and injected into every generation prompt. Cannot be overridden by autonomous agents.

### Safety lattice

- **`BLOCKLIST`** in `src/config.py` — hard list (never engage at all).
- **`respect_list.py`** — soft list (engage but never criticize by name). Output scrubs at every content bot's post path. Default-seeded with 30 high-traction handles.
- **`suppression_watch_bot`** — hourly health check; pauses aggressive bots (`spicy`, `breakout`, `follow_blast`) if avg likes drop below the floor.
- **`health.py`** — Safari watchdog auto-restarts after 3 consecutive cycle failures.

### Voice — `core_identity.md`

Stable. Never auto-rewritten. Loaded into every prompt as the ideological spine. Four pillars:

1. **Before anyone else** — ship first or SKIP.
2. **In-depth analysis** — sharp angle, exact figure, named causality.
3. **Zero bullshit, zero fluff** — every word earns its slot.
4. **You'll hate me until I'm right** — confident-arrogant, signs the take.

### Comedy patterns — `pattern_tags.py`

Every generated tweet carries `[PATTERN: <ID>]` metadata. Six patterns:
- `REPETITION` / `DIALOGUE` / `METAPHOR` / `RENAME` / `EN_ANCHOR` / `UNDERSTATEMENT`

Plus `FR_ANCHOR` for FR-mode runs, `OTHER` as fallback. The metadata line is stripped before posting and logged into `engagement_log.csv` column 6 for bandit attribution. `evolution_agent` reads this to compute per-pattern ROI and rewrite the style guide.

### Language — `lang_mode.py`

`CONTENT_LANG_PRIMARY=en` (default) → all standalone content (news, hot takes, breakouts, spicy, threads, quote-tweet commentary) in English.

Reply paths (`direct_reply`, `reply_bot`, `replyback_agent`, `viral_followup`, `spike`, `mega_watch`, `early_bird`) **always match parent tweet language** regardless of `CONTENT_LANG_PRIMARY`.

### Self-modification boundary

Agents that auto-rewrite project state (and auto-push to git):

| Agent | Cadence | What it modifies |
|---|---|---|
| `meta_strategy_agent` | 4h | `live_strategy.json` (daily caps, cadence factor, topic focus) |
| `strategy_agent` | 3h | `dynamic_queries.json` + `dynamic_accounts.json` (additions only) |
| `evolution_agent` | 3h | `directives.md` + `pruned_accounts.json` + `reinforced_accounts.json` |
| `reflection_agent` | 6h | `personality.json` (per-account dossiers + topic positions) |
| `self_evolution_agent` | 4h | `bot_self.json` (mood, obsession, drift, self_narrative) |
| `scout_agent` | 4h | `dynamic_accounts.json` + auto-follows |
| `performance.py` | 2h | `performance_log.json` + `learnings.json` |
| `daily_digest` | 1h (idempotent) | `daily_digest.md` |

Agents CANNOT touch:
- `core_identity.md` (ideological spine)
- `BLOCKLIST` in `config.py`
- `respect_list.py` defaults (operator-managed)
- `personality_store.HARD_RULES_BLOCK`
- Any source code (only state files)

---

## Files of note

| File | Purpose |
|---|---|
| `main.py` | Scheduler entry point — boots all bots |
| `src/config.py` | Central config + live-cap reader (`get_live_cap`, `get_live_cadence_factor`) |
| `src/llm_client.py` | CLI adapter (Claude / Codex / Gemini) |
| `src/twitter_client.py` | Safari + AppleScript browser automation |
| `src/agent.py` etc. | Generation modules (one per content surface) |
| `core_identity.md` | Stable voice anchor |
| `personality.json` | Per-account dossiers (rewritten by reflection_agent) |
| `bot_self.json` | Bot's evolving mood (rewritten by self_evolution_agent) |
| `live_strategy.json` | Daily caps + cadence (rewritten by meta_strategy_agent) |
| `directives.md` | Style guide (rewritten by evolution_agent) |
| `engagement_log.csv` | Append-only action log (source of truth for ROI math) |

For the full module catalog see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Adding a new bot

See [`docs/ARCHITECTURE.md#6-adding-a-new-bot`](docs/ARCHITECTURE.md#6-adding-a-new-bot).

Mandatory invariants:

1. Wrap the cycle body in `try/except` inside `safe_run_*` so a single-cycle exception cannot crash the scheduler.
2. Call `health.record_success/failure` at the end.
3. If interacting with Safari, take `_safari_lock` before opening URLs and `close_front_tab` at the end.
4. If writing state files that should be in git, call `git_ops.auto_push([...], "message")` after success.
5. If you have a daily cap, key state by `date.today().isoformat()` and short-circuit when reached.

---

## Memory model

This file is read by Claude Code agentic sessions when working on the bot's source. It exists to give the AI context about the project so first-time edits don't break invariants. The same content lives in [`CODEX.md`](CODEX.md) for Codex CLI sessions. **Keep them in sync** when you edit either.
