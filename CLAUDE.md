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

The bot runs three systems on launch: reply bot first (scan for tweets to reply to), then post bot (first news tweet), then schedules all three bots (posts, replies, engagement). Each cycle is wrapped in error handling so the scheduler stays alive.

You can also run a single tweet manually:
```bash
python test_tweet.py
```

## Architecture

The bot is a Claude agent that autonomously tweets in English about AI news, replies to popular AI tweets with sharp funny one-liners, quote tweets for visibility, posts threads for big stories, and engages with target accounts for reciprocity on X/Twitter as @kzer_ai.

### Post flow
`main.py` (scheduler) -> `src/bot.py` (`run_bot_cycle`) -> `src/agent.py` (`generate_tweet`) -> `src/twitter_client.py` (`post_tweet` or `post_thread`)

### Reply flow
`main.py` (scheduler) -> `src/reply_bot.py` (`run_reply_cycle`) -> `src/reply_agent.py` (`generate_replies`) -> `src/twitter_client.py` (`reply_to_tweet` or `quote_tweet`)

### Engage flow
`main.py` (scheduler) -> `src/engage_bot.py` (`run_engage_cycle`) -> `src/twitter_client.py` (`visit_profile_and_like`)

### Files

- **`src/agent.py`** - Shells out to the `claude` CLI (`subprocess.run`) with `--allowedTools WebSearch --model claude-sonnet-4-6`. The agent searches for the freshest AI news (last hour first, then today), picks the best story, and writes a high-engagement English tweet or 2-3 tweet thread. Uses multi-engine prompt (hook, troll, debate, numbers, mention, self-scoring, scroll-stop test). ~15% of posts are threads for big stories. ~25% include a follow CTA. Returns `None` if no fresh news (`SKIP`).
- **`src/reply_agent.py`** - Shells out to `claude` CLI to search X/Twitter for popular AI tweets and generates a sharp, funny reply. Targets rising tweets (10-30 min old, early engagement) and big accounts (10k+ followers) for max visibility. Replies match the language of the original tweet. 20-30% are quote tweets instead of replies. Cross-dedup with recent posts. Returns a list of dicts with `tweet_url`, `reply`, and `type` ("reply" or "quote"), or `None`.
- **`src/bot.py`** - Orchestration: calls agent, detects threads (split by `---THREAD---`), posts single tweet or thread, saves to history.
- **`src/reply_bot.py`** - Reply orchestration: refreshes feed, generates replies with cross-dedup, auto-likes tweets before replying, posts replies or quote tweets, tracks replied URLs in `replied_tweets.json`.
- **`src/engage_bot.py`** - Reciprocity engine: visits 3-5 random target accounts every 30 minutes, likes their latest tweet. Builds relationships and signals activity to the algorithm.
- **`src/twitter_client.py`** - Browser automation functions: `post_tweet()`, `post_thread()`, `reply_to_tweet()` (with auto-like), `quote_tweet()`, `visit_profile_and_like()`, `refresh_feed()`, `like_tweet()`, `close_front_tab()`. All via intent URLs + AppleScript. macOS only. No Twitter API credentials.
- **`src/history.py`** - Persists posted tweets to `tweet_history.json` (JSON array with `text` + `timestamp`). Exposes `get_recent_tweets(hours=24)` for dedup, and `save_tweet()` called after each post.
- **`main.py`** - APScheduler `BlockingScheduler` with three scheduled jobs: time-based posts, dynamic reply intervals, and 30-minute engagement cycles.

## Posting schedule (EST)

| Time (EST)   | Post interval        | Reply interval       |
|--------------|----------------------|----------------------|
| 11pm - 2am   | 45-75 min (random)   | 15-20 min            |
| 2am - 4am    | 45-75 min            | 3-5 min (FR morning) |
| 4am - 6am    | 45-75 min            | 10-15 min            |
| 6am - 9am    | 15-20 min (random)   | 3-5 min (US morning) |
| 9am - 10am   | 15-20 min            | 8 min                |
| 10am - 2pm   | 40 min               | 8 min                |
| 2pm - 5pm    | 40 min               | 3-5 min (US afternoon) |
| 5pm - 7pm    | 15 min               | 8 min                |
| 7pm - 11pm   | 40 min               | 8 min                |

Engagement bot runs every 30 minutes, 24/7.

## Key design notes

- No API keys of any kind needed (no Twitter API, no Anthropic API).
- Posts are in English, 280 chars max (257 chars text + 23 for URL, which Twitter auto-shortens).
- Replies match the language of the original tweet. Keep them short (under 80 chars ideal).
- Account identity: @kzer_ai - the sharpest AI account on X. Sharp, funny, 0% bullshit.
- AI news only. No crypto, no general tech.
- Model is pinned to `claude-sonnet-4-6` via the `--model` flag.
- Posting is macOS-only: uses `webbrowser.open` + AppleScript for browser automation.
- Safari tabs auto-close after every action to prevent memory buildup.
- Auto-likes tweets before replying (double notification for the author).
- Quote tweets used 20-30% of the time for replies (shows on YOUR timeline).
- Threads (2-3 tweets) for big stories (~15%), boosted by algorithm.
- Engagement bot likes tweets from target AI accounts every 30 min (reciprocity).
- Post dedup: agent is given last 24h of posted tweets to avoid repeating topics.
- Reply dedup: tracks replied tweet URLs in `replied_tweets.json` (last 500).
- Cross-dedup: reply bot avoids topics the post bot just covered (last 6h).
- Tweet history stored locally in `tweet_history.json` at repo root (gitignored).
- Strict recency: prioritizes news from the last hour, then today. Older stories are last resort.
- No em dashes anywhere in the codebase.
- ~25% of posts include a follow CTA ("Follow @kzer_ai for the fastest AI takes").
- Targets rising tweets (10-30 min old, 20-100 likes) for early reply position.
- Prioritizes big accounts (10k+ followers) for maximum visibility.
