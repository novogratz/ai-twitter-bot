# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
```

No API keys needed. The bot posts via browser + AppleScript (macOS only) and uses the Claude Code CLI subscription for AI generation.

The only requirement is that the `claude` CLI is installed and authenticated:
```bash
claude login
```

## Running

Use skills (slash commands) to control the bot:

```
/start              # Start full bot in background (all systems)
/stop               # Stop the bot gracefully
/restart            # Stop then start
/status             # Quick health check - running?, counters, errors
/run-agent          # Run as Claude Code agent (replaces python main.py)
```

### Manual triggers
```
/post               # Trigger one post cycle (news or hot take)
/reply              # Trigger one reply cycle
/engage             # Trigger one engage cycle (follow + like)
/boost              # Self-retweet latest tweet
/hotake             # Generate a hot take, preview, then post
/news               # Generate a news tweet preview
/tweet              # Post a specific tweet right now
/thread             # Post a multi-tweet thread
/follow             # Follow a specific account
/like               # Visit a profile and like their tweets
/dryrun             # Preview what the bot would do without posting
```

### Monitoring & config
```
/stats              # Full engagement dashboard
/logs               # Recent bot logs
/history            # Recent tweet history
/accounts           # View/manage target accounts
/config             # View/edit bot configuration
/reset              # Reset daily counters
/improve            # Self-improvement cycle from performance data
```

The bot runs 4 systems: reply bot first (scan for tweets), then post bot, then schedules all jobs (posts, replies, engagement, notification farming). Each cycle is wrapped in error handling so the scheduler stays alive. Graceful shutdown via Ctrl+C or SIGTERM.

## Architecture

AI news before everyone else. Sharp takes. Zero bullshit. You'll hate me until I'm right. Follow @kzer_ai.

Autonomous bot that covers AI news with sharp criticism and trolling energy. The AI CRITIC - sees what others miss, calls out what others won't. English only. Quality over quantity.

### Strategy
- **ENGLISH only**: All posts, replies, hot takes in English
- **AI only**: No crypto, no finance. Pure AI focus.
- **AI CRITIC identity**: Not a news aggregator. The sharpest critic in the room.
- **Replies are the growth engine**: 3-4 replies every 20 min on massive accounts (500k+ followers)
- **Hot takes are the differentiator**: 4/day - original criticism, trolling, predictions
- **News only for earthquakes**: 1/day max, must be THE story of the day
- **Humanizer on everything**: Every post goes through a human-pass before publishing
- **Self-improving**: Scrapes own metrics and adapts style automatically
- **Anti-spam**: Moderate frequencies to avoid shadow bans

### 5 Bots

**Post bot** - 1 news/day (Opus + WebSearch, only massive stories) + 4 hot takes/day (Sonnet, AI critic commentary). 80% hot takes. Humanizer on all output.

**Reply bot** - 3-4 quality replies per cycle, every 20 min. Targets tweets from 500k+ follower accounts. ~85% replies, ~15% quote tweets. Be early on viral tweets. Humanizer on all output.

**Engage bot** - 3-5 accounts per cycle, every 30 min. Auto-follow + 3 likes per visit. AI companies, leaders, researchers, influencers.

**Notify + Boost bot** - Like replies on own tweets every 45 min. Self-retweet every 8 hours.

**Performance bot** - Scrapes likes/views every 2h. Identifies top/worst performers. Injects learnings into prompts.

### Files

- **`src/config.py`** - Central config: handle, paths, limits (1 news, 4 hot takes), models, retry settings.
- **`src/agent.py`** - News agent. Opus + WebSearch. English. AI only. Strict quality gate - only THE story of the day.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. AI CRITIC identity. Commentary + trolling.
- **`src/reply_agent.py`** - Reply agent. Sonnet + WebSearch. 3-4 replies per cycle. Targets 500k+ accounts. 85% replies, 15% QTs.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Witty replies to people who reply to our tweets.
- **`src/humanizer.py`** - Humanizer. Sonnet pass to make AI-generated text sound human. Applied to all output.
- **`src/bot.py`** - Post orchestration. 80% hot takes, 20% news. Persistent daily limits. Humanizer on all output.
- **`src/reply_bot.py`** - Reply orchestration. Generates replies, cross-dedup, humanizer, posts. Every 20 min.
- **`src/engage_bot.py`** - Growth engine. Auto-follows AI accounts. 3-5 accounts per cycle, every 30 min.
- **`src/notify_bot.py`** - Notification farmer. Likes replies every 45 min. Self-retweet every 8 hours.
- **`src/performance.py`** - Self-improving. Scrapes metrics every 2h. Injects learnings into prompts.
- **`src/engagement_log.py`** - CSV engagement logging.
- **`src/twitter_client.py`** - Browser automation with Safari lock and retry logic.
- **`src/history.py`** - Tweet history persistence, dedup, capped at 500 entries.
- **`main.py`** - CLI entry point. APScheduler with 6 jobs. Signal handlers. Graceful shutdown.

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 8am   | 240-420 min   | 20 min         |
| 8am - 12pm   | 120-200 min   | 20 min         |
| 12pm - 6pm   | 90-160 min    | 20 min         |
| 6pm - 11pm   | 150-240 min   | 20 min         |

Engage bot: every 30 min (3-5 accounts, 3 likes each). Notify bot: every 45 min. Boost: every 8h. Performance: every 2h.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- ENGLISH only. AI only. 280 chars max.
- AI CRITIC identity: sharp commentary, criticism, trolling on AI news.
- 1 news + 4 hot takes per day. Quality elite.
- Replies are the #1 growth engine: target massive accounts (500k+ followers).
- Humanizer pass on ALL output (posts, replies, hot takes).
- News agent: Opus. Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript. macOS only.
- Safari lock prevents concurrent browser access.
- Anti-spam: moderate frequencies to avoid shadow bans.
- Reply targeting: 5-30 min old tweets for best position.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Self-improving: scrapes own metrics every 2h, adapts prompts.
- Persistent daily state survives process restarts.
- All limits configurable via environment variables.
