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

The bot runs one tweet immediately on start (if within active hours), then checks every 10-15 minutes (randomized). It only posts during 6am-11pm EST. Each tick calls `safe_run_bot_cycle()`, which catches all exceptions so the scheduler stays alive.

You can also run a single tweet manually:
```bash
python test_tweet.py
```

## Architecture

The bot is a Claude agent that autonomously tweets in French about AI and Crypto news, targeting maximum engagement on X/Twitter as @kzer_ai - the #1 French AI and Crypto account.

**Flow:** `main.py` (scheduler) -> `src/bot.py` (`run_bot_cycle`) -> `src/agent.py` (`generate_tweet`) -> `src/twitter_client.py` (`post_tweet`)

- **`src/agent.py`** - Shells out to the `claude` CLI (`subprocess.run`) with `--allowedTools WebSearch --model claude-sonnet-4-6`. The agent searches for fresh AI and Crypto news published TODAY, picks the best story, and writes a high-engagement French tweet using a multi-engine prompt (hook engine, troll engine, numbers engine, mention engine, self-scoring, scroll-stop test). Returns `None` if no fresh news exists today (`SKIP`).
- **`src/bot.py`** - Thin orchestration: calls agent, prints result, posts tweet, saves to history. Skips silently if agent returns `None`.
- **`src/twitter_client.py`** - Posts tweets via the Twitter web intent URL (`https://x.com/intent/post?text=...`), opens it in the browser, then uses AppleScript (`osascript`) to send Cmd+Enter to auto-submit. macOS only. No Twitter API credentials needed.
- **`src/history.py`** - Persists posted tweets to `tweet_history.json` (JSON array with `text` + `timestamp`). Exposes `get_recent_tweets(hours=24)` for dedup, and `save_tweet()` called after each post.
- **`main.py`** - APScheduler `BlockingScheduler` with a randomized 10-15 minute interval. Checks `is_peak_hour_est()` before each cycle and skips outside 6am-11pm EST.

## Key design notes

- No API keys of any kind needed (no Twitter API, no Anthropic API).
- Tweets are in French, 280 chars max (257 chars text + 23 for URL, which Twitter auto-shortens).
- Account identity: @kzer_ai - #1 French AI and Crypto account, sharp, funny, 0% bullshit.
- Covers both AI and Crypto news with equal priority.
- Model is pinned to `claude-sonnet-4-6` via the `--model` flag.
- Posting is macOS-only: uses `webbrowser.open` + AppleScript to click the Post button.
- Dedup: agent is given last 24h of posted tweets to avoid repeating topics.
- Tweet history stored locally in `tweet_history.json` at repo root (gitignored).
- Strict recency: only news published TODAY is accepted. Older stories are discarded.
- Prompt includes: hook engine, troll engine (dry/deadpan), numbers engine, mention engine, self-scoring (rewrite if avg < 8/10), scroll-stop test, format rotation.
- Active hours: 6am-11pm EST only.
