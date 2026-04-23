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

The bot autonomously covers 3 topics: IA, Crypto, and Investissement/Bourse. Posts news, drops hilarious troll replies, posts hot takes, likes target accounts, and farms notifications on X/Twitter as @kzer_ai. All original content in French. Replies match the language of the original tweet. FULL TROLL MODE.

### 4 Bots

**Post bot** - IA/Crypto/Bourse news tweets (Opus, with web search) + occasional hot takes (Sonnet, no web search, ~20% of posts). Threads for big stories. Follow CTA on ~25% of posts. All in French.

**Reply bot** - 3 parallel agents (IA, Crypto, Invest), 3-4 replies each (~10 total per cycle). Runs every 1-3 min for constant fresh content. FULL TROLL MODE. French first, then English. Any account size. Auto-likes before replying. 20-30% are quote tweets. Cross-dedup with post bot.

**Engage bot** - Visits 3-5 target accounts every 25 min, likes their latest tweet. Builds reciprocity. ~40 accounts: AI companies, crypto leaders, finance influencers, French tech.

**Notify bot** - Every 20 min, visits own latest tweet and likes up to 5 replies. Builds loyalty (people feel seen, come back). Signals active engagement to the algorithm.

### Files

- **`src/agent.py`** - News tweet agent. Opus + WebSearch. Full French prompt covering IA + Crypto + Bourse (hook, troll, debate, numbers, mention, self-scoring). Returns `SKIP` if no fresh news.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. Full French prompt. Generates engagement bait across IA (~40%), Crypto (~30%), Investissement (~30%).
- **`src/reply_agent.py`** - Reply agent. 3 parallel Sonnet + WebSearch agents (IA, Crypto, Invest). 3-4 tweets per topic, runs fast. Full troll mode. French first, then English. Strict recency: today only, last 30 min preferred. Uses `--bare` for speed.
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
| 11pm - 2am   | 45-75 min            | 8-12 min             |
| 2am - 4am    | 45-75 min            | 1-2 min (FR morning) |
| 4am - 6am    | 45-75 min            | 5-8 min              |
| 6am - 9am    | 15-20 min            | 1-2 min (US morning) |
| 9am - 10am   | 15-20 min            | 2-3 min              |
| 10am - 2pm   | 40 min               | 2-3 min              |
| 2pm - 5pm    | 40 min               | 1-2 min (US afternoon) |
| 5pm - 7pm    | 15 min               | 2-3 min              |
| 7pm - 11pm   | 40 min               | 2-3 min              |

Engage bot: every 25 min. Notify bot: every 20 min. Both 24/7.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- All posts in French, 280 chars max. Quote tweets always in French. Replies match original tweet language.
- 3 topics: IA, Crypto, Investissement/Bourse. All covered equally in news, replies, and hot takes.
- News is the core content (~80%). Hot takes fill gaps (~20%).
- News agent: Opus (deep analysis, better research). Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript. macOS only.
- Safari tabs auto-close after every action.
- Auto-likes tweets before replying (double notification).
- Quote tweets 20-30% of replies (visible on own timeline).
- Notification farming: likes replies on own tweets every 20 min.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Strict recency on all content: today only, last 30 min preferred. Never yesterday or older.
- French tweets are #1 priority for replies. 3 topics: IA, crypto, investissement.
- Reply volume: 3-4 per topic (~10 total) per cycle, runs every 1-3 min. Small fast batches.
- Reply agents use 1 search max per topic for speed.
- Any account size is fine for replies. Small accounts engage back, big accounts give visibility.
