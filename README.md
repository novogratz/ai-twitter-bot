# @TheAIShrink — AI knowledge, useful updates, and conversation

A Safari-driven AI account with the voice of a confident, warm, playfully flirty
45-year-old mom who loves AI. The bot aims to give readers something useful in
every post and respond naturally in conversations.

## Current publishing policy

- **Active daily: 04:30–22:00 America/Toronto**, with daylight saving handled automatically.
- **Six original posts planned; seven is the hard daily ceiling.** Weak drafts are skipped.
- **Unlimited replies during waking hours**, with spacing and duplicate protection.
  Every reply passes Reply admission before generation (before sending for
  the optional search job, whose one model call finds and drafts together)
  and again at the write: blocked accounts, the account's own posts and links without an
  author handle are refused.
  If the replied store (`replied_tweets.json`) is unreadable, no reply ships until
  it is repaired ([recovery](docs/OPERATIONS.md#recovery)).
- **No automatic quote tweets, reposts, self-recycling, startup bursts, or burst threads.**
- Every scheduled original uses a fetched primary source, a specific takeaway,
  duplicate checks, and a separate editorial review before publishing.
- The 500,000-view target is tracked using observed views of originals published
  in the last seven days. Public view counters cannot identify home-timeline views.

The bot stays idle overnight and resumes automatically. Browser operations and
model calls check the waking window too, so a queued daytime task cannot start
a new action after 22:00. An already-issued request may still finish remotely.

## Daily editorial mix

| Toronto time | Reader value |
|---|---|
| 05:00 | An AI update worth understanding |
| 08:00 | A practical AI workflow |
| 11:30 | A clear explanation of an AI concept |
| 14:30 | A model or tool update and its consequences |
| 17:30 | An informed take on an AI tradeoff |
| 20:30 | An idea worth saving or sharing |
| 21:30 | Optional seventh post, only for an exceptional update from the last six hours |

Each slot has a short retry window. Restarts do not trigger a backlog of posts.
Originals have their own scheduler worker so reply scans cannot starve them.
See [editorial policy](docs/EDITORIAL_POLICY.md) for review and recovery details.

## Run

Requires macOS, Safari with JavaScript from Apple Events enabled, Python 3.12+,
[uv](https://docs.astral.sh/uv/), and the configured local Ollama models. Originals use `gemma4:31b` by default
(`EDITORIAL_OLLAMA_MODEL`); replies use the existing reply model.

```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env
uv run python main.py
```

`.env.example` predates the current account: fix `.env` as described in
[setup](docs/OPERATIONS.md#setup) before the first run.

```bash
uv run --with-requirements requirements.txt python main.py --dry-run  # print policy/jobs and exit; no browser or LLM
uv run --with-requirements requirements.txt python main.py --reply-only  # daytime conversations only
uv run --with-requirements requirements.txt python main.py --post-only   # editorial originals only
uv run --with pytest --with-requirements requirements.txt python -m pytest tests/ -q
```

`bot.log` contains runtime activity. `editorial_review.jsonl` records decisions;
`editorial_state.json` persists attempts, completed slots and source history;
`editorial_reach.md` shows measured reach and missing coverage. These are local
runtime files and are not committed to Git.

Scheduled jobs are defined in `main.py`. `src/editorial_bot.py` handles source
selection, drafting and review. `src/active_hours.py` owns the Toronto clock.
`src/action_guard.py` and `src/twitter_client.py` enforce limits at the browser
boundary. The legacy content modules are gone (issue #110): every module under
`src/` is reached from `main.py`. The quote, repost, thread and GIF write
functions are removed from `src/twitter_client.py` (issue #111), and the
scheduled jobs carry no such branch.

Autonomous prompt/code rewriting is excluded from the active scheduler. Old
`.env` or strategy values cannot lift the seven-post ceiling or restore quotes.
The configured reply provider and browser pacing still apply.

## License

[MIT](LICENSE) — © 2026 Benoit Floch.
