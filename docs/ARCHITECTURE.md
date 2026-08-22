# Architecture

This document is the engineering reference for the bot. For the runbook see [OPERATIONS.md](OPERATIONS.md); for env vars see [CONFIGURATION.md](CONFIGURATION.md).

---

## 1. System overview

The bot is a single Python process running an `APScheduler.BlockingScheduler` loop. ~30 jobs (each one a "bot") fire on independent intervals and serialize browser access via a single `_safari_lock` mutex inside `twitter_client.py`. The process never makes Twitter/X API calls; all interactions go through Safari + AppleScript JS-injection.

### Process model

```
main.py
   │
   ├── argparse → flags (--post-only, --reply-only, --dry-run)
   ├── signal handlers → SIGTERM/SIGINT → graceful scheduler.shutdown()
   ├── BlockingScheduler
   │     ├── 30+ IntervalTrigger jobs, each wrapped in safe_run_*
   │     └── Each safe_run_* calls health.record_success/failure
   │
   └── twitter_client._safari_lock (threading.RLock)
            └── serialises all Safari activations
```

### Data flow

```
                     ┌─────────────────────────┐
                     │   external_signal.json  │
        RSS  ─────┐  │  (RSS + HN + Reddit +   │
        HN   ─────┼──▶  X /home, top 30)       │
        Reddit ───┘  └────────────┬────────────┘
        X /home  ────────────────┘
                                  ▼
        ┌─── prompt assembly (original_content_engine.py / agents) ──┐
        │                                                           │
        │   1. lang_directive (en|fr) ── from lang_mode.py           │
        │   2. core_identity ── from core_identity.md                │
        │   3. bot_self ── from self_evolution_agent.json            │
        │   4. global_mood ── from personality.json                  │
        │   5. external_signal ── HN/RSS/Reddit/Home pulse           │
        │   6. follower_growth ── from follower_history.json         │
        │   7. pattern_stats ── from engagement_log + performance    │
        │   8. live_strategy ── from meta_strategy_agent (caps)      │
        │   9. directives.md ── from evolution_agent (style rules)   │
        │  10. hard_rules + respect_list (always last)               │
        │                                                           │
        └────────────┬──────────────────────────────────────────────┘
                     ▼
              run_llm() → configured CLI provider
                     ▼
              multi-candidate ranking + critics + humanizer/scrubbers
                     ▼
              twitter_client.post_tweet
                     ▼
              engagement_log.csv (with pattern attribution)
                     ▼
        performance.evaluate_and_learn (every 2h)
                     ▼
        evolution_agent / reflection_agent / meta_strategy_agent
                     ▼
        rewrite directives + dossiers + caps
                     ▼
        git_ops.auto_push (per agent)
```

---

## 2. Module catalog

63 modules. Grouped by responsibility.

### Content generation (standalone originals are the monetization layer)

| Module | Cadence | Output |
|---|---|---|
| `run_post_slot` (main.py) | cron slots across US hours ±15min jitter | ONE original per slot — tries `original_content_engine` first, then news/hotake → breakout → spicy → stunt, stops on the first landed post |
| `original_content_engine.py` | inside slots | Generates 15-30 standalone candidates, removes semantic duplicates, scores quality/originality/genericness/repetition/factuality, publishes only one winner above threshold |
| `main_post_growth.py` | startup + every 2h | Builds separate original/reply analytics, opportunity queue, rewards dashboard, editorial brief, approval queue, experiments |
| `agent.py` / `hotake_agent.py` | inside slots | News post / hot take (therapist-framed, no URL in body) |
| `breakout_bot.py` | inside slots | Fast-trend reaction post |
| `spicy_bot.py` | inside slots | Polarising take; QUESTION reply-bait capped 4/week |
| `viral_stunt_bot.py` | inside slots (leads 12:30) | Native-GIF meme original |
| `thread_bot.py` / `digest_thread_bot.py` / `recap_thread_bot.py` | DISABLED | threads aren't in the spec mix |

### Reshare (the QUALITY lane — operator focus 2026-06-07)

| Module | Cadence | Behavior |
|---|---|---|
| `quote_tweet_bot.py` | every 4 min | EN viral-query + curator-handle discovery → 50-like floor, 24h age, niche → the measured formula (re-denominate the number + mechanism metaphor + closing question) → ≤100/day chokepoint, screenshot-worthy or SKIP |
| `hot_quote_bot.py` | cron 8/12/16/20 NY ±10min | external_signal top story → most viral tweet about it → quote |
| `btc_blitz.py` (quote side) | startup + 6h | @TheBTCTherapist best ≤48h posts → AI-side inversion bit + GIF |
| `retweet_bot.py` | every 2 min | Plain RTs ≤2/day — reciprocity / MUST_REPOST (TheBTCTherapist) only |
| `notify_bot.run_boost_cycle` | every 20 min | Self-RT freshest own post (algo-window timing) |
| `boost_recycler_bot.py` | every 45 min | Winners (≥1 external like in 1h) → self-RT at 1h, then un-RT→re-RT every 4h+, max 4 cycles, ≤48h |

### Reply paths (the QUANTITY lane — unlimited, freshest-fast-rising first)

| Module | Cadence | Source |
|---|---|---|
| `direct_reply.py` | dynamic | Investor-psych + AI + markets searches, `from:` scans of seeds/foils; `_freshness_sort_key` orders <60-min risers first |
| `feed_sweeper_bot.py` | every 8 min | For You / Following: ≥100 likes → quote, below → reply |
| `btc_blitz.py` (reply side) | startup + 6h | EVERY ≤48h @TheBTCTherapist post (one reply per tweet, ever) |
| `early_bird_bot.py` | every 4-12 min | Curator top-30 (`account_curator.tracked_handles`), 12-min freshness window |
| `mega_watch_bot.py` | every 90s | Curator top-12, ≤4-min window, top-5-reply race |
| `replyback_agent.py` (in `notify_bot`) | every 8 min | Reply-back to people who reply to OUR tweets |
| `first_hour_babysitter.py` | every 10 min | Extra replyback sweeps while latest post <60 min old |
| `viral_followup_bot.py` | every 5 min | When own post gets traction, post follow-up |
| `spike_bot.py` | every 8 min | When own post hits ≥25 likes, orchestrate amplification |

### Follow / network (2026-06-07: operator-manual unfollows, curator-earned targets)

| Module | Cadence | Behavior |
|---|---|---|
| `marquee_follow_bot.py` (seed-follow) | every 15 min | Whitelist seeds in tier priority order, 1 attempt/cycle; display-name resolution before follow; chokepoint enforces 20/day, ≥10-min gaps, 300/150 total ceiling |
| `account_curator.py` | every 4h | Earns `tracked_accounts.json` from on-lane engagements × conversion weights (pins: TheBTCTherapist, Graphseo); promotes ≤3/day to whitelist `discovered` tier |
| `smart_unfollow_bot.py` | DISABLED (cap 0) | Operator unfollows manually (`bin/mass_unfollow.py` / `/unfollow` skill) |
| `follow_blast_bot.py` / `followback_bot.py` | OFF / cap 0 | whitelist-only mode blocks strangers at the chokepoint |
| `discover_bot.py` / `scout_agent.py` | every 2h / 4h | Discovery candidates → suggestions (never auto-follow outside the whitelist) |

### Like / promote

| Module | Cadence | Behavior |
|---|---|---|
| `like_bot.py` | every 15 min | JS-click ~18 likes on niche search results |
| `pin_bot.py` | every 6h (idempotent daily) | Auto-pin highest-likes own post via JS menu |
| `promote_bot.py` | every 3h | Plain-repost top recent reply onto profile |

### Real-time signal

| Module | Cadence | Source |
|---|---|---|
| `rss_signal_bot.py` | every 5 min | 20 trusted RSS feeds, parallel fetch |
| `hn_signal_bot.py` | every 20 min | HN front page + Reddit hot |
| `x_home_scout_bot.py` | every 7 min | /home niche-filter |
| `auto_tune_bot.py` | every 30 min | Per-source velocity gauge |
| `mega_watch_bot.py` (signal side) | every 90s | Top-10 mega-account fresh tweets |

### Autonomous self-modification

| Agent | Cadence | Output | Auto-push |
|---|---|---|---|
| `meta_strategy_agent.py` | 4h | `live_strategy.json` (caps, cadence, topic focus) | ✓ |
| `strategy_agent.py` | 3h | `dynamic_queries.json` + `dynamic_accounts.json` | ✓ |
| `evolution_agent.py` | 3h | `directives.md` + `pruned_accounts.json` + `reinforced_accounts.json` | ✓ |
| `reflection_agent.py` | 6h | `personality.json` (per-account dossiers + topic positions) | ✓ |
| `self_evolution_agent.py` | 4h | `bot_self.json` (mood, obsession, drift, self_narrative) | ✓ |
| `scout_agent.py` | 4h | `dynamic_accounts.json` + auto-follows | ✓ |

### Performance + telemetry

| Module | Cadence | Behavior |
|---|---|---|
| `original_content_engine.py` | every post slot attempt | Writes candidate decisions to `growth/original_post_decisions.json` and provenance to `growth/original_post_provenance.json` |
| `main_post_growth.py` | startup + every 2h | Writes `growth/main_post_analytics.json`, `growth/reply_analytics.json`, `growth/opportunity_queue.json`, `growth/home_timeline_500k_dashboard.json` |
| `performance.py` | every 2h | Scrape own profile metrics, write `performance_log.json` + `learnings.json`, compute pattern bandit |
| `daily_digest.py` | hourly (idempotent) | Append yesterday's rollup to `daily_digest.md` |
| `follower_tracker_bot.py` | every 30 min | Scrape /CryptoAIDecode header, log `follower_history.json` |
| `cleanup_bot.py` | hourly (idempotent) | Daily state hygiene — log rotation + JSON caps |
| `heartbeat_bot.py` | every 60s | Alive-tick log line |

Current impact bias: active prompts and repost scoring favor concrete,
numeric, named-actor updates over abstract one-liners. The data-backed pattern
is actor + exact number + consequence, e.g. BTC buys, funding, valuations,
capex, regulation, datacenter energy, and clear winners/losers.

### Safety + infrastructure

| Module | Purpose |
|---|---|
| `health.py` | Per-bot success/failure tracking; 3-fail Safari restart |
| `suppression_watch_bot.py` | Hourly engagement health check; pauses aggressive bots if avg likes drop |
| `respect_list.py` | Soft list of protected handles; output scrub before post |
| `personality_store.py` | Hard rules + per-account dossiers + bot self loader |
| `humanizer.py` | Strip AI artifacts (em dashes, robotic openers, agent preamble) |
| `pattern_tags.py` | Comedy-pattern enum + extract/scrub helpers |
| `lang_mode.py` | Bilingual content language picker |
| `git_ops.py` | Best-effort autonomous git push helper |
| `engagement_log.py` | CSV append-only log: ts, type, text, target_url, source, pattern |

---

## 3. Key invariants

These properties hold at every point in the bot's life cycle:

1. **No cycle ever crashes the scheduler.** Every `safe_run_*` wraps the body in try/except and reports to `health`.
2. **No state file is corrupted by partial write.** Every persistent file uses `json.dump` to a fully-formed dict; counter increments load-modify-save.
3. **No tweet is double-posted.** Every reply/post path has lock-URL-before-publish dedup against a persistent set.
4. **No protected handle is named in critical content.** The `respect_list.scrub_text_or_skip()` final-line defense rejects output containing `@<protected>` or bare-token + derisive marker.
5. **No pattern/source/image metadata leaks into a posted tweet.** `pattern_tags.extract_pattern` + `humanizer.strip_agent_preamble` + `twitter_client._scrub_metadata_leaks` form a 3-layer guard.
6. **No autonomous agent can move caps outside hard ranges.** `meta_strategy_agent._BOUNDS` clamps every output.
7. **No git commit is created on a failed cycle.** `auto_push` is called only after `health.record_success`.

---

## 4. Hard rules (immutable)

Two rules are stamped into every generation prompt via `personality_store.HARD_RULES_BLOCK`. They cannot be auto-rewritten by any agent:

1. **No illegal content** in any form.
2. **No trolling of US government / federal agencies** (Fed, SEC, IRS, FBI, DOJ, etc.). Commenting on the *facts* of their decisions is fine; mocking is not.

A third dynamic rule is added at runtime from `respect_list.json`: never criticize protected handles by name.

---

## 5. Self-modification boundary

What an agent CAN modify autonomously:

- `dynamic_queries.json` / `dynamic_accounts.json` (additions only)
- `directives.md` (overwritten each cycle)
- `pruned_accounts.json` (max 3 prunes/cycle, TTL 30d)
- `reinforced_accounts.json` (max 5/cycle, no TTL)
- `personality.json` (max 30 account updates / 10 topic updates per cycle)
- `bot_self.json` (max 5 voice_tweaks, 5 drift entries)
- `live_strategy.json` (caps clamped to bounds)

What it CANNOT touch:

- `core_identity.md` (the ideological spine)
- `BLOCKLIST` in `config.py`
- `respect_list.py` defaults (operator-managed)
- `personality_store.HARD_RULES_BLOCK`
- Quiet-hour boundaries
- Any source code (only state files)

---

## 6. Adding a new bot

1. Write `src/<your_bot>.py` exposing `safe_run_<your_bot>_cycle()`.
2. Inside `safe_run_*`, wrap the cycle body in try/except. Call `health.record_success/failure` at the end.
3. If the bot writes state files that should be visible in git, call `git_ops.auto_push([...], "message")` after success.
4. If the bot interacts with X via Safari, take `_safari_lock` before opening any URL and `close_front_tab` at the end.
5. Register in `main.py`:
   ```python
   from src.your_bot import safe_run_your_bot_cycle
   ...
   scheduler.add_job(
       safe_run_your_bot_cycle,
       trigger=IntervalTrigger(minutes=N),
       id="your_bot_job",
   )
   ```
6. If your bot has a daily cap, key it by `date.today().isoformat()` in a state file and short-circuit when reached.

---

## 7. Testing strategy

Modules are stateless or store JSON; the bot is exercised by running it. There are no traditional unit tests. The contract is:

- `python3 -c "import main"` must succeed (CI smoke test).
- `python3 -c "import src.<module>"` must succeed for every module.
- `./bin/run.sh` must boot through the AUTONOMY AUDIT block without exception within 10 seconds.

Any new bot must satisfy the same contract.
