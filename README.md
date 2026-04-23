# ai-twitter-bot

The sharpest AI account on X/Twitter. Fastest news. Hardest takes. 0% bullshit. Powered by Claude Code.

## How it works

The bot runs two systems:

**Post bot** - Every cycle, invokes the `claude` CLI with web search enabled. Claude finds the freshest AI news (last hour first), picks the best angle, and writes a sharp English tweet (280 chars max). Posts via browser + AppleScript. No API keys needed.

**Reply bot** - Every 8 minutes, searches X for popular AI tweets and drops a funny, sharp one-liner reply. Replies match the language of the original tweet. The goal: be quotable, make people curious enough to check the profile.

## Schedule

Posts follow a time-based schedule (EST):
- Night (11pm-6am): every 45-75 min
- Morning rush (6am-10am): every 15-20 min
- Midday (10am-5pm): every 40 min
- Evening rush (5pm-7pm): every 15 min
- Wind down (7pm-11pm): every 40 min

Reply bot runs every 8 minutes, 24/7.

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
# Run the bot (posts and replies continuously)
python main.py

# Post a single tweet manually
python test_tweet.py
```

Stop with `Ctrl+C`.

## Requirements

- macOS (posting uses AppleScript to automate browser clicks)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on your default browser
