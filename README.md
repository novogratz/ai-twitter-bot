# AI Twitter Bot

An autonomous Twitter/X bot powered by Claude Code. No API keys needed. Posts via browser automation (Safari + AppleScript on macOS).

## How It Works

Uses Claude Code CLI for AI generation and Safari + AppleScript for browser automation. No Twitter API, no Anthropic API key. Just log into X on Safari and go.

### Bots

**Post Bot** - Searches the web for breaking news (AI, crypto, bourse), writes sharp FR tweets. **News format = MEME HOT TAKE + URL**: a screenshot-worthy punchline first, raw article URL on its own line so X renders the link card. No "Selon X..." / "Breaking:" / news-report style — if the news doesn't lend itself to a meme, the bot SKIPs. FIRST-DERIVATIVE rule: reject angles BFM/Bloomberg would post as-is, find the second-order implication. Threads supported. Mix of news (24/day) + hot-take memes (24/day). News-first policy: first 3 posts/day must be news. **HARD RULE 2026-04-26 PM — SOURCE OR SKIP**: per user directive, both news AND hot takes require a real article URL (≤72h, direct link, not paywalled). Hot take agent uses WebSearch to anchor every meme on a real recent event; without a URL the cycle SKIPs rather than ship a sourceless meme. Hot takes WITH a URL skip the image attach so X renders the native link-card cleanly (image+headline+domain). Replies are EXEMPT from this rule.

**Post Bot** - News + hot take publisher (cap 4/day each — cut hard 2026-04-29 because 51% of original posts got 0 likes). **Source-as-self-reply pattern** (2026-04-29): the URL is stripped out of the main tweet body and posted as a self-reply via `post_thread()`. X deboosts inline outbound links by ~30-50% (confirmed cause of the 0-likes pattern); the main tweet now ships URL-free with a quote-card visual for max algorithmic reach, and the source URL appears as reply #1 to preserve credibility. Quote card is always attached on news + hot takes.

**Reply Bot** - Direct + search reply paths. Finds high-engagement FR tweets (with EN fallback), drops sharp one-liner replies (cap 18/cycle, impact-ranked — bumped from 7 on 2026-04-29 strategy pivot: replies are the only surface earning likes, so we max-out volume). **Source-aware engagement floor**: random-discovery sources (SEARCH-FR-LIVE, SEARCH-FR-HOT) skip tweets below `REPLY_MIN_LIKES` (default 5); curated paths (PROFILE-FR, FEED, FOLLOWING) bypass the floor entirely so the bot replies on EVERYTHING from the vetted 1k+ FR roster. Content blocklist (e.g. "se poser") still applies. FR priority, bilingual. **Replies are tagged with one of 6 comedy patterns** (REPETITION / DIALOGUE / METAPHOR / RENAME / FR_ANCHOR / UNDERSTATEMENT / OTHER) and logged into `engagement_log.csv` so the evolution agent can compute per-pattern ROI and steer style. **Graceful FR + QC quiet-hour fade**: Paris 04-07 = 95% skip (deepest dark), Paris 00-04 = 25% skip (= QC primetime, light-active for francophone Quebec audience), weekend Sat/Sun 8-11 = 30% skip.

**Engage Bot** - Auto-follows target accounts and likes their latest tweets. Static list + autonomously discovered handles + strategy-agent additions, all merged at runtime.

**Notify + Boost Bot** - Likes replies on own tweets every 35 min. Replies in-thread to influencer replies (dynamic 4-8/cycle by parent virality). Self-retweets every 2h (validated growth lever — pulled 200 views from one boost; cadence pushed 6h→4h→3h→2h as the lever kept working).

**Discover Bot** - Every 3h: searches X for new FR AI/crypto/bourse handles, scores with Claude, persists approved ones, auto-follows the best FR ones. `follow_account` returns a bool so a transient JS-click failure (Safari race) leaves the handle out of `followed_accounts.json` and gets retried next cycle instead of being silently dropped.

**Roast Bot** - Every ~12-17 min jittered: 1-roast-per-tweet sarcastic reply on @pgm_pm's original tweets. URL-deduped hard cap. **Circuit breaker** — 8 consecutive empty scrapes (target suspended/blocking us/private) → 24h pause, auto-resets so a recovery is detected within a day. Quiet hours skip. Roast model: Haiku (one-liners off fixed pattern, frees Sonnet/Opus budget).

**Safari Watchdog** - Every safe_run wrapper reports success/failure to `src/health.py`. After 3 consecutive failures (10-min cooldown), force-restarts Safari via osascript. Audit trail in `autonomous_log.md`. Stops the whole bot from going dark when Safari hangs.

**Performance Bot** - Scrapes own tweet metrics every 2h. Identifies top/worst performers, injects learnings into prompts.

**Strategy Agent (autonomous self-improvement, INPUT side)** - Every 3h: agentic Claude run with Read + WebSearch + Bash tools. Reads `engagement_log.csv` (per-source ROI), looks up live FR AI/crypto/bourse trends, proposes new search queries + accounts. Python applies ADDITIONS only — never removes. Outputs land in `dynamic_queries.json` / `dynamic_accounts.json` and are merged at runtime by the reply bot. **No human in the loop.** Audit trail in `strategy_log.json`.

**Scout Agent (open-web FR-speaker recruitment)** - Every 4h: agentic Claude run with WebSearch + WebFetch tools. Investigates the open web for the BEST FR-speaking AI / crypto / bourse / fintech / tech accounts in **France, Quebec, and the USA**. Filters by ≥5k followers, dedups against every known list, appends keepers to `dynamic_accounts.json` FR bucket, and AUTO-FOLLOWS the top picks (cap 3/cycle). Different signal than the Strategy Agent (engagement-log-based) and Discover Bot (X-search-based) — this one finds hidden gems via classements, blogs, lists. Audit trail in `scout_log.json`.

**Evolution Agent (autonomous self-improvement, OUTPUT side)** - Every 6h: reads engagement_log + performance_log, identifies winning/losing patterns + dead/hot accounts, rewrites `directives.md` (loaded by all generation prompts), prunes accounts that produced 0 engagement (TTL 30d, max 3/cycle), reinforces accounts whose tweets converted into our top posts (max 5/cycle). Audit trail in `evolution_log.json`.

**Reflection Agent (autobiographical brain)** - Every 6h: reads engagement + history, updates `personality.json` — per-account dossiers (category, stance, feelings, notes) + per-topic positions. Replies become PERSONAL because the bot remembers each account.

**Quote-Tweet Bot** - Every 75 min, cap 12/day: picks the most viral FR tweet in our niches (min_faves:30, top tab) and quote-tweets it with a sharp meme observation. Different distribution surface than replies. Quote model: Haiku.

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
| `MAX_NEWS_PER_DAY` | 4 | Max news posts per day (cut 24→4 on 2026-04-29 — replies are the only converting surface, news/hot takes were 0-engagement noise) |
| `MAX_HOTAKES_PER_DAY` | 4 | Max hot takes per day (same cut as news) |
| `MAX_QUOTES_PER_DAY` | 12 | Max quote-tweets per day |
| `MAX_REPLIES_PER_CYCLE` | 18 | Max replies per cycle (bumped 12→18 — replies are the engine) |
| `REPLY_MIN_LIKES` | 2 | Min likes on a tweet before the bot will reply (random-search sources only — curated paths bypass) |
| `NEWS_MODEL` | claude-opus-4-6 | Model for news posts |
| `REPLY_MODEL` | claude-opus-4-6 | Model for replies (upgraded from sonnet-4-6 on 2026-04-29 — replies convert, FR humor benefits from Opus) |
| `HOTAKE_MODEL` | claude-opus-4-6 | Model for hot takes |

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
  quote_tweet_bot.py         # Quote-tweet path (cap 12/day, every 90 min)
  early_bird_bot.py          # Top-5-reply path on fresh viral tweets
  retweet_bot.py             # Selective retweets of trusted news (cap 8/day, every 95 min)
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
