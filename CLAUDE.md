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

```bash
python main.py              # Run all bots
python main.py --post-only  # Run only the post bot
python main.py --reply-only # Run only the reply bot
python main.py --dry-run    # Print actions without posting
```

The bot runs 4 systems: reply bot first (scan for tweets), then post bot, then schedules all four jobs (posts, replies, engagement, notification farming). Each cycle is wrapped in error handling so the scheduler stays alive. Graceful shutdown via Ctrl+C or SIGTERM.

## Architecture

The sharpest AI account on X. Fastest on news. Hardest takes. 0% bullshit. Follow @kzer_ai for the fastest AI takes.

The bot autonomously covers AI news, drops hilarious troll replies, posts AI philosophy hot takes and personal AI tool reviews, auto-follows top AI accounts, likes their tweets, and farms notifications on X/Twitter as @kzer_ai. All posts in ENGLISH. Replies bilingual (match tweet language). AI ONLY focus. FULL TROLL MODE.

### Smart Features
- **AI-only focus**: Pure AI coverage for maximum authority and audience targeting
- **High volume**: 3-4 news posts/hour + 1 hot take/hour during peak (~90 posts/day)
- **Auto-follow**: Automatically follows top AI accounts, tracks who's been followed
- **Aggressive engagement**: Likes 2 tweets per profile visit, 5-8 accounts every 15 min
- **Personal experience tweets**: "Just tested [tool] and..." - authentic AI tool reviews
- **Structured logging**: Rotating file logs (bot.log), engagement CSV tracking
- **Persistent state**: Daily counters survive process restarts (daily_state.json)
- **CLI arguments**: --post-only, --reply-only, --dry-run modes
- **Graceful shutdown**: SIGTERM/SIGINT signal handlers
- **Environment variable config**: All limits and models configurable via env vars

### 4 Bots

**Post bot** - AI news tweets in English (Opus, with web search) + AI hot takes (Sonnet, no web search, ~22% of posts). Hot takes mix: 35% philosophical, 35% troll, 30% personal experience. ~70 news + ~20 hot takes per day. Threads for big stories. Follow CTA on ~25% of posts.

**Reply bot** - Single agent finds 10-14 tweets per cycle. Runs every 2 min. FULL TROLL MODE. Replies match tweet language (English tweets get English replies, French tweets get French replies). Targets big AI posts with high engagement. Also replies to top replies on viral posts for extra visibility. Auto-likes before replying. Cross-dedup with post bot. This week only.

**Engage bot** - Visits 5-8 target accounts every 15 min. Auto-follows new accounts (tracked in followed_accounts.json). Likes their latest 2 tweets. ~45 top AI accounts (companies, CEOs, researchers, influencers, dev tools, media, French AI).

**Notify bot** - Every 10 min, visits own latest tweet and likes up to 8 replies. Aggressive loyalty building.

### Files

- **`src/config.py`** - Central configuration: bot handle, file paths, daily limits, models, retry settings. All configurable via environment variables.
- **`src/logger.py`** - Structured logging with rotating file handler (5MB, 3 backups). Used by all modules.
- **`src/agent.py`** - News tweet agent. Opus + WebSearch. English prompt. AI-only (hook, troll, debate, numbers, mention, self-scoring). Returns `SKIP` if no fresh news.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. English. 35% philosophical, 35% troll, 30% personal experience ("just tested [tool]...").
- **`src/reply_agent.py`** - Reply agent. Single Sonnet + WebSearch. 10-14 tweets per cycle. Matches tweet language. AI-only. Targets big posts + replies on viral threads. This week only.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Generates witty replies to people who reply to our tweets.
- **`src/bot.py`** - Post orchestration. ~78% news, ~22% hot takes. Persistent daily limits (70 news, 20 hot takes). Falls back to hot take when no news. Handles threads. Engagement logging.
- **`src/reply_bot.py`** - Reply orchestration. Refreshes feed, generates replies with cross-dedup, auto-likes, posts replies. Engagement logging.
- **`src/engage_bot.py`** - Growth engine. Auto-follows AI accounts, likes their latest 2 tweets. ~45 accounts. Tracks followed in JSON.
- **`src/notify_bot.py`** - Notification farmer. Visits own latest tweet, likes up to 8 replies.
- **`src/engagement_log.py`** - CSV engagement logging. Tracks all posts, replies, hot takes with timestamps.
- **`src/twitter_client.py`** - Browser automation with retry logic: `post_tweet()`, `post_thread()`, `reply_to_tweet()`, `quote_tweet()`, `follow_account()`, `visit_profile_and_like()`, `like_own_tweet_replies()`, `refresh_feed()`, `like_tweet()`, `close_front_tab()`.
- **`src/history.py`** - Tweet history persistence, dedup, capped at 500 entries.
- **`main.py`** - CLI entry point. APScheduler with 4 jobs. Argument parser. Signal handlers. Graceful shutdown.

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 6am   | 30-45 min     | 2 min          |
| 6am - 10am   | 15-20 min     | 2 min          |
| 10am - 5pm   | 15-20 min     | 2 min          |
| 5pm - 7pm    | 15-20 min     | 2 min          |
| 7pm - 11pm   | 20-30 min     | 2 min          |

Engage bot: every 15 min (follow + like 2 tweets). Notify bot: every 10 min (like 8 replies). Both 24/7.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- All posts in ENGLISH, 280 chars max. Replies bilingual (match tweet language).
- AI ONLY focus. No crypto, no bourse/stocks.
- ~70 news + ~20 hot takes per day. High volume strategy.
- News agent: Opus (deep analysis, better research). Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript with retry logic. macOS only.
- Safari tabs auto-close after every action.
- Auto-follows top AI accounts (tracked, no re-follows).
- Likes 2 tweets per profile visit for double engagement.
- Auto-likes tweets before replying (double notification).
- Notification farming: likes 8 replies on own tweets every 10 min.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Reply recency: this week only. News recency: today only.
- Reply volume: 10-14 per cycle, runs every 2 min flat. Single agent for speed.
- Target big posts with high engagement for maximum visibility on replies.
- Structured logging to bot.log with rotation (5MB, 3 backups).
- Persistent daily state survives process restarts.
- All limits configurable via environment variables.
- Engagement tracking: all actions logged to engagement_log.csv.
