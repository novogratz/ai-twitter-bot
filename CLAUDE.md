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

L'actu IA, Crypto et Bourse avant tout le monde. Des prises de position tranchees. Zero bullshit. Tu me detesteras jusqu'a ce que j'aie raison.

The bot autonomously covers 3 topics: IA, Crypto, and Investissement/Bourse. Posts news, drops hilarious troll replies, posts hot takes, likes target accounts, and farms notifications on X/Twitter as @kzer_ai. All original content in French. ALL replies in French, even to English tweets. FULL TROLL MODE.

### Smart Features
- **All topics all the time**: IA, Crypto, and Bourse covered in every cycle regardless of time of day
- **Trend surfing**: Reply agent searches for trending topics before picking tweets to reply to
- **Engagement tracking**: All posts, replies, and hot takes logged to `engagement_log.csv` for performance analysis
- **Reply-back agent**: `replyback_agent.py` generates witty follow-ups (ready for future integration)

### 4 Bots

**Post bot** - IA/Crypto/Bourse news tweets (Opus, with web search) + occasional hot takes (Sonnet, no web search, ~20% of posts). Threads for big stories. Follow CTA on ~25% of posts. All in French.

**Reply bot** - Single agent finds 5-10 tweets per cycle (IA, crypto, bourse). Runs every 2 min. FULL TROLL MODE. ALL replies in French. Prioritizes big French accounts. Auto-likes before replying. 20-30% are quote tweets. Cross-dedup with post bot. Trend surfing enabled.

**Engage bot** - Visits 3-5 target accounts every 25 min, likes their latest tweet. Builds reciprocity. ~40 accounts: AI companies, crypto leaders, finance influencers, French tech.

**Notify bot** - Every 20 min, visits own latest tweet and likes up to 5 replies. Builds loyalty (people feel seen, come back). Signals active engagement to the algorithm.

### Files

- **`src/agent.py`** - News tweet agent. Opus + WebSearch. Full French prompt covering IA + Crypto + Bourse (hook, troll, debate, numbers, mention, self-scoring). Returns `SKIP` if no fresh news.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. Full French prompt. 50% IA (philosophical + troll), 50% Crypto (full troll).
- **`src/reply_agent.py`** - Reply agent. Single Sonnet + WebSearch agent. 5-10 tweets per cycle. Full troll mode. ALL replies in French. Prioritizes big French accounts. Trend surfing. Strict recency: today only, last 30 min preferred.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Generates witty 60-char replies to people who reply to our tweets.
- **`src/bot.py`** - Post orchestration. 50/50 news vs hot takes. Time-zone topic optimization. Falls back to hot take when no news. Handles threads. Engagement logging.
- **`src/reply_bot.py`** - Reply orchestration. Refreshes feed, generates replies with cross-dedup, auto-likes, posts replies or quote tweets. Engagement logging.
- **`src/engage_bot.py`** - Reciprocity engine. Visits target accounts, likes their latest tweet. ~40 accounts.
- **`src/notify_bot.py`** - Notification farmer. Visits own latest tweet, likes replies.
- **`src/engagement_log.py`** - CSV engagement logging. Tracks all posts, replies, hot takes with timestamps.
- **`src/twitter_client.py`** - Browser automation: `post_tweet()`, `post_thread()`, `reply_to_tweet()`, `quote_tweet()`, `visit_profile_and_like()`, `like_own_tweet_replies()`, `refresh_feed()`, `like_tweet()`, `close_front_tab()`.
- **`src/history.py`** - Tweet history persistence and dedup.
- **`main.py`** - APScheduler with 4 jobs: posts (time-based), replies (2 min flat), engagement (25 min), notifications (20 min).

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 6am   | 10-15 min     | 2 min          |
| 6am - 9am    | 3-5 min       | 2 min          |
| 9am - 4pm    | 5-8 min       | 2 min          |
| 5pm - 7pm    | 3-5 min       | 2 min          |
| 7pm - 11pm   | 5-8 min       | 2 min          |

Engage bot: every 25 min. Notify bot: every 20 min. Both 24/7.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- All posts in French, 280 chars max. Replies match the language of the tweet (French reply to French tweet, English reply to English tweet).
- 3 topics: IA, Crypto, Investissement/Bourse. All covered all the time.
- News and hot takes 50/50. Hot takes fill gaps when no news.
- News agent: Opus (deep analysis, better research). Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript. macOS only.
- Safari tabs auto-close after every action.
- Auto-likes tweets before replying (double notification).
- Quote tweets 20-30% of replies (visible on own timeline).
- Notification farming: likes replies on own tweets every 20 min.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Strict recency on all content: today only, last 30 min preferred. Never yesterday or older.
- French tweets are #1 priority for replies. Prioritize big French accounts (10k+ followers).
- Reply volume: 5-10 per cycle, runs every 2 min flat. Single agent for speed.
- Trend surfing: reply agent searches for trending topics before picking tweets.
- Engagement tracking: all actions logged to engagement_log.csv.
- Any account size is fine for replies. Small accounts engage back, big accounts give visibility.
