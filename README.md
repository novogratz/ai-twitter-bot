# ai-twitter-bot

A Twitter bot that autonomously searches the web for the latest AI news and tweets about it in French, powered by Claude.

## How it works

On each scheduled run, a Claude agent (`claude-opus-4-6` with adaptive thinking) uses its built-in web search tool to find recent AI news, picks the most interesting story, and writes a French tweet (≤280 chars) with relevant hashtags. No external news API required — Claude handles the search itself.

The bot fires every 15–20 minutes (randomized) using APScheduler.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with your credentials:

| Variable | Where to get it |
|---|---|
| `TWITTER_API_KEY` / `TWITTER_API_SECRET` | [developer.twitter.com](https://developer.twitter.com) |
| `TWITTER_ACCESS_TOKEN` / `TWITTER_ACCESS_TOKEN_SECRET` | Twitter Developer Portal |
| `TWITTER_BEARER_TOKEN` | Twitter Developer Portal |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

## Usage

```bash
python main.py
```

The bot will log the generated tweet and its ID each time it posts. Stop with `Ctrl+C`.
