# AI Twitter Bot

An autonomous Twitter/X bot powered by Claude Code (default) or Codex CLI. Posts via browser automation (Safari + AppleScript on macOS).

## How It Works

Uses an installed AI CLI for generation (`AI_CLI=claude` by default, or `codex` / `gemini`) and Safari + AppleScript for browser automation. No Twitter API. Just log into X on Safari and go.

Default mode is Plus-safe: AI is used for content that actually ships (news, hot takes, replies, reply-backs, roasts, quote-tweets). Background scouting, strategy, reflection, discovery scoring, and retweet scoring are disabled or deterministic unless explicitly enabled.

### Bots

**Post Bot** - News + hot take publisher. News is capped at 12/day, hot takes at 4/day, both ship only if the story clears a 9/10 impact + comedy bar AND the source is in the FR-priority whitelist (Les Échos, Le Monde, BFM, Numerama, Usine Digitale, Siècle Digital, 01net, Frandroid, Presse-Citron, Maddyness, Cryptoast, Cointribune, Boursorama — EN fallback only if no FR angle exists in the last 48h). Format = sarcastic FR punchline + direct article URL so X renders the native link-card. No "Selon X..." / "Breaking:" / wire-service tone.

**Reply Bot** - Direct + search reply paths. Finds high-engagement FR tweets (with EN fallback), drops sharp one-liner replies (cap 18/cycle, impact-ranked — bumped from 7 on 2026-04-29 strategy pivot: replies are the only surface earning likes, so we max-out volume). **Source-aware engagement floor**: random-discovery sources (SEARCH-FR-LIVE, SEARCH-FR-HOT) skip tweets below `REPLY_MIN_LIKES` (default 5); curated paths (PROFILE-FR, FEED, FOLLOWING) bypass the floor entirely so the bot replies on EVERYTHING from the vetted 1k+ FR roster. Content blocklist (e.g. "se poser") still applies. FR priority, bilingual. **Replies are tagged with one of 6 comedy patterns** (REPETITION / DIALOGUE / METAPHOR / RENAME / FR_ANCHOR / UNDERSTATEMENT / OTHER) and logged into `engagement_log.csv` so the evolution agent can compute per-pattern ROI and steer style. **Graceful FR + QC quiet-hour fade**: Paris 04-07 = 95% skip (deepest dark), Paris 00-04 = 25% skip (= QC primetime, light-active for francophone Quebec audience), weekend Sat/Sun 8-11 = 30% skip.

**Engage Bot** - Auto-follows target accounts and likes their latest tweets. Static list + autonomously discovered handles + strategy-agent additions, all merged at runtime.

**Notify + Boost Bot** - Likes replies on own tweets every 35 min. Replies in-thread to influencer replies (dynamic 4-8/cycle by parent virality). Self-retweets every 2h (validated growth lever — pulled 200 views from one boost; cadence pushed 6h→4h→3h→2h as the lever kept working).

**Discover Bot** - Disabled by default in Plus-safe mode. If enabled, searches X for new FR AI/crypto/bourse handles and filters them with Python heuristics, no model call.

**Roast Bot** - Every ~12-17 min jittered: 1-roast-per-tweet sarcastic reply on @pgm_pm's original tweets. URL-deduped hard cap. **Circuit breaker** — 8 consecutive empty scrapes (target suspended/blocking us/private) → 24h pause, auto-resets so a recovery is detected within a day. Quiet hours skip. Roast model: Haiku (one-liners off fixed pattern, frees Sonnet/Opus budget).

**Safari Watchdog** - Every safe_run wrapper reports success/failure to `src/health.py`. After 3 consecutive failures (10-min cooldown), force-restarts Safari via osascript. Audit trail in `autonomous_log.md`. Stops the whole bot from going dark when Safari hangs.

**Performance Bot** - Scrapes own tweet metrics every 2h. Identifies top/worst performers, injects learnings into prompts.

**Strategy / Reflection / Evolution Agents** - Disabled by default in Plus-safe mode. Set `ENABLE_AI_MAINTENANCE=1` if you want the old autonomous analysis loops.

**Scout Agent** - Disabled by default in Plus-safe mode. Set `ENABLE_AI_DISCOVERY=1` to re-enable discovery/scouting.

**Evolution Agent (autonomous self-improvement, OUTPUT side)** - Every 6h: reads engagement_log + performance_log, identifies winning/losing patterns + dead/hot accounts, rewrites `directives.md` (loaded by all generation prompts), prunes accounts that produced 0 engagement (TTL 30d, max 3/cycle), reinforces accounts whose tweets converted into our top posts (max 5/cycle). Audit trail in `evolution_log.json`.

**Reflection Agent (autobiographical brain)** - Every 6h: reads engagement + history, updates `personality.json` — per-account dossiers (category, stance, feelings, notes) + per-topic positions. Replies become PERSONAL because the bot remembers each account.

**Quote-Tweet Bot** - Every 75 min, cap 10/day. FR-biased query pool (Mistral, Anthropic, Hugging Face, CAC40, Bercy/AMF/BdF) with one EN viral fallback. Lands in followers' feed AND notifies the original author — different distribution surface than replies.

**Retweet Bot** - Every 20 min, cap 60/day. FR-biased trusted-handle amplifier (26 FR press + 25 EN wires; per-cycle sample 14 FR + 4 EN). Scorer adds +2 for FR-language signal in tweet text and -1 to EN picks → EN must clear score ≥8 to retweet, FR ≥7. Picks ≥6 → retweet, ≥7 → logged to `daily_news_picks.md`.

**Thread Bot** - 1 well-crafted 4-tweet FR thread per day on the biggest IA/crypto/bourse story. Hook → fait → angle → chute + URL. Different distribution surface than single news (longer lifespan, screenshot RTs). Idempotent daily state.

**Promote Bot** - Quote-RTs our top recent reply onto the profile feed (cap 3/day, MIN_LIKES=5). Repackages proven content onto a different surface — replies hit but live inside other people's threads, this puts them on /kzer_ai.

**Follow-back Bot** - Scrapes /kzer_ai/followers and follows back fresh accounts (cap 8/cycle, every 2h). Reciprocity is the highest-leverage follower-growth tactic.

**Pin Bot** - Daily idempotent. Picks our highest-engagement own POST and pins it via JS menu click (FR + EN strings). Best-effort; falls back silently if the X menu DOM has shifted. A strong pinned tweet is the #1 follow-conversion lever.

**Daily Digest** - Hourly idempotent cron, writes one section per day to `daily_digest.md`: total actions, by-type breakdown, top sources, comedy patterns, top reply targets, top-perf posts, follow count delta. Built specifically for the 2-week post-mission review.

**Early-Bird Bot** - Every ~7 min jittered (12-min freshness window). Scans 3 random accounts from a 75-account roster, replies to any tweet < 12 min old. Cap 2 replies/cycle. Top-5 reply on a viral tweet = 10-100x impressions multiplier. Quiet hours skip.

### Cross-format topic dedup

`src/topic_dedup.py` is shared by news + hot take agents — entities (Claude, Bitcoin, OpenAI, etc.) recurring in the last 24-48h get hard-banned across BOTH formats so the audience never sees the same topic twice in two different posts.

### Hard rules (immutable)

Two rules stamped into every generation prompt via `personality_store.HARD_RULES_BLOCK`:
1. Aucun contenu illegal sous aucune forme.
2. Aucun troll / mocking / attaque du gouvernement americain (US government, Fed, SEC, CFTC, IRS, FBI, DOJ, presidents). Commenter des FAITS OK, attaquer NON.

## Setup

```bash
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code
claude login
```

For ChatGPT Plus / Codex CLI:

```bash
codex login
```

Log into X/Twitter on Safari. That's it.

## Usage

### Option 1: Python Scheduler (autonomous)

```bash
python main.py              # Run all bots 24/7
python main.py --post-only  # Only post news + hot takes
python main.py --reply-only # Only reply to tweets
python main.py --dry-run    # Preview without posting
```

### Option 2: Claude Code Agent (interactive)

Run the bot as a Claude Code agent with full control:

```bash
claude                      # Open Claude Code in the project
/run-agent                  # Start the agent loop
/loop                       # Keep it running autonomously
```

### Slash Commands

Full bot control from Claude Code:

| Command | Description |
|---------|-------------|
| `/run-agent` | Run the bot as a native Claude Code agent |
| `/post` | Trigger a post cycle |
| `/reply` | Trigger a reply cycle |
| `/hotake` | Generate and preview a hot take |
| `/news` | Preview a news tweet before posting |
| `/tweet` | Post a specific tweet |
| `/thread` | Post a multi-tweet thread |
| `/engage` | Follow and like target accounts |
| `/boost` | Self-retweet latest tweet |
| `/follow` | Follow a specific account |
| `/like` | Like someone's latest tweets |
| `/stats` | Full engagement dashboard |
| `/status` | Quick bot health check |
| `/logs` | View recent bot activity |
| `/history` | View tweet and reply history |
| `/accounts` | Manage target accounts list |
| `/config` | View and edit bot settings |
| `/reset` | Reset daily counters |
| `/dryrun` | Preview a full cycle without posting |
| `/start` | Start the bot in background |
| `/stop` | Stop the bot gracefully |
| `/restart` | Restart the bot |
| `/improve` | Run performance evaluation |

## Configuration

All settings in `src/config.py`, overridable with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_NEWS_PER_DAY` | 12 | Max standalone news posts per day |
| `MAX_HOTAKES_PER_DAY` | 4 | Max hot takes per day |
| `MAX_RETWEETS_PER_DAY` | 20 | Max selective retweets per day |
| `RETWEET_MIN_LIKES` | 5 | Min likes on a candidate retweet |
| `MAX_QUOTES_PER_DAY` | 10 | Max quote-tweets per day |
| `MAX_REPLIES_PER_CYCLE` | 6 | Max search replies per cycle |
| `REPLY_MIN_LIKES` | 2 | Min likes on a tweet before the bot will reply (random-search sources only — curated paths bypass) |
| `AI_CLI` | claude | `claude`, `codex`, or `gemini` |
| `NEWS_MODEL` | claude-sonnet-4-6 | Model for high-impact news posts |
| `REPLY_MODEL` | claude-sonnet-4-6 | Model for replies |
| `PRIORITY_REPLY_MODEL` | claude-sonnet-4-6 | Model for user-VIP account replies |
| `HOTAKE_MODEL` | claude-sonnet-4-6 | Model for hot takes |
| `QUOTE_MODEL` | claude-haiku-4-5 | Model for quote-tweets (cheap one-liners) |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | 45 | Local spacing between model calls |
| `LLM_MAX_CALLS_PER_HOUR` | 60 | Local hourly model-call budget across bot threads |
| `ENABLE_AI_MAINTENANCE` | 0 | Re-enable strategy/evolution/reflection model calls |
| `ENABLE_AI_DISCOVERY` | 0 | Re-enable discovery/scout jobs |

### Customizing for Your Niche

Configured for AI/crypto/finance but adaptable to any topic:

1. **`src/agent.py`** - News prompt: search terms, examples, tone
2. **`src/hotake_agent.py`** - Hot take prompt: topics, formats, examples
3. **`src/reply_agent.py`** - Reply prompt: search terms, target accounts, style
4. **`src/engage_bot.py`** - Target accounts list
5. **`src/config.py`** - Bot handle and limits
6. **`.claude/skills/run-agent/SKILL.md`** - Agent behavior and personality

## Architecture

```
main.py                      # Python entry point, APScheduler
.claude/
  skills/                    # 22 slash commands for Claude Code
    run-agent/SKILL.md       # Main agent loop
    post/SKILL.md            # Manual post trigger
    reply/SKILL.md           # Manual reply trigger
    ...
src/
  config.py                  # Central config, env var overrides
  logger.py                  # Rotating file logs (5MB, 3 backups)
  agent.py                   # News tweet generation (Opus + WebSearch)
  hotake_agent.py            # Hot take generation (Sonnet)
  reply_agent.py             # Reply generation (Sonnet + WebSearch)
  replyback_agent.py         # Reply-back generation
  bot.py                     # Post orchestration, daily limits
  reply_bot.py               # Reply orchestration, dedup
  engage_bot.py              # Auto-follow + like engine
  notify_bot.py              # Notification + boost
  performance.py             # Self-improving metrics system (every 2h)
  strategy_agent.py          # Autonomous self-improvement INPUT side (agentic, every 3h)
  evolution_agent.py         # Autonomous self-improvement OUTPUT side (agentic, every 6h)
  evolution_store.py         # directives.md + pruned/reinforced account stores
  reflection_agent.py        # Autobiographical brain — personality.json (every 6h)
  personality_store.py       # Per-account/per-topic dossiers + HARD_RULES_BLOCK
  topic_dedup.py             # Shared cross-format banlist (news + hot take)
  dynamic_strategy.py        # Append-only stores for strategy-agent additions
  quote_tweet_bot.py         # Quote-tweet path (cap 30/day, every 35 min)
  early_bird_bot.py          # Top-5-reply path on fresh viral tweets (cap 4/cycle)
  retweet_bot.py             # Selective retweets of trusted news (cap 60/day, every 20 min)
  thread_bot.py              # 1 FR thread/day on biggest IA story (idempotent, every 4h)
  promote_bot.py             # Quote-RT our top recent reply (cap 3/day, every 3h)
  followback_bot.py          # Scrape followers, follow back (cap 8/cycle, every 2h)
  pin_bot.py                 # Auto-pin best own post (daily idempotent, every 6h)
  discover_bot.py            # Autonomous handle discovery (every 3h)
  roast_pgm_bot.py           # Dedicated 1-roast-per-tweet for @pgm_pm
  image_gen.py               # PNG quote-card generator (Pillow)
  twitter_client.py          # Safari/AppleScript browser automation
  history.py                 # Tweet history, dedup (capped at 500)
  engagement_log.py          # CSV engagement tracking with source attribution
```

## Requirements

- macOS (browser automation uses AppleScript + Safari)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on Safari
