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

The bot runs both the reply bot and post bot immediately on start, then schedules them on different intervals. The reply bot runs every 8 minutes. The post bot uses a time-based schedule (see below). Each cycle is wrapped in error handling so the scheduler stays alive.

You can also run a single tweet manually:
```bash
python test_tweet.py
```

## Architecture

The bot is a Claude agent that autonomously tweets in English about AI news and replies to popular AI tweets with sharp, funny one-liners on X/Twitter as @kzer_ai.

### Post flow
`main.py` (scheduler) -> `src/bot.py` (`run_bot_cycle`) -> `src/agent.py` (`generate_tweet`) -> `src/twitter_client.py` (`post_tweet`)

### Reply flow
`main.py` (scheduler) -> `src/reply_bot.py` (`run_reply_cycle`) -> `src/reply_agent.py` (`generate_replies`) -> `src/twitter_client.py` (`reply_to_tweet`)

### Files

- **`src/agent.py`** - Shells out to the `claude` CLI (`subprocess.run`) with `--allowedTools WebSearch --model claude-sonnet-4-6`. The agent searches for the freshest AI news (last hour first, then today), picks the best story, and writes a high-engagement English tweet using a multi-engine prompt (hook engine, troll engine, debate engine, numbers engine, mention engine, self-scoring, scroll-stop test). Returns `None` if no fresh news exists (`SKIP`).
- **`src/reply_agent.py`** - Shells out to `claude` CLI to search X/Twitter for popular AI tweets and generates a sharp, funny reply. Replies match the language of the original tweet (French tweet = French reply, English tweet = English reply). Returns a list of dicts with `tweet_url` and `reply`, or `None`.
- **`src/bot.py`** - Thin orchestration: calls agent, prints result, posts tweet, saves to history. Skips silently if agent returns `None`.
- **`src/reply_bot.py`** - Reply orchestration: refreshes the X feed, generates replies, posts them via browser automation, tracks replied tweet URLs in `replied_tweets.json` to avoid duplicates.
- **`src/twitter_client.py`** - Three functions: `post_tweet()` (via intent URL + AppleScript), `reply_to_tweet()` (opens tweet, presses `r` to reply, types text, Tab+Enter to submit), `refresh_feed()` (opens X home to load new tweets). macOS only. No Twitter API credentials needed.
- **`src/history.py`** - Persists posted tweets to `tweet_history.json` (JSON array with `text` + `timestamp`). Exposes `get_recent_tweets(hours=24)` for dedup, and `save_tweet()` called after each post.
- **`main.py`** - APScheduler `BlockingScheduler` with time-based posting intervals and 8-minute reply cycles. On launch: runs reply bot first (scan for tweets to reply to), then posts first news tweet, then schedules both.

## Posting schedule (EST)

| Time (EST)   | Post interval        |
|--------------|----------------------|
| 11pm - 6am   | 45-75 min (random)   |
| 6am - 10am   | 15-20 min (random)   |
| 10am - 5pm   | 40 min               |
| 5pm - 7pm    | 15 min               |
| 7pm - 11pm   | 40 min               |

Reply bot runs every 8 minutes, 24/7.

## Key design notes

- No API keys of any kind needed (no Twitter API, no Anthropic API).
- Posts are in English, 280 chars max (257 chars text + 23 for URL, which Twitter auto-shortens).
- Replies match the language of the original tweet.
- Account identity: @kzer_ai - the sharpest AI account on X. Sharp, funny, 0% bullshit.
- AI news only. No crypto, no general tech.
- Model is pinned to `claude-sonnet-4-6` via the `--model` flag.
- Posting is macOS-only: uses `webbrowser.open` + AppleScript for browser automation.
- Post dedup: agent is given last 24h of posted tweets to avoid repeating topics.
- Reply dedup: tracks replied tweet URLs in `replied_tweets.json` (last 500).
- Tweet history stored locally in `tweet_history.json` at repo root (gitignored).
- Strict recency: prioritizes news from the last hour, then today. Older stories are last resort.
- No em dashes anywhere in the codebase.
- Prompt includes: hook engine, troll engine (dry/deadpan), debate engine, numbers engine, mention engine, self-scoring (rewrite if avg < 8.5/10), scroll-stop test, format rotation.
