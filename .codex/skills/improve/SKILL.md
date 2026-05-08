---
name: improve
description: Self-improvement cycle. Evaluates tweet performance, discovers what works, and updates the bot's prompts and strategy based on data. Run this periodically to make the bot smarter.
allowed-tools: Bash Read Write Edit Grep WebSearch
---

You are the bot's strategy optimizer. Your job is to look at real performance data and improve the bot's prompts and strategy.

## Step 1: Scrape Performance

Run: `python3 -c "from src.performance import evaluate_and_learn; r = evaluate_and_learn(); print(r)"`

This scrapes likes and views from the bot's recent tweets and saves learnings.

## Step 2: Read the Data

1. Read `performance_log.json` - all scraped tweets with likes/views
2. Read `learnings.json` - current top/worst performers
3. Read `engagement_log.csv` - all posts/replies with timestamps

## Step 3: Analyze

Look at the data and figure out:
- Which TOPICS get the most likes? (AI companies? regulation? tools? drama?)
- Which FORMATS work? (questions? one-liners? threads? predictions?)
- Which TONE works? (funny? serious? skeptical? excited?)
- What TIME of day performs best?
- Do shorter tweets outperform longer ones?
- Do tweets with hashtags do better or worse?
- Do tweets tagging companies get more engagement?
- What reply style gets the most likes?

## Step 4: Update Strategy

Based on your analysis, edit the bot's prompts to double down on what works:
- `src/agent.py` - News tweet prompt (tone, format, topics)
- `src/hotake_agent.py` - Hot take prompt (style, examples)
- `src/reply_agent.py` - Reply prompt (troll style, targeting)

Make SPECIFIC changes based on DATA. Don't guess. For example:
- "Tweets about OpenAI drama get 3x more likes -> add more OpenAI search terms"
- "Questions get 2x more engagement -> increase question frequency"
- "Tweets under 100 chars get more likes -> tighten character limits"

## Step 5: Commit and Push

After making changes, commit with a message explaining what you learned and what you changed.
Include the performance data in the commit message.

Then push to git.

## Step 6: Report

Tell the user:
- What the data showed
- What changes you made
- Expected impact
