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

The bot runs one tweet immediately on start (if within peak EST hours), then checks every 15-18 minutes. It only posts during peak EST engagement windows: 6am-11pm. Each tick calls `safe_run_bot_cycle()`, which catches all exceptions so the scheduler stays alive.

You can also run a single tweet manually:
```bash
python test_tweet.py
```

## Architecture

The bot is a Claude agent that autonomously tweets in English about AI news, targeting maximum engagement on X/Twitter as @kzer_ai.

**Flow:** `main.py` (scheduler) -> `src/bot.py` (`run_bot_cycle`) -> `src/agent.py` (`generate_tweet`) -> `src/twitter_client.py` (`post_tweet`)

- **`src/agent.py`** - Shells out to the `claude` CLI (`subprocess.run`) with `--allowedTools WebSearch --model claude-sonnet-4-6`. The agent searches for fresh AI news, picks the best story, and writes a high-engagement English tweet using a multi-engine prompt (hook engine, numbers engine, mention engine, emotion engine, personality engine, post scoring, scroll-stop test). Returns `None` if no high-quality news exists (`SKIP`).
- **`src/bot.py`** - Thin orchestration: calls agent, prints result, posts tweet, saves to history. Skips the cycle silently if agent returns `None`.
- **`src/twitter_client.py`** - Posts tweets via the Twitter web intent URL (`https://x.com/intent/post?text=...`), opens it in the browser, then uses AppleScript (`osascript`) to send Cmd+Enter to auto-submit. macOS only. No Twitter API credentials needed.
- **`src/history.py`** - Persists posted tweets to `tweet_history.json` (JSON array with `text` + `timestamp`). Exposes `get_recent_tweets(hours=24)` used by the agent for dedup, and `save_tweet()` called after each successful post.
- **`main.py`** - APScheduler `BlockingScheduler` with a randomized 15-18 minute interval. Checks `is_peak_hour_est()` before each cycle and skips posting outside peak EST windows (6am-11pm).

## Key design notes

- No API keys of any kind needed (no Twitter API, no Anthropic API).
- Tweets are in English, 280 chars max (257 chars text + 23 for URL, which Twitter auto-shortens).
- Account identity: @kzer_ai - early AI scout, sharp market-aware commentary, personality-driven.
- Model is pinned to `claude-sonnet-4-6` via the `--model` flag in the CLI call.
- Posting is macOS-only: uses `webbrowser.open` + AppleScript to click the Post button.
- Dedup: the agent is given the last 24h of posted tweets and told to pick a different topic.
- Tweet history is stored locally in `tweet_history.json` at the repo root (gitignored).
- The prompt includes: hook engine, numbers engine (specific figures), mention engine (@handles), emotion engine, contrarian/ratio-bait formats, self-scoring (rewrite if avg < 8/10), and scroll-stop test.
- Post formats rotate: breaking news, explainer, bold take, witty, prediction, contrarian, ratio bait.
- Peak hour gating: only posts during 6am-11pm EST for max reach per tweet.
