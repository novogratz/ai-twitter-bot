---
name: improve
description: Self-improvement cycle. Scrapes tweet performance, finds what works, updates prompts. Run periodically.
allowed-tools: Bash Read Write Edit
---

## Step 1: Scrape performance

```bash
python3 -c "from src.performance import evaluate_and_learn; print(evaluate_and_learn())"
```

## Step 2: Read data

- `performance_log.json` — tweets with likes/views
- `learnings.json` — top/worst performers
- `engagement_log.csv` — all actions with timestamps

## Step 3: Edit prompts based on data (only if 3x+ delta)

- `src/agent.py` — news tweet prompt
- `src/hotake_agent.py` — hot take prompt
- `src/reply_agent.py` — reply prompt

## Step 4: Commit and push

Include what data drove the change in the commit message.
