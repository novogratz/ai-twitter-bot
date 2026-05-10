# OpenCode + @kzer_ai

> OpenCode is **free** — no API key, no credit card, no auth needed.

## Setup

```bash
# Already done — brew install on macOS:
which opencode     # /opt/homebrew/bin/opencode

# No login required. Just set the env:
echo "AI_CLI=opencode" >> .env
echo "NEWS_MODEL=opencode/big-pickle" >> .env
```

## Available models

Run `opencode models` to list all models:

| Model | Notes |
|---|---|
| `opencode/big-pickle` | Default — good quality, free |
| `opencode/ring-2.6-1t-free` | Lighter, faster, free |
| `opencode/minimax-m2.5-free` | Alternative free model |
| `opencode/nemotron-3-super-free` | Alternative free model |

Set any model in `.env` per surface:

```env
AI_CLI=opencode
NEWS_MODEL=opencode/big-pickle
REPLY_MODEL=opencode/ring-2.6-1t-free
HOTAKE_MODEL=opencode/big-pickle
```

## Running the bot (Python scheduler)

```bash
./bin/run.sh
```

This runs the APScheduler-based bot from `main.py`. All LLM calls go through `src/llm_client.py` which now speaks opencode.

## Running as an agent (replace main.py)

Use the `run-agent` skill. OpenCode runs the bot loop itself with native WebSearch + Bash:

```bash
opencode run --model opencode/big-pickle --dangerously-skip-permissions
```

Then type `/run-agent` to start the loop.

## Using other providers (OpenRouter, Qwen, etc.)

OpenCode can connect to any OpenAI-compatible API provider:

```bash
opencode providers login <url>
```

Qwen models via OpenRouter:

```bash
opencode providers login https://openrouter.ai/api/v1 --api-key <key>
# Then: opencode run --model openrouter/qwen-2.5-72b-instruct
```

Or via a direct Qwen API endpoint if available.

## How it works

`src/llm_client.py` builds the CLI command:

```
opencode run --model <model> [--format json] [--dangerously-skip-permissions] "<prompt>"
```

- Default format → raw text output, works for most generation
- `--format json` → NDJSON events, parsed by `_unwrap_ndjson()`
- `--dangerously-skip-permissions` → headless, no approval prompts

The `unwrap_text()` function handles all three output formats: NDJSON (opencode --format json), JSON envelopes (claude/gemini), and raw text (codex).

## Model format

OpenCode uses `provider/model` naming:

```
opencode/model-name
openrouter/model-name
anthropic/claude-sonnet-4-20250514
openai/gpt-4o
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Provider: codex` in logs | Set `AI_CLI=opencode` in `.env` |
| Slow generations | Use `opencode/ring-2.6-1t-free` for reply/quote surfaces |
| `command not found: opencode` | Run `brew install opencode` |
