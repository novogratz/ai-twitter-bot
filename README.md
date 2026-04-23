# ai-twitter-bot

The sharpest AI account on X/Twitter. Fastest news. Hardest takes. 0% bullshit. Powered by Claude Code.

## How it works

The bot runs three systems:

**Post bot** - Invokes the `claude` CLI with web search to find the freshest AI news (last hour first). Writes sharp English tweets (280 chars max) or 2-3 tweet threads for big stories. Posts via browser + AppleScript. No API keys needed.

**Reply bot** - Searches X for popular AI tweets and drops funny, sharp one-liner replies. Targets rising tweets (posted 10-30 min ago) and big accounts (10k+ followers) for maximum visibility. Auto-likes tweets before replying. 20-30% of replies are quote tweets that show up on your own timeline. Replies match the language of the original tweet.

**Engage bot** - Visits 3-5 target AI accounts every 30 minutes and likes their latest tweet. Builds reciprocity (they engage back) and signals activity to the algorithm.

## Schedule

Posts follow a time-based schedule (EST):
- Night (11pm-6am): every 45-75 min
- Morning rush (6am-10am): every 15-20 min
- Midday (10am-5pm): every 40 min
- Evening rush (5pm-7pm): every 15 min
- Wind down (7pm-11pm): every 40 min

Reply bot adapts to peak hours:
- Peak (6-9am, 2-5pm EST, 2-4am EST for France): every 3-5 min
- Default: every 8 min
- Late night: every 15-20 min

Engage bot runs every 30 minutes, 24/7.

## Growth features

- **Rising tweet targeting** - Replies to tweets posted 10-30 min ago with early engagement. Your reply sits at the top of the thread.
- **Big account filter** - Prioritizes accounts with 10k+ followers for replies.
- **Quote tweets** - 20-30% of replies become quote tweets visible on your timeline.
- **Like + reply combo** - Auto-likes before replying for double notification.
- **Thread posting** - 2-3 tweet threads for big stories, boosted by the algorithm.
- **Engagement pods** - Auto-likes tweets from target AI accounts for reciprocity.
- **Cross-dedup** - Reply bot avoids topics the post bot just covered.
- **Follow CTA** - ~25% of posts include "Follow @kzer_ai" call to action.
- **Safari cleanup** - Auto-closes tabs after every action to prevent memory buildup.

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
# Run the bot (posts, replies, and engages continuously)
python main.py

# Post a single tweet manually
python test_tweet.py
```

Stop with `Ctrl+C`.

## Requirements

- macOS (posting uses AppleScript to automate browser clicks)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on your default browser (Safari)
