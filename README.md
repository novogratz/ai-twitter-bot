# AI Twitter Bot

An autonomous Twitter/X bot powered by Claude Code. No API keys needed. Runs 4 bots 24/7: posting, replying, engagement, and notification farming.

## How It Works

Uses the Claude Code CLI for AI generation and Safari + AppleScript for browser automation. No Twitter API, no Anthropic API key. Just log into X on Safari and go.

### 4 Bots

**Post Bot** - Searches the web for breaking news in your niche, writes sharp tweets, and posts them automatically. Supports threads for big stories. Mix of news posts (~78%) and hot takes (~22%).

**Reply Bot** - Finds high-engagement tweets in your niche and drops witty one-liner replies every 2 minutes. Targets viral posts and replies to top comments on big threads. Auto-likes before replying for double notifications. Matches the language of the original tweet.

**Engage Bot** - Auto-follows target accounts and likes their latest tweets. Visits 5-8 profiles every 15 minutes, likes 2 tweets per visit. Tracks who's been followed to avoid re-follows.

**Notify Bot** - Likes replies on your own tweets every 10 minutes. Builds loyalty by making people feel seen.

## Setup

```bash
pip install -r requirements.txt
```

Install and authenticate the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

Log into X/Twitter on Safari. That's it.

## Usage

```bash
python main.py              # Run all 4 bots
python main.py --post-only  # Only post news + hot takes
python main.py --reply-only # Only reply to tweets
python main.py --dry-run    # Print without posting
```

Stop with `Ctrl+C` (graceful shutdown with signal handlers).

## Configuration

All settings are in `src/config.py` and can be overridden with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_NEWS_PER_DAY` | 70 | Max news posts per day |
| `MAX_HOTAKES_PER_DAY` | 20 | Max hot takes per day |
| `NEWS_MODEL` | claude-opus-4-6 | Model for news posts |
| `REPLY_MODEL` | claude-sonnet-4-6 | Model for replies |
| `HOTAKE_MODEL` | claude-sonnet-4-6 | Model for hot takes |

### Customizing for Your Niche

The bot is currently configured for AI/tech news but can be adapted to any topic:

1. **`src/agent.py`** - Edit the news prompt: change search terms, examples, and tone
2. **`src/hotake_agent.py`** - Edit the hot take prompt: change topics, formats, and examples
3. **`src/reply_agent.py`** - Edit the reply prompt: change search terms, target accounts, and reply style
4. **`src/engage_bot.py`** - Change the target accounts list to accounts in your niche
5. **`src/config.py`** - Change `BOT_HANDLE` to your Twitter handle

### Schedule (EST)

| Time         | Post interval | Reply interval | Engage     | Notify     |
|--------------|---------------|----------------|------------|------------|
| 11pm - 6am   | 30-45 min     | 2 min          | 15 min     | 10 min     |
| 6am - 7pm    | 15-20 min     | 2 min          | 15 min     | 10 min     |
| 7pm - 11pm   | 20-30 min     | 2 min          | 15 min     | 10 min     |

Post intervals are configurable in `main.py`.

## Growth Features

- **High volume** - ~90 posts/day + ~400 replies/day
- **Auto-follow** - Follows target accounts automatically, tracks state
- **Double-like** - Likes 2 tweets per profile visit for reciprocity
- **Big post targeting** - Replies to high-engagement tweets for max visibility
- **Reply-to-replies** - Replies to top comments on viral threads
- **Auto-like before reply** - Double notification for tweet authors
- **Notification farming** - Likes replies on own tweets, builds loyalty
- **Thread posting** - Multi-tweet threads for big stories (algorithm boost)
- **Follow CTA** - Configurable % of posts include a follow call-to-action
- **Cross-dedup** - Reply bot avoids topics the post bot just covered
- **Persistent state** - Daily counters and followed accounts survive restarts

## Architecture

```
main.py                  # Entry point, scheduler, CLI args
src/
  config.py              # Central config, env var overrides
  logger.py              # Rotating file logs (5MB, 3 backups)
  agent.py               # News tweet generation (Opus + WebSearch)
  hotake_agent.py         # Hot take generation (Sonnet, no web search)
  reply_agent.py          # Reply generation (Sonnet + WebSearch)
  replyback_agent.py      # Reply-back generation for engagement
  bot.py                 # Post orchestration, daily limits
  reply_bot.py           # Reply orchestration, dedup
  engage_bot.py          # Auto-follow + like engine
  notify_bot.py          # Notification farming
  twitter_client.py      # Safari/AppleScript browser automation
  history.py             # Tweet history, dedup (capped at 500)
  engagement_log.py      # CSV engagement tracking
```

## Requirements

- macOS (browser automation uses AppleScript + Safari)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on Safari
