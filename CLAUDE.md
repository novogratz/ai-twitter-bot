# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # then fill in credentials
```

Required env vars: `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET`, `TWITTER_BEARER_TOKEN`.

No Anthropic API key needed — the bot shells out to the `claude` CLI, which uses the Claude Code subscription.

## Running

```bash
python main.py
```

The bot runs one tweet immediately on start, then schedules the next run every 45–60 minutes (randomized) (hardcoded in `random_interval_minutes()`). Each tick calls `safe_run_bot_cycle()`, which catches all exceptions so the scheduler stays alive.

## Architecture

The bot is a Claude agent that autonomously tweets in French about AI news.

**Flow:** `main.py` (scheduler) → `src/bot.py` (`run_bot_cycle`) → `src/agent.py` (`generate_tweet`) → `src/twitter_client.py` (`post_tweet`)

- **`src/agent.py`** — Shells out to the `claude` CLI (`subprocess.run`) with `--allowedTools WebSearch --model claude-sonnet-4-6`. The CLI runs under the Claude Code subscription — no API key needed. Returns `None` if the agent decides no fresh news exists (responds with `SKIP`).
- **`src/bot.py`** — Thin orchestration: calls agent, prints result, posts tweet, saves to history. Skips the cycle silently if agent returns `None`.
- **`src/twitter_client.py`** — Posts tweets via the Twitter web intent URL (`https://x.com/intent/post?text=...`), opens it in the browser, then uses AppleScript (`osascript`) to send Cmd+Enter to auto-submit. **macOS only.**
- **`src/history.py`** — Persists posted tweets to `tweet_history.json` (JSON array with `text` + `timestamp`). Exposes `get_recent_tweets(hours=24)` used by the agent for dedup, and `save_tweet()` called after each successful post.
- **`main.py`** — APScheduler `BlockingScheduler` with a fixed 35-minute interval that reschedules itself after each run.

## Key design notes

- Tweets are in French, 280 chars max, targeting a French-speaking AI audience.
- No Anthropic API key or external news API needed — the `claude` CLI handles both search and generation.
- The `claude` CLI must be installed and authenticated (`claude login`) on the machine running the bot.
- Model is pinned to `claude-sonnet-4-6` via the `--model` flag in the CLI call.
- Posting is macOS-only: uses `webbrowser.open` + AppleScript to click the Post button.
- Dedup: the agent is given the last 24h of posted tweets and told to pick a different topic.
- Tweet history is stored locally in `tweet_history.json` at the repo root (gitignored).
