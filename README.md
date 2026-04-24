# AI Twitter Bot

An autonomous Twitter/X bot powered by Claude Code. No API keys needed. Two modes: Python scheduler or Claude Code agent with slash commands.

## How It Works

Uses Claude Code for AI generation and Safari + AppleScript for browser automation. No Twitter API, no Anthropic API key. Just log into X on Safari and go.

### 4 Bots

**Post Bot** - Searches the web for breaking news in your niche, writes sharp tweets, and posts them automatically. Supports threads for big stories. Mix of news posts (~78%) and hot takes (~22%).

**Reply Bot** - Finds high-engagement tweets and drops witty one-liner replies every 2 minutes. Targets viral posts and replies to top comments on big threads. Auto-likes before replying. Matches tweet language.

**Engage Bot** - Auto-follows target accounts and likes their latest tweets. Visits 5-8 profiles every 15 minutes, likes 2 tweets per visit. Tracks who's been followed.

**Notify + Boost Bot** - Likes replies on your own tweets every 10 minutes. Self-retweets every 60 minutes. Builds loyalty and reach.

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

## Configuration

All settings in `src/config.py`, overridable with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_NEWS_PER_DAY` | 70 | Max news posts per day |
| `MAX_HOTAKES_PER_DAY` | 20 | Max hot takes per day |
| `NEWS_MODEL` | claude-opus-4-6 | Model for news posts |
| `REPLY_MODEL` | claude-sonnet-4-6 | Model for replies |
| `HOTAKE_MODEL` | claude-sonnet-4-6 | Model for hot takes |

### Customizing for Your Niche

Configured for AI/tech but adaptable to any topic:

1. **`src/agent.py`** - News prompt: search terms, examples, tone
2. **`src/hotake_agent.py`** - Hot take prompt: topics, formats, examples
3. **`src/reply_agent.py`** - Reply prompt: search terms, target accounts, style
4. **`src/engage_bot.py`** - Target accounts list
5. **`src/config.py`** - Bot handle and limits
6. **`.claude/skills/run-agent/SKILL.md`** - Agent behavior and personality

## Growth Features

- **High volume** - ~90 posts/day + ~400 replies/day
- **Quote tweets** - ~15% of replies are quote tweets (show on your timeline)
- **Self-retweet** - Boosts own content every 60 minutes
- **Auto-follow** - Follows target accounts, tracks state
- **Double-like** - Likes 2 tweets per profile visit
- **Big post targeting** - Replies to high-engagement tweets
- **Reply-to-replies** - Replies to top comments on viral threads
- **Auto-like before reply** - Double notification for tweet authors
- **Notification farming** - Likes replies on own tweets
- **Thread posting** - Multi-tweet threads for big stories
- **Follow CTA** - ~20% of replies include follow call-to-action
- **Cross-dedup** - Reply bot avoids topics the post bot just covered
- **Persistent state** - Counters and follows survive restarts

## Architecture

```
main.py                      # Python entry point, APScheduler
.claude/
  skills/                    # 22 slash commands for Claude Code
    run-agent/SKILL.md       # Main agent loop (replaces main.py)
    post/SKILL.md            # Manual post trigger
    reply/SKILL.md           # Manual reply trigger
    ...
  settings.json              # Hooks (pre-commit doc reminder)
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
  twitter_client.py          # Safari/AppleScript browser automation
  history.py                 # Tweet history, dedup (capped at 500)
  engagement_log.py          # CSV engagement tracking
```

## Requirements

- macOS (browser automation uses AppleScript + Safari)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on Safari
