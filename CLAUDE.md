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

The bot starts a scheduler that fires every 15–20 minutes (randomized). On each tick it calls `safe_run_bot_cycle()`, which catches all exceptions so the scheduler stays alive.

## Architecture

The bot is a Claude agent that autonomously tweets in French about AI news.

**Flow:** `main.py` (scheduler) → `src/bot.py` (`run_bot_cycle`) → `src/agent.py` (`generate_tweet`) → `src/twitter_client.py` (`post_tweet`)

- **`src/agent.py`** — Shells out to the `claude` CLI (`subprocess.run`) with `--allowedTools web_search`. The CLI runs under the Claude Code subscription — no API key needed.
- **`src/bot.py`** — Thin orchestration: calls agent, prints result, posts tweet.
- **`src/twitter_client.py`** — Wraps Tweepy v2 `client.create_tweet`.
- **`main.py`** — APScheduler `BlockingScheduler` with a randomized interval that reschedules itself after each run.

## Key design notes

- Tweets are in French, 280 chars max, targeting a French-speaking AI audience.
- No Anthropic API key or external news API needed — the `claude` CLI handles both search and generation.
- The `claude` CLI must be installed and authenticated (`claude login`) on the machine running the bot.
