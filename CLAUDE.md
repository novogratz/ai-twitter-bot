# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # then fill in credentials
```

Required env vars: `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET`, `TWITTER_BEARER_TOKEN`, `ANTHROPIC_API_KEY`.

## Running

```bash
python main.py
```

The bot starts a scheduler that fires every 15–20 minutes (randomized). On each tick it calls `safe_run_bot_cycle()`, which catches all exceptions so the scheduler stays alive.

## Architecture

The bot is a Claude agent that autonomously tweets in French about AI news.

**Flow:** `main.py` (scheduler) → `src/bot.py` (`run_bot_cycle`) → `src/agent.py` (`generate_tweet`) → `src/twitter_client.py` (`post_tweet`)

- **`src/agent.py`** — Core Claude agent loop. Uses the `web_search_20260209` built-in tool with `claude-opus-4-6` and adaptive thinking. Handles `pause_turn` (server-side search iteration limit) by re-appending assistant content and continuing, up to 5 iterations.
- **`src/bot.py`** — Thin orchestration: calls agent, prints result, posts tweet.
- **`src/twitter_client.py`** — Wraps Tweepy v2 `client.create_tweet`.
- **`main.py`** — APScheduler `BlockingScheduler` with a randomized interval that reschedules itself after each run.

## Key design notes

- Tweets are in French, 280 chars max, targeting a French-speaking AI audience.
- The agent uses `thinking: {"type": "adaptive"}` — the model decides when extended thinking is needed.
- No external news API; Claude fetches its own news via the built-in web search tool.
- `model="claude-opus-4-6"` is hardcoded in `src/agent.py`.
