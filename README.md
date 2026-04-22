# ai-twitter-bot

An autonomous AI news bot for X/Twitter, powered by Claude Code. It scouts the freshest and most wild AI stories, then posts sharp, funny, occasionally savage takes as @kzer_ai.

## How it works

On each scheduled run, the bot invokes the `claude` CLI with web search enabled. Claude finds the best AI news, picks the most shocking or juicy story, and writes an English tweet (280 chars max) with attitude. No API keys of any kind required. Posting happens via your browser + AppleScript.

The bot fires every 35-45 minutes (randomized), only during 6am-11pm EST.

## Setup

```bash
pip install -r requirements.txt
```

Install and authenticate the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

That's it. No Twitter API keys, no Anthropic API key, nothing else.

## Usage

```bash
# Run the bot (posts on a schedule)
python main.py

# Post a single tweet manually
python test_tweet.py
```

Stop with `Ctrl+C`.

## Requirements

- macOS (posting uses AppleScript to auto-click the tweet button)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on your default browser
