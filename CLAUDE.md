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

The sharpest AI account on X. Fastest on news. Hardest takes. 0% bullshit. Follow @kzer_ai for the fastest AI takes.

The bot autonomously covers AI news, drops hilarious troll replies, posts AI philosophy hot takes, likes target accounts, and farms notifications on X/Twitter as @kzer_ai. All posts in ENGLISH. Replies bilingual (match tweet language). AI ONLY focus. FULL TROLL MODE.

### Smart Features
- **AI-only focus**: Pure AI coverage for maximum authority and audience targeting
- **High volume**: 3-4 news posts/hour + 1 hot take/hour during peak
- **Engagement tracking**: All posts, replies, and hot takes logged to `engagement_log.csv`
- **Big post targeting**: Reply agent prioritizes high-engagement tweets for maximum visibility

### 4 Bots

**Post bot** - AI news tweets in English (Opus, with web search) + AI philosophy hot takes (Sonnet, no web search, ~22% of posts). ~70 news + ~20 hot takes per day. Threads for big stories. Follow CTA on ~25% of posts.

**Reply bot** - Single agent finds 10-14 tweets per cycle. Runs every 2 min. FULL TROLL MODE. Bilingual (matches tweet language). Targets big AI posts with high engagement. Auto-likes before replying. Cross-dedup with post bot.

**Engage bot** - Visits 3-5 target accounts every 25 min, likes their latest tweet. Builds reciprocity. AI-focused accounts only (~30 accounts).

**Notify bot** - Every 20 min, visits own latest tweet and likes up to 5 replies. Builds loyalty.

### Files

- **`src/agent.py`** - News tweet agent. Opus + WebSearch. English prompt. AI-only (hook, troll, debate, numbers, mention, self-scoring). Returns `SKIP` if no fresh news.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. English. 50% philosophical AI, 50% troll AI.
- **`src/reply_agent.py`** - Reply agent. Single Sonnet + WebSearch. 10-14 tweets per cycle. Bilingual. AI-only. Targets big posts. This week only.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Generates witty replies to people who reply to our tweets.
- **`src/bot.py`** - Post orchestration. ~78% news, ~22% hot takes. Daily limits (70 news, 20 hot takes). Falls back to hot take when no news. Handles threads. Engagement logging.
- **`src/reply_bot.py`** - Reply orchestration. Refreshes feed, generates replies with cross-dedup, auto-likes, posts replies. Engagement logging.
- **`src/engage_bot.py`** - Reciprocity engine. AI-focused accounts only. Likes their latest tweet.
- **`src/notify_bot.py`** - Notification farmer. Visits own latest tweet, likes replies.
- **`src/engagement_log.py`** - CSV engagement logging. Tracks all posts, replies, hot takes with timestamps.
- **`src/twitter_client.py`** - Browser automation: `post_tweet()`, `post_thread()`, `reply_to_tweet()`, `quote_tweet()`, `visit_profile_and_like()`, `like_own_tweet_replies()`, `refresh_feed()`, `like_tweet()`, `close_front_tab()`.
- **`src/history.py`** - Tweet history persistence and dedup.
- **`main.py`** - APScheduler with 4 jobs: posts (15-20 min), replies (2 min flat), engagement (25 min), notifications (20 min).

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 6am   | 30-45 min     | 2 min          |
| 6am - 10am   | 15-20 min     | 2 min          |
| 10am - 5pm   | 15-20 min     | 2 min          |
| 5pm - 7pm    | 15-20 min     | 2 min          |
| 7pm - 11pm   | 20-30 min     | 2 min          |

Engage bot: every 25 min. Notify bot: every 20 min. Both 24/7.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- All posts in ENGLISH, 280 chars max. Replies bilingual (match tweet language).
- AI ONLY focus. No crypto, no bourse/stocks.
- ~70 news + ~20 hot takes per day. High volume strategy.
- News agent: Opus (deep analysis, better research). Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript. macOS only.
- Safari tabs auto-close after every action.
- Auto-likes tweets before replying (double notification).
- Notification farming: likes replies on own tweets every 20 min.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Reply recency: this week only. News recency: today only.
- Reply volume: 10-14 per cycle, runs every 2 min flat. Single agent for speed.
- Target big posts with high engagement for maximum visibility on replies.
- Engagement tracking: all actions logged to engagement_log.csv.
