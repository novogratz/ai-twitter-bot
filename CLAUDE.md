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
python main.py
```

The bot runs 4 systems: reply bot first (scan for tweets), then post bot, then schedules all four jobs (posts, replies, engagement, notification farming). Each cycle is wrapped in error handling so the scheduler stays alive.

## Architecture

The bot autonomously tweets AI news in French, drops funny replies, posts hot takes in French, likes target accounts, and farms notifications on X/Twitter as @kzer_ai. All original content (news posts, hot takes, quote tweets) is in French. Replies match the language of the original tweet.

### 4 Bots

**Post bot** - AI news tweets (Opus, with web search) + occasional hot takes (Sonnet, no web search, ~20% of posts). Threads for big stories. Follow CTA on ~25% of posts.

**Reply bot** - Finds 10-12 tweets per cycle (French first, any topic), writes HILARIOUS troll replies (Sonnet). Full comedy mode. French Twitter is #1 priority, then English. Any account size. Auto-likes before replying. 20-30% are quote tweets. Cross-dedup with post bot.

**Engage bot** - Visits 3-5 target AI accounts every 25 min, likes their latest tweet. Builds reciprocity. ~25 accounts: AI companies, leaders, influencers, French tech.

**Notify bot** - Every 20 min, visits own latest tweet and likes up to 5 replies. Builds loyalty (people feel seen, come back). Signals active engagement to the algorithm.

### Files

- **`src/agent.py`** - News tweet agent. Opus + WebSearch. Full French prompt (hook, troll, debate, numbers, mention, self-scoring). All tweets in French. Returns `SKIP` if no fresh news.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. Full French prompt. Generates engagement bait in French: opinions impopulaires, classements, predictions, battles VS.
- **`src/reply_agent.py`** - Reply agent. Sonnet + WebSearch. Finds 10-12 tweets per cycle, full troll mode. French tweets #1 priority (any topic: tech, startups, dev life, AI). Then English. Any account size. Strict recency: today only, last 30 min preferred.
- **`src/bot.py`** - Post orchestration. 80% news, 20% hot takes. Falls back to hot take when no news. Handles threads.
- **`src/reply_bot.py`** - Reply orchestration. Refreshes feed, generates replies with cross-dedup, auto-likes, posts replies or quote tweets.
- **`src/engage_bot.py`** - Reciprocity engine. Visits target accounts, likes their latest tweet.
- **`src/notify_bot.py`** - Notification farmer. Visits own latest tweet, likes replies.
- **`src/twitter_client.py`** - Browser automation: `post_tweet()`, `post_thread()`, `reply_to_tweet()`, `quote_tweet()`, `visit_profile_and_like()`, `like_own_tweet_replies()`, `refresh_feed()`, `like_tweet()`, `close_front_tab()`.
- **`src/history.py`** - Tweet history persistence and dedup.
- **`main.py`** - APScheduler with 4 jobs: posts (time-based), replies (peak-aware), engagement (25 min), notifications (20 min).

## Schedule (EST)

| Time (EST)   | Post interval        | Reply interval       |
|--------------|----------------------|----------------------|
| 11pm - 2am   | 45-75 min            | 15-20 min            |
| 2am - 4am    | 45-75 min            | 3-5 min (FR morning) |
| 4am - 6am    | 45-75 min            | 10-15 min            |
| 6am - 9am    | 15-20 min            | 3-5 min (US morning) |
| 9am - 10am   | 15-20 min            | 8 min                |
| 10am - 2pm   | 40 min               | 8 min                |
| 2pm - 5pm    | 40 min               | 3-5 min (US afternoon) |
| 5pm - 7pm    | 15 min               | 8 min                |
| 7pm - 11pm   | 40 min               | 8 min                |

Engage bot: every 25 min. Notify bot: every 20 min. Both 24/7.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- All posts in French, 280 chars max. Quote tweets always in French. Replies match original tweet language.
- AI news is the core content (~80%). Hot takes fill gaps (~20%).
- News agent: Opus (deep analysis, better research). Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript. macOS only.
- Safari tabs auto-close after every action.
- Auto-likes tweets before replying (double notification).
- Quote tweets 20-30% of replies (visible on own timeline).
- Notification farming: likes replies on own tweets every 20 min.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Strict recency on all content: today only, last 30 min preferred. Never yesterday or older.
- French tweets are #1 priority for replies. Any topic (tech, startups, dev life, AI, whatever is trending).
- Reply volume: 10-12 replies per cycle in full troll/comedy mode.
- Any account size is fine for replies. Small accounts engage back, big accounts give visibility.
