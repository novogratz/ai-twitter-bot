# CLAUDE.md

Project context for **Claude Code** sessions. Mirror of [`CODEX.md`](CODEX.md). Use whichever CLI you have authenticated.

> **You'll hate me until I'm right.**

> **Mandate 2026-05-29:** Full pivot. Brand = 🚀 The AI & Space Decoder ⚡. 3 pillars: **AI** (labs, models, GPU infra, robotics, agentic), **Space** (SpaceX, Rocket Lab, NASA, satellites, space stocks), **Investment** (AI stocks, space stocks, Bitcoin/crypto as asset class, tech earnings). All standalone content in English. French ONLY when replying to French content. Goal = 20k followers. Be the best quant analyst AND funniest account on X.

---

## Quick context

Autonomous Twitter/X influencer bot. ~30 concurrent micro-bots managed by APScheduler in `main.py`. Browser-driven via Safari + AppleScript — no Twitter API key.

**Default AI provider: Ollama** (`AI_CLI=ollama`). Codex is the default backup when the local model fails.

To switch providers:

```bash
AI_CLI=codex ./bin/run.sh
echo "AI_CLI=codex" >> .env
```

The `src/llm_client.py` adapter handles each provider transparently. If the
primary returns a hard failure (non-zero exit, empty stdout) **or a soft
refusal** (exit 0 but body like `[no need to search for external sources…]`),
the same fallback ladder fires: `LLM_FALLBACK_CLI` / `LLM_FALLBACK_MODEL`,
then `OPENCODE_FALLBACK2_MODEL`. Refusal patterns live in
`_REFUSAL_PATTERNS` in `src/llm_client.py`.

News bursts are tuned via `NEWS_POSTS_PER_CYCLE` (default `3`); set to `1`
when the LLM is flaky so each cycle skips fast instead of grinding for 6+ min
on bad output.
Repost / quote volume is tuned high but bounded: `MAX_RETWEETS_PER_DAY=150`,
`RETWEETS_PER_CYCLE=15`, retweet job every 2 min, and the quote bot every
2 min (5 queries + 5 trusted handles per cycle to stay under the 2-min window).
Quote and repost discovery is English-first (2026-05-27 pivot): they scan
global high-signal EN AI / crypto / markets / space queries and EN trusted
handles first, with a short FR tail only for major French stories. Every
generated quote is in English.
Retweet and quote candidates still pass source, niche, age, min-like, respect
list, and dedup filters before posting.

**Catchup burst (2026-05-29):** On every startup, after the normal weekly/daily
Decode burst, the bot fires 3 extra rounds of RT → quote → spicy → breakout →
direct-reply back-to-back before the scheduler begins. Fills downtime gaps fast.

Impact tuning: top historical posts were concrete, numeric, named-actor
updates (Capital B funding/BTC buys, Saylor/Strategy BTC buys, ex-OpenAI
startup valuation). Prompts now explicitly prefer actor +
exact number + consequence, and avoid abstract standalone one-liners
that do not carry a verifiable fact.

Daily Decode schedule: cron at 07:00 `America/New_York` (`daily_news_job`).
Weekly fires at startup AND cron Fridays at 07:00 EST.
`MAX_NEWS_PER_DAY` caps the daily total; per-`(topic, format)` dedup
(`daily_topic_state.json`) prevents topic repetition across restarts.

**Scheduler hardening (2026-05-26):** `BlockingScheduler` runs with
`misfire_grace_time=3600`, `coalesce=True`, `max_instances=2`, and a
30-thread pool. APScheduler's defaults (`misfire_grace_time=1s`, 10 threads)
silently DROPPED once-a-day crons whenever a 600s LLM call saturated the
pool at the scheduled tick — so the daily news could skip the whole day.

Monthly recaps: `python main.py --monthly-recap-now` forces three Monthly
Décode Top 10 posts (IA, Crypto, Investissement). Scheduled monthly on the
1st at 8 AM New York. Big-post discovery is enabled for reposts/replies, but
freshness gates remain strict: reposts stay under `RETWEET_MAX_AGE_HOURS`,
direct replies under `DIRECT_REPLY_MAX_AGE_MINUTES`.

**Hard post-flight guard** (`contains_post_unsafe_leak` in `src/llm_client.py`,
wired into `twitter_client.post_tweet`): refuses to post anything containing
tool-call XML (`<function=…>`), NDJSON envelope keys (`"sessionID":`,
`"step_start"`, etc.), or text that opens with `{` / `[{`. Added after a
163k-char `{"type":"step_start",…}` blob got pushed to Safari on 2026-05-14
because the previous guard only caught XML, not JSON streams.

**`structured_output=True` flag (2026-05-28):** `run_llm()` and `unwrap_text()`
accept `structured_output=True` to bypass the `[{` safety guard when the caller
expects a JSON array (not a tweet). `reply_agent.py` uses this for `REPLY_SEARCH`
— without it, every Ollama JSON-array response was silently swallowed, causing
zero replies from search cycles.

**Safari black-screen recovery (2026-05-29):** `safari_hygiene._launch_safari()`
now calls `_warm_up_xcom()` after every relaunch: navigates to x.com, unregisters
all service workers, clears all caches, and hard-reloads. Prevents the stale-SW
blank app shell that made every scrape return `NO_ARTICLES`. Reactive path:
`twitter_client._record_blank_page()` counts consecutive blank-page responses;
after 5 in a row triggers `restart_safari("black_screen_recovery")` with a 5-min
cooldown (vs 30-min for preventive).

**Codex usage-limit lockout cache** (`codex_lockout.json` at repo root):
when codex returns "hit your usage limit, try again at …", `run_llm` parses
the date and caches it. Until that timestamp passes, codex is bypassed
entirely and calls go straight to the local Ollama fallback (`LLM_FALLBACK_CLI` /
`LLM_FALLBACK_MODEL`). Self-cleaning — the cache file is deleted when the
lockout window expires. Avoids the 6+ min per-cycle ladder cost while codex
is unavailable for days.

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
cp .env.example .env       # edit caps + handle
opencode auth              # or claude login / gemini login
./bin/run.sh               # foreground start, Ctrl-C to stop
```

For full operations playbook see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## Skills

User-invokable slash commands live under `.claude/skills/` (mirrored at `.codex/skills/`). 25 skills, each is a directory with a `SKILL.md` file:

- **Lifecycle**: `start`, `stop`, `restart`, `status`, `run-agent`
- **Manual triggers**: `post`, `reply`, `engage`, `boost`, `hotake`, `news`, `tweet`, `thread`, `dryrun`
- **Account ops**: `follow`, `like`, `accounts`, `history`
- **Telemetry**: `logs`, `stats`, `config`, `reset`, `improve`
- **Weekly strategy**: `strategy` — Claude-powered weekly review (style evolution + prompt tuning)

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
- **`safari_hygiene.py`** — preventive Safari quit+relaunch every 2h. Stops Safari from wedging after hours of `webbrowser.open()` + AppleScript JS. Cookies / localStorage / IndexedDB are file-based so login survives the restart.

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

`CONTENT_LANG_PRIMARY=en` (default since the 2026-05-27 pivot) → all standalone content (news, hot takes, breakouts, spicy, threads, quotes, reposts) in English. The quote bot's prompt is hardcoded English; repost/quote discovery is English-first (see `quote_tweet_bot.py` / `retweet_bot.py`).

Reply paths (`direct_reply`, `reply_bot`, `replyback_agent`, `viral_followup`, `spike`, `mega_watch`, `early_bird`) **always match parent tweet language** regardless of `CONTENT_LANG_PRIMARY` — so French replies still happen on French threads.

### Self-modification boundary

Agentic maintenance is disabled by default. These agents auto-rewrite project
state only when the matching feature flags are enabled (`ENABLE_AI_MAINTENANCE`
for strategy/evolution/reflection/meta/self-evolution, `ENABLE_AI_DISCOVERY`
for discovery/scout):

| Agent | Cadence | What it modifies |
|---|---|---|
| `meta_strategy_agent` | 4h | `live_strategy.json` (daily caps, cadence factor, topic focus) — min bounds prevent zeroing hot takes |
| `strategy_agent` | 3h | `dynamic_queries.json` + `dynamic_accounts.json` (additions only) |
| `evolution_agent` | 3h | `directives.md` + `pruned_accounts.json` + `reinforced_accounts.json` |
| `reflection_agent` | 6h | `personality.json` (per-account dossiers + topic positions) |
| `self_evolution_agent` | 4h | `bot_self_fr.json` + `bot_self_en.json` (mood, obsession, character_traits, en_voice, drift, self_narrative) |
| `scout_agent` | 4h | `dynamic_accounts.json` + auto-follows |
| `analyzer_bot` | 4h | `performance_insights.json` (top patterns, best hours, rising topics, viral examples) |
| `style_evolution_bot` | 168h (weekly) | `directives.md` — scrapes viral X formats, rewrites style guide with Claude Sonnet |
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
| `src/llm_client.py` | CLI adapter (OpenCode / Claude / Codex / Gemini) |
| `src/twitter_client.py` | Safari + AppleScript browser automation |
| `src/agent.py` etc. | Generation modules (one per content surface) |
| `core_identity.md` | Stable voice anchor |
| `personality.json` | Per-account dossiers (rewritten by reflection_agent when maintenance is enabled) |
| `bot_self.json` | Bot's evolving mood (rewritten by self_evolution_agent when maintenance is enabled) |
| `live_strategy.json` | Daily caps + cadence (rewritten by meta_strategy_agent when maintenance is enabled) |
| `directives.md` | Style guide (rewritten by evolution_agent when maintenance is enabled) |
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
