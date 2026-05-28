---
name: strategy
description: Weekly strategy review using Claude - updates directives.md, adjusts live_strategy.json, and reviews prompt performance. Run once a week.
allowed-tools: Bash Read Write Edit
---

Weekly strategy update (Claude-powered). Run once a week.

## Step 1: Trigger style evolution

```bash
python3 -c "from src.style_evolution_bot import run_style_evolution_cycle; run_style_evolution_cycle()"
```

This scrapes viral X formats and rewrites `directives.md` using Claude Sonnet.

## Step 2: Read performance data

- `performance_insights.json` — top patterns, best topics, viral examples
- `learnings.json` — top/worst performers
- `live_strategy.json` — current caps and cadence

## Step 3: Adjust live_strategy.json

Based on performance data, tune caps and cadence in `live_strategy.json`:
- Raise daily cap for top-performing content types
- Lower cap for underperformers
- Adjust `cadence_factor` (0.5 = slow, 1.0 = normal, 1.5 = aggressive)

## Step 4: Update key prompts if needed

Only edit if data shows a clear pattern (3x+ delta):
- `src/agent.py` — news tweet prompt
- `src/hotake_agent.py` — hot take prompt
- `src/reply_agent.py` — reply prompt

## Step 5: Commit and push

```bash
git add directives.md live_strategy.json src/agent.py src/hotake_agent.py src/reply_agent.py
git commit -m "Weekly strategy update — $(date +%Y-%m-%d)"
git push
```

## Report

Tell the user: what changed, why, expected impact in 3 bullet points.
