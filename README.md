# AI Twitter Bot

An autonomous Twitter/X bot powered by Claude Code. No API keys needed. Posts via browser automation (Safari + AppleScript on macOS).

## How It Works

Uses Claude Code CLI for AI generation and Safari + AppleScript for browser automation. No Twitter API, no Anthropic API key. Just log into X on Safari and go.

### Bots

**Post Bot** - Searches the web for breaking news (AI, crypto, bourse), writes sharp FR tweets in SETUP→PUNCH format (factual setup, sarcastic punch — sourced article without a joke = failure). Threads supported. Mix of news (10/day) + hot-take memes (4/day). News-first policy: first 3 posts/day must be news. Hot takes ship with a generated PNG quote-card for screenshot-worthy feed presence.

**Reply Bot** - Direct + search reply paths. Finds high-engagement FR tweets (with EN fallback), drops sharp one-liner replies every ~30 min jittered (cap 2/cycle, impact-ranked). Skips dead tweets (0 likes AND 0 replies). FR priority, bilingual. **Quiet hours 1am-7am Paris** — engagement cycles skip overnight so the account looks human.

**Engage Bot** - Auto-follows target accounts and likes their latest tweets. Static list + autonomously discovered handles + strategy-agent additions, all merged at runtime.

**Notify + Boost Bot** - Likes replies on own tweets every 45 min. Replies in-thread to influencer replies (cap 3/cycle). Self-retweets every 6h (validated growth lever — pulled 200 views from one boost).

**Discover Bot** - Every 6h: searches X for new FR AI/crypto/bourse handles, scores with Claude, persists approved ones, auto-follows the best FR ones.

**Roast Bot** - Every 10 min: 1-roast-per-tweet sarcastic reply on @pgm_pm's original tweets. URL-deduped hard cap.

**Performance Bot** - Scrapes own tweet metrics every 2h. Identifies top/worst performers, injects learnings into prompts.

**Strategy Agent (autonomous self-improvement)** - Every 6h: agentic Claude run with Read + WebSearch + Bash tools. Reads `engagement_log.csv` (per-source ROI), looks up live FR AI/crypto/bourse trends, proposes new search queries + accounts. Python applies ADDITIONS only — never removes. Outputs land in `dynamic_queries.json` / `dynamic_accounts.json` and are merged at runtime by the reply bot. **No human in the loop.** Audit trail in `strategy_log.json`.

**Quote-Tweet Bot** - Every 4h, cap 2/day: picks the most viral FR tweet in our niches (min_faves:30, top tab) and quote-tweets it with a sharp meme observation. Different distribution surface than replies.

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
| `MAX_NEWS_PER_DAY` | 10 | Max news posts per day |
| `MAX_HOTAKES_PER_DAY` | 4 | Max hot takes per day |
| `NEWS_MODEL` | claude-opus-4-6 | Model for news posts |
| `REPLY_MODEL` | claude-sonnet-4-6 | Model for replies |
| `HOTAKE_MODEL` | claude-sonnet-4-6 | Model for hot takes |

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
  strategy_agent.py          # Autonomous self-improvement (agentic, every 6h)
  dynamic_strategy.py        # Append-only stores for strategy-agent additions
  quote_tweet_bot.py         # Quote-tweet path (cap 2/day)
  discover_bot.py            # Autonomous handle discovery (every 6h)
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
