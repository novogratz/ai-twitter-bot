# The AI Therapist — autonomous X/Twitter agent

[![guard-tests](https://github.com/novogratz/ai-twitter-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/novogratz/ai-twitter-bot/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/novogratz/ai-twitter-bot)](https://github.com/novogratz/ai-twitter-bot/releases)

> **Treating market trauma. AI-powered portfolio therapy. Follow the signal. Heal the fear.** ⚡

A fully autonomous X/Twitter influencer agent that runs, grows, and **improves its own codebase** without human intervention. It operates [@TheAIShrink](https://x.com/TheAIShrink) — a warm, data-sharp "therapist" persona for the AI era: name the fear, validate it, heal it with the precise fact.

No X API. The entire surface is driven through **Safari + AppleScript** browser automation on macOS, with local-first LLM generation (Ollama) and cloud fallback.

---

## What it does

**~35 concurrent micro-bots** orchestrated by a single APScheduler process (`main.py`):

| Layer | Bots | Role |
|---|---|---|
| **Content** | `agent`, `hotake_agent`, `breakout_bot`, `spicy_bot`, `viral_stunt_bot`, `thread_bot`, `longform_bot` | Original posts — sourced news, takes, threads, occasional viral-format comedy (stock-promo surface exists but is disabled) |
| **Amplification** | `retweet_bot`, `quote_tweet_bot`, `hot_quote_bot`, `feed_sweeper_bot` | Retweets + quote-posts of viral in-niche content (the highest-ROI surface); feed sweeping: good post → quote, weak post → reply |
| **Replies** | `direct_reply`, `reply_bot`, `engagement_targeting`, `early_bird_bot`, `mega_watch_bot`, `replyback_agent` | Real-time engagement on high-velocity threads; replies always match the parent tweet's language |
| **Network** | `engage_bot`, `discover_bot`, `followback_bot`, `smart_unfollow_bot`, `marquee_follow_bot` | Discovery, follows (30-day anti-churn both ways), reciprocity |
| **Signal** | `rss_signal_bot`, `hn_signal_bot`, `x_home_scout_bot`, `wsb_signal_bot` | RSS + HN + Reddit + X-feed trend aggregation into `external_signal.json` |
| **Self-tuning** | `meta_strategy_agent`, `strategy_agent`, `evolution_agent`, `reflection_agent`, `self_evolution_agent`, `analyzer_bot` | Periodic LLM runs that rewrite strategy, caps, persona dossiers, and style state |
| **Reliability** | `engine_health_bot`, `suppression_watch_bot`, `health.py`, `safari_hygiene` | Per-surface collapse detection, shadowban pause, Safari watchdog + preventive restarts |
| **Attribution** | `conversion_attribution_bot`, `performance.py`, `fast_feedback` | Learns which reply targets convert to followers; per-pattern engagement ROI |

## The autonomous improvement loop

The repo improves itself daily — code included:

```
DAILY 07:17 (launchd) ─────┐
COLLAPSE ALERT (self-heal) ┼──▶ headless Claude Code session
                           │      diagnose metrics → ONE focused change
                           │      → guard tests → PR → CI green → squash-merge
                           └──▶ learnings recorded to memory
```

- **`bin/auto_improve.sh`** — headless [Claude Code](https://claude.com/claude-code) run: reads `engagement_log.csv`, `engine_health_alerts.json`, and `bot.log`; ships one tested improvement **as a GitHub PR**; merges only when CI is green. Validated end-to-end ([PR #3](https://github.com/novogratz/ai-twitter-bot/pull/3), [PR #4](https://github.com/novogratz/ai-twitter-bot/pull/4) — #4 was diagnosed, fixed, tested, and merged with zero human involvement).
- **Self-healing** — `engine_health_bot` compares each surface's hourly pace to its 7-day baseline; a collapse triggers an emergency improvement run (6h cooldown, `ENABLE_SELF_HEAL=0` kill switch).
- **Guard tests + CI** — `tests/` runs in <1s, stdlib-only, on every push and PR (`.github/workflows/ci.yml`).
- **The operator keeps the keys** — autonomous runs never start the bot, never touch the persona spine, blocklists, or the 48h repost-freshness rule.

## Architecture in one diagram

```
┌──────────────── REAL-TIME SIGNAL ───────────────────┐
│  RSS (5m)   HN+Reddit (20m)   X feeds + searches    │
│                      ▼                              │
│             external_signal.json                    │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌──────────────── GENERATION (LLM) ───────────────────┐
│  news · takes · quotes · replies · threads · stunts │
│  voice: core_identity.md + bot_self + directives    │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌──────────────── WRITE CHOKEPOINTS ──────────────────┐
│  content_guard   → dedup v2 · price gate · language │
│  action_guard    → daily caps · jittered spacing    │
│  scrub pipeline  → metadata/tool-call leak removal  │
│  twitter_client  → Safari + AppleScript automation  │
└─────────────────────────────────────────────────────┘
```

Every write action funnels through `twitter_client` (`post_tweet` / `quote_tweet` / `reply_to_tweet` / `follow_account` / …) so all ~35 bots obey the same policy with no per-bot rewrites. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Safety model

- **Hard rules** baked into every prompt (no illegal content, no US-government trolling, protected-accounts respect list) — not overridable by autonomous agents
- **Dedup v2** at the chokepoints: stemmed-word similarity + shared-bigram + same-story-entity detection, so the account never posts the same thesis twice
- **No near-term price targets** — drafts pairing a price with a short timeframe are rejected pre-publish
- **48h repost-freshness rule** — hard-clamped in code; stale content is never reshared
- **Write pacing** — per-action daily caps with jittered spacing; no bursts (the browser-automation equivalent of API rate-limit hygiene)
- **Suppression watch** — auto-pauses aggressive surfaces if average engagement drops below the floor

## Quickstart

Requirements: macOS (Safari + AppleScript), Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) for local generation, [Claude Code](https://claude.com/claude-code) + [gh](https://cli.github.com) for the autonomous improvement loop.

```bash
git clone https://github.com/novogratz/ai-twitter-bot && cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env        # set BOT_HANDLE + caps
./bin/run.sh                # foreground start; Ctrl-C to stop
```

Run the guard tests:

```bash
.venv/bin/python -m pytest tests/ -q
```

Operate it:

| Task | How |
|---|---|
| Start / stop / status | `/start`, `/stop`, `/status` skills (Claude Code) or `bin/run.sh` |
| Dry run (no posting) | `DRY_RUN=1 ./bin/run.sh` |
| One manual improvement run | `./bin/auto_improve.sh` |
| Full ops playbook | [`docs/OPERATIONS.md`](docs/OPERATIONS.md) |
| Every config knob | [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) |

## Repository layout

```
main.py                 scheduler entry point — boots all bots
src/                    one module per bot + shared guards/clients
tests/                  guard-test suite (CI gate for agentic pushes)
bin/                    run.sh, auto_improve.sh, watchdog
docs/                   architecture, operations, configuration
.github/workflows/      CI (guard tests on every push/PR)
core_identity.md        the persona spine — never auto-rewritten
CLAUDE.md / CODEX.md    agent session context (kept in sync)
*.json (repo root)      bot state files, synced to git by the bot itself
```

> **Note on root-level `*.json` files:** they are the bots' persistent state (ledgers, dedup sets, learned weights). The running bot commits and pushes them autonomously — by design, so state survives reinstalls and stays auditable in history.

## License

[MIT](LICENSE) — © 2026 Benoit Floch.
