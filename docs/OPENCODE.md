# OpenCode + @kzer_ai

> Codex is the default provider. Use this page when explicitly switching to OpenCode for local-model testing.

## Setup

```bash
# Already done — brew install on macOS:
which opencode     # /opt/homebrew/bin/opencode

# Local Ollama setup used by this repo's `opencode.json`:
echo "AI_CLI=opencode" >> .env
echo "NEWS_MODEL=ollama/qwen3-coder:30b" >> .env
```

## Available models

Run `opencode models` to list all models:

| Model | Notes |
|---|---|
| `ollama/qwen3-coder:30b` | Local model configured in `opencode.json` |
| `opencode/big-pickle` | Hosted OpenCode model |
| `opencode/ring-2.6-1t-free` | Lighter, faster, free |
| `opencode/minimax-m2.5-free` | Alternative free model |
| `opencode/nemotron-3-super-free` | Alternative free model |

Set any model in `.env` per surface:

```env
AI_CLI=opencode
NEWS_MODEL=ollama/qwen3-coder:30b
REPLY_MODEL=ollama/qwen3-coder:30b
HOTAKE_MODEL=ollama/qwen3-coder:30b
```

## Running the bot (Python scheduler)

```bash
./bin/run.sh
```

This runs the APScheduler-based bot from `main.py`. All LLM calls go through `src/llm_client.py` which now speaks opencode.

## Running as an agent (replace main.py)

Use the `run-agent` skill. OpenCode runs the bot loop itself with native WebSearch + Bash:

```bash
opencode run --model ollama/qwen3-coder:30b --dangerously-skip-permissions
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

The `unwrap_text()` function handles OpenCode JSON events, NDJSON streams, JSON envelopes (Claude/Gemini), and raw text (Codex).

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
| `Provider: codex` in logs | Set `AI_CLI=opencode` in `.env` only for OpenCode test runs |
| Slow generations | Use `opencode/ring-2.6-1t-free` for reply/quote surfaces |
| Raw JSON appears in generated text | Keep `src/llm_client.py` current; `unwrap_text()` parses OpenCode JSON events before falling back to raw text |
| `command not found: opencode` | Run `brew install opencode` |
