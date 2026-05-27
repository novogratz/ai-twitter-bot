# kzer — autonomous Twitter/X growth agent

> 🤖 **Infos IA et Crypto, avant tout le monde. Analyses pointues. Zéro bullshit, zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison.** ⚡

> **Positioning 2026-05-24:** English standalone content. Core niche = AI infrastructure & asymmetric investing: power demand, MW/GW capacity, compute wars, AI infra stocks, energy, robotics, space, frontier tech, and crypto linked to AI.

A self-evolving Twitter/X agent. Posts breaking news, replies in real time, amplifies signal, and manages its own follower-ratio. Agentic strategy/persona rewrites are available but disabled by default so LLM calls are spent on production content first. Driven by Claude Code (or Codex / Gemini CLI). No Twitter API key. Browser automation only.

---

## What it does

The bot operates **30+ concurrent micro-bots** orchestrated by an APScheduler loop. Each bot owns one job:

| Layer | Bots | Purpose |
|---|---|---|
| **Content** | `agent`, `hotake_agent`, `breakout_bot`, `spicy_bot`, `thread_bot`, `digest_thread_bot` | Original posts — news, daily/weekly/monthly Décodes, hot takes, threads |
| **Reshare** | `retweet_bot`, `quote_tweet_bot`, `notify_bot` (boost) | Amplify trusted-source and big visible posts with same-day + niche filters; quote posts are FR-first and add our own angle |
| **Reply** | `direct_reply`, `reply_bot`, `early_bird_bot`, `mega_watch_bot`, `replyback_agent`, `viral_followup_bot`, `spike_bot`, `roast_pgm_bot` | Real-time engagement on viral tweets, mega-account top-5-reply window |
| **Follow** | `engage_bot`, `discover_bot`, `scout_agent`, `follow_blast_bot`, `followback_bot`, `smart_unfollow_bot` | Network growth — discover, follow, follow-back, prune non-reciprocal |
| **Like** | `like_bot`, `notify_bot` | Bulk likes for outbound notifications |
| **Promote** | `pin_bot`, `promote_bot` | Auto-pin best post, plain-repost top reply onto profile |
| **Real-time signal** | `rss_signal_bot`, `hn_signal_bot`, `x_home_scout_bot`, `auto_tune_bot` | Aggregate trends from RSS + HN + Reddit + X home; 20-50 min ahead of WebSearch |
| **Self-evolution** | `meta_strategy_agent`, `strategy_agent`, `evolution_agent`, `reflection_agent`, `self_evolution_agent` | Optional agentic runs that rewrite strategy, persona, dossiers; gated by `ENABLE_AI_MAINTENANCE` / `ENABLE_AI_DISCOVERY` |
| **Safety** | `suppression_watch_bot`, `health.py`, `respect_list` | Shadowban detection + Safari watchdog + protected-handle list |
| **Hygiene** | `cleanup_bot`, `heartbeat_bot`, `daily_digest`, `follower_tracker_bot`, `performance.py` | State rotation, alive ticks, growth metrics, learnings |

---

## Architecture at a glance

```
┌──────────────────── REAL-TIME SIGNAL LAYER ────────────────────┐
│  RSS feeds (5m)   HN+Reddit (20m)   X /home (7m)   Trusted-handle│
│        │                │                │              │        │
│        └────────────┬───┴────────────────┘              │        │
│                     ▼                                   ▼        │
│             external_signal.json              retweet_bot/quote  │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── GENERATION LAYER ────────────────────────────────┐
│   agent (news)   hotake   breakout   spicy   thread   digest    │
│        │            │         │        │        │        │      │
│        └────────────┴─────┬───┴────────┴────────┴────────┘      │
│                           ▼                                     │
│                  twitter_client.post_tweet                      │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── ENGAGEMENT LAYER ────────────────────────────────┐
│  direct_reply  reply_bot  early_bird  mega_watch  replyback    │
│  viral_followup  spike  engage  follow_blast  like  unfollow    │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── ADAPTATION LAYER (auto-pushes to git) ───────────┐
│  meta_strategy(4h)  strategy(3h)  evolution(3h)                 │
│  reflection(6h)     self_evolution(4h)  scout(4h)               │
│  performance(2h)    auto_tune(30m)                              │
│        │                                                         │
│        ▼                                                         │
│  live_strategy.json | bot_self.json | personality.json |        │
│  directives.md | dynamic_*.json | learnings.json                │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── SAFETY + HYGIENE LAYER ──────────────────────────┐
│  suppression_watch  health(Safari watchdog)  respect_list       │
│  cleanup  heartbeat  daily_digest  follower_tracker             │
└─────────────────────────────────────────────────────────────────┘
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full lattice.

---

## Quick start

**Requirements**

- macOS (Safari + AppleScript automation, browser-driven, no API key)
- Python 3.10+
- Ollama running locally, with Codex CLI (`codex`) authenticated as backup
- Twitter/X account logged into Safari

**Install**

```bash
git clone https://github.com/<you>/ai-twitter-bot.git
cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env  # then edit caps + model + handle
```

**Run (foreground)**

```bash
./bin/run.sh        # Ctrl-C to stop
```

**Stop from any other terminal**

```bash
./bin/stop.sh
```

**Watch the logs**

```bash
tail -F bot.log
```

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for full runbook (autonomy mode, debugging, tuning).

---

## Configuration

Every knob is an environment variable in `.env`. Defaults are tuned for an English-content / global-audience build with conservative caps.

| Variable | Default | What it does |
|---|---|---|
| `BOT_HANDLE` | `CryptoAIDecode` | Your X handle (without `@`) |
| `AI_CLI` | `ollama` | `ollama` / `codex` / `opencode` / `claude` / `gemini` |
| `NEWS_MODEL` | `gpt-5.4-mini` | Model for news + threads; override for manual quality runs |
| `HOTAKE_MODEL` | `gpt-5.4-mini` | Model for hot takes + breakouts |
| `REPLY_MODEL` | `gpt-5.4-mini` | Model for replies (volume surface) |
| `LLM_ENFORCE_BUDGET` | `0` | `0` = soft accounting only; `1` = hard-stop local LLM calls at configured budgets |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | `15` | Spacing guardrail to avoid bursty overlapping CLI calls |
| `MAX_NEWS_PER_DAY` | `5` | Cap on Décode insight posts |
| `NEWS_POSTS_PER_CYCLE` | `3` | News posts to burst per cycle; set to `1` for one-shot (fail → skip) |
| `MAX_HOTAKES_PER_DAY` | `3` | Cap on quick takes |
| `MAX_QUOTES_PER_DAY` | `80` | Cap on quote posts from the FR-first quote bot |
| `MAX_RETWEETS_PER_DAY` | `30` | Cap on retweets |
| `RETWEETS_PER_CYCLE` | `3` | Max external retweets shipped after each candidate scrape |
| `MAX_REPLIES_PER_CYCLE` | `3` | Cap per broad reply cycle; direct replies target 20-50 quality replies/day |
| `CONTENT_LANG_PRIMARY` | `fr` | `en` / `fr` / `mixed` (replies always match parent) |
| `RETWEET_MAX_AGE_HOURS` | `18` | Skip retweet candidates older than this |
| `SUPPRESSION_AVG_LIKES_FLOOR` | `1.0` | Trigger shadowban-pause if avg drops below |

Full reference: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

---

## Project structure

```
ai-twitter-bot/
├── main.py                  # APScheduler entry point — boots all 30+ bots
├── bin/
│   ├── run.sh               # Foreground start
│   ├── stop.sh              # SIGTERM all bot processes
│   ├── install_autonomous.sh   # macOS LaunchAgent (auto-respawn + boot-start)
│   └── uninstall_autonomous.sh
├── launchd/
│   └── com.kzer.ai-twitter-bot.plist
├── docs/
│   ├── ARCHITECTURE.md      # Full bot lattice, data flow, key invariants
│   ├── OPERATIONS.md        # Runbook — start, watch, debug, tune
│   └── CONFIGURATION.md     # Every env var explained
├── src/
│   ├── config.py            # Central config + live-cap reader
│   ├── llm_client.py        # CLI adapter (OpenCode / Claude / Codex / Gemini)
│   ├── twitter_client.py    # Safari + AppleScript browser automation
│   ├── agent.py             # News generation
│   ├── hotake_agent.py      # Hot take generation
│   ├── reply_agent.py       # Reply generation
│   ├── replyback_agent.py   # In-thread reply-back
│   ├── humanizer.py         # Deterministic AI-artifact stripping
│   ├── lang_mode.py         # Bilingual content language picker
│   ├── pattern_tags.py      # Comedy-pattern bandit attribution
│   ├── git_ops.py           # Autonomous git push helper
│   ├── health.py            # Safari watchdog
│   ├── personality_store.py # Per-account dossiers + hard rules
│   ├── respect_list.py      # Protected-handle list
│   ├── ... (45+ other bots — see docs/ARCHITECTURE.md for catalog)
└── core_identity.md         # Stable ideological spine (loaded into every prompt)
```

63 Python modules, ~10k LOC. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the per-module map.

---

## Design principles

1. **Process safety > feature parity.** Every cycle is wrapped in `safe_run_*` so a single-cycle exception cannot crash the scheduler. Health watchdog auto-restarts Safari after 3 consecutive cycle failures. The `BlockingScheduler` runs with a 30-thread pool and `misfire_grace_time=3600` + `coalesce=True` so a long (≤600s) LLM call saturating the pool can never silently drop a time-sensitive job — once-a-day crons (daily Décode, morning recap) still fire when a worker frees up instead of skipping the day.
2. **Autonomous self-modification with bounded blast radius.** Agentic maintenance is disabled by default. When enabled, `meta_strategy_agent` can rewrite daily caps only within hard-coded ranges (`news 4-8`, `retweet 8-30`). Every self-modifying agent auto-commits + pushes its state files to git so every change is audit-trailed.
3. **Idempotent state.** All daily-counter files (`thread_daily_state`, `pin_daily_state`, etc.) are JSON-keyed by date. A restart mid-day picks up exactly where it left off; the bot never double-posts.
4. **Best-effort UI automation.** Every JS-click into the X DOM is wrapped in try/except with a fallback path. When X reshuffles its DOM, the bot logs and skips that one cycle — it never crashes.
5. **Bandit attribution baked in.** Every generated tweet carries a `[PATTERN: <ID>]` metadata line that's stripped pre-post and logged to `engagement_log.csv` column 6. The `evolution_agent` reads these to compute per-pattern ROI and rewrite the style guide.
6. **Concrete impact beats abstract wit.** Saved performance data shows named actors + exact numbers + real consequences outperform standalone punchlines, so prompts bias toward naming actors, amounts, BTC counts, valuations, capex, regulation, and clear winners/losers.
7. **Soft + hard list separation.** `BLOCKLIST` (hard, never engage) is for actual bad actors. `respect_list` (soft, engage but never criticize by name) is for influencers we shouldn't risk offending.

---

## Real-time signal pipeline

The bot's "before everyone else" claim runs on a fan-in signal pipeline:

```
RSS (5m)    → 20 trusted-outlet feeds, 8-thread parallel fetch (~1s wall)
HN/Reddit (20m) → HN front page + r/MachineLearning + r/CryptoCurrency
X /home (7m) → home-feed niche-filter
              ↓
     external_signal.json (top 30, sorted by recency desc)
              ↓
   agent.py + hotake_agent.py + breakout_bot.py inject as prompt context
```

WebSearch (Google indexing) lags publication by 30-60 min. RSS publishes within seconds. Net effect: news prompt sees the scoop **20-50 min** before WebSearch surfaces it.

---

## Autonomous self-modification

Six maintenance agents can run on cron schedules when enabled. They are off by default because they spend LLM calls; deterministic research/signal bots keep running without them. Each enabled agent writes its decisions to a JSON/MD state file AND auto-pushes to git so every adjustment is version-controlled:

| Agent | Cadence | Decides | State file |
|---|---|---|---|
| `meta_strategy_agent` | 4h | Daily caps, cadence factor, topic focus | `live_strategy.json` |
| `strategy_agent` | 3h | New search queries + accounts to engage | `dynamic_*.json` |
| `evolution_agent` | 3h | Style directives, prune/reinforce | `directives.md` + `*_accounts.json` |
| `reflection_agent` | 6h | Per-account dossiers (category, stance, feelings) | `personality.json` |
| `self_evolution_agent` | 4h | Bot's mood / obsession / drift / voice tweaks | `bot_self.json` |
| `scout_agent` | 4h | New FR/EN voices to monitor + auto-follows | `dynamic_accounts.json` |

Each is bounded: the meta-strategy agent can only set caps within `[lo, hi]` ranges; `evolution_agent` caps prunes at 3/cycle and reinforces at 5/cycle; `scout_agent` caps auto-follows at 3/cycle. A bad cycle degrades gracefully.

---

## Safety architecture

- **`BLOCKLIST`** (hard) — handles the bot will never engage with under any circumstance.
- **`respect_list.py`** (soft) — influencers the bot can engage but must never criticize by name. Output scrubs at every content-bot's post path. Default-seeded with 30 high-traction FR/EN voices.
- **`personality_store.HARD_RULES_BLOCK`** — two non-negotiable rules stamped into every generation prompt: (1) no illegal content, (2) no trolling US government / federal agencies.
- **`suppression_watch_bot`** — hourly engagement health check; if avg likes drop below floor, pauses aggressive bots (`spicy`, `breakout`, `follow_blast`) for 4h.
- **`health.py`** — Safari watchdog; force-restarts Safari after 3 consecutive cycle failures.
- **`safari_hygiene.py`** — preventive Safari quit+relaunch every 2h to stop Safari from wedging after hours of automation. Force-kills lingering WebKit helpers; cookies/localStorage persist so login survives.

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full bot lattice + module catalog
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — runbook + debugging + tuning playbook
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — env var reference
- [`CLAUDE.md`](CLAUDE.md) — project-context for Claude Code sessions
- [`core_identity.md`](core_identity.md) — bot's stable ideological spine (loaded into every prompt)

---

## License

MIT. See [`LICENSE`](LICENSE).
