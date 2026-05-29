# Operations runbook

How to run, watch, debug, and tune the bot.

---

## 1. First-time setup

```bash
git clone <repo>
cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- Set `BOT_HANDLE` to your X username (without `@`)
- Set `AI_CLI` to `ollama` for the local default, with `LLM_FALLBACK_CLI=codex`
- Set the model defaults if you explicitly switch away from Ollama
- Adjust caps to match your tier

Authenticate the AI CLI:
```bash
codex login          # backup provider when Ollama fails
```

Open Safari, log into x.com, accept all cookies, dismiss any onboarding modals.

Verify the boot path:
```bash
python3 -c "import main"   # should print nothing
```

---

## 2. Running the bot

### Foreground (recommended for daily use)

```bash
./bin/run.sh
```

- Runs in this terminal.
- Output streams to stdout AND tees to `bot.log`.
- Press **Ctrl-C** to stop cleanly.
- Closing the terminal kills the bot.

### Stop from another terminal

```bash
./bin/stop.sh
```

Sends SIGTERM, waits 3s, escalates to SIGKILL if needed.

### Autonomous mode (LaunchAgent)

For production / unattended operation. Bot starts at login, auto-respawns on crash, survives reboots.

```bash
./bin/install_autonomous.sh
```

Logs go to `bot.log` and `bot.err` exactly as in foreground mode. Verify:

```bash
launchctl list | grep com.kzer
tail -F bot.log
```

To pause without uninstalling:
```bash
launchctl unload ~/Library/LaunchAgents/com.kzer.ai-twitter-bot.plist
```

To resume:
```bash
launchctl load ~/Library/LaunchAgents/com.kzer.ai-twitter-bot.plist
```

To take back manual control:
```bash
./bin/uninstall_autonomous.sh
```

---

## 3. Watching the bot

### Real-time log tail

```bash
tail -F bot.log
```

Filter for a specific bot:
```bash
tail -F bot.log | grep -E "\[NEWS\]|\[BREAKOUT\]|\[SPIKE\]"
```

### Heartbeat sanity check

The heartbeat bot writes one line every 60s. If you don't see `[HEARTBEAT] alive HH:MM:SS` for >2 min, the bot is hung. Either:
- Safari is locked → `pkill Safari` to recover (the watchdog should also catch this)
- A scheduler thread deadlocked → `./bin/stop.sh && ./bin/run.sh`

### Daily digest

`daily_digest.md` is overwritten daily with yesterday's rollup. Read it for a high-level signal of:
- Total actions (posts, replies, RTs, follows)
- Top sources / authors
- Comedy-pattern distribution
- Top-performing posts
- Follow count delta

### Autonomy audit on startup

The bot prints an audit block on boot:
```
============================================================
AUTONOMY AUDIT — bot self-modifies + auto-pushes the following:
  STRATEGIC ADAPTATION (auto-decides + auto-pushes to git):
    [4h] meta_strategy_agent  → live_strategy.json
    [3h] strategy_agent       → dynamic_queries / dynamic_accounts
    ...
============================================================
```

If a bot you expected to see is missing, check `main.py` for the `scheduler.add_job` call.

---

## 4. Debugging

### "Bot won't start"

```bash
python3 -c "import main"
```
If this fails with an `ImportError`, the broken module is in the traceback. Fix the import in that module.

### "A specific bot keeps failing"

`grep "\[<BOT>\] Error" bot.log | tail -5`

Each failure is logged with a traceback. The Safari watchdog auto-restarts Safari after 3 consecutive failures, but if a Python bug is the root cause, restart won't help — fix the bug.

### "x.com shows a blank / black screen in Safari"

This is a stale service-worker issue. The bot now fixes it automatically:
- **On every Safari relaunch**: `safari_hygiene` navigates to x.com, unregisters all service workers, clears all caches, and hard-reloads before handing control back to the bot.
- **Reactive**: after 5 consecutive `NO_ARTICLES` scrape responses, `twitter_client` auto-triggers a Safari restart with a 5-min cooldown.

To force a manual recovery:
```bash
# From the macOS prompt while the bot is stopped:
osascript -e 'tell application "Safari" to quit'
sleep 3 && open -a Safari
# Then start the bot normally — _warm_up_xcom() runs automatically.
```

### "Bot is suddenly silent"

Check the suppression watchdog:
```bash
cat suppression_state.json
```

If `paused_until` is in the future, the bot detected a shadowban-like signal (avg likes < 1) and paused `spicy`, `breakout`, `follow_blast` for 4h. This is intentional. The other surfaces (replies, likes, retweets) keep running.

### "Bot is posting things I don't want"

Add the offending handle to the respect list:
```bash
python3 -c "from src.respect_list import add; add('handle', 'reason')"
```

Or to the hard blocklist (`config.BLOCKLIST` — requires editing `src/config.py`).

The bot will pick up the change on the next cycle (no restart needed for `respect_list`; restart for `BLOCKLIST`).

### "Bot is too aggressive / posting too much"

Edit `.env`:
```
MAX_NEWS_PER_DAY=8
MAX_HOTAKES_PER_DAY=4
MAX_QUOTES_PER_DAY=15
MAX_RETWEETS_PER_DAY=20
RETWEETS_PER_CYCLE=1
```

Restart. Or wait 4h for `meta_strategy_agent` to re-evaluate (it adapts caps based on engagement).

### "Bot is not aggressive enough"

Edit `.env` to raise the same caps. Or:

```bash
echo '{"caps": {"MAX_NEWS_PER_DAY": 30, "MAX_RETWEETS_PER_DAY": 60}, "cadence_factor": 0.7, "topic_focus": ["AI agents", "BTC ETF", "NVDA earnings"]}' > live_strategy.json
```

This overrides `.env` until the next `meta_strategy_agent` cycle.

---

## 5. Tuning playbook

After 24-48h of running, look at `daily_digest.md` and the top 5 / worst 5 tweets in `engagement_log.csv`:

```bash
# Top 5 tweets in the last 24h by likes (requires performance_log.json populated)
python3 -c "
import json
with open('performance_log.json') as f:
    data = json.load(f)
top = sorted(data, key=lambda x: x.get('likes', 0), reverse=True)[:5]
for t in top:
    print(f\"{t['likes']} likes — {t['text'][:120]}\")
"
```

Common patterns and what to do:

| Symptom | Tune |
|---|---|
| Replies hit, posts flop | Drop `MAX_NEWS_PER_DAY`, raise `MAX_REPLIES_PER_CYCLE`. Replies are the working surface. |
| All output is mid | Tighten quality gate in `agent.py` (8/10 → 9/10) and freshness (24h → 12h). |
| Same topic 3x in a day | Check `topic_dedup.py` is working; raise dedup window. |
| Bot followers stagnant | Pin a banger manually. Update bio. Raise `FOLLOW_BLAST_PER_CYCLE`. |
| Followers but no engagement | Bot looks like a follow-spam account. Run `smart_unfollow_bot` more often. |
| Off-niche posts | Tighten `NICHE_KEYWORDS` regex in `retweet_bot.py`. Or extend `OFF_TOPIC_KEYWORDS`. |

### Switching language mode

```bash
# All content in EN (default)
echo "CONTENT_LANG_PRIMARY=en" >> .env
# All content in FR
echo "CONTENT_LANG_PRIMARY=fr" >> .env
# 70% EN / 30% FR per cycle
echo "CONTENT_LANG_PRIMARY=mixed" >> .env
```

Replies always match parent tweet language regardless.

---

## 6. State files reference

Files that change at runtime. Most are auto-pushed to git by their producing agent.

| File | Producer | Purpose |
|---|---|---|
| `daily_state.json` | `bot.py` | News + hot take daily counters |
| `bot.log` / `bot.err` | scheduler | Stdout / stderr (rotated by `cleanup_bot`) |
| `engagement_log.csv` | `engagement_log.py` | Append-only log of every action |
| `performance_log.json` | `performance.py` | Scraped own metrics |
| `learnings.json` | `performance.py` | Top/worst + insights for prompt injection |
| `personality.json` | `reflection_agent` | Per-account dossiers + topic positions |
| `bot_self.json` | `self_evolution_agent` | Mood, obsession, voice tweaks, drift |
| `live_strategy.json` | `meta_strategy_agent` | Daily caps + cadence factor + topic focus |
| `directives.md` | `evolution_agent` | Style guide (overwritten each cycle) |
| `dynamic_queries.json` | `strategy_agent` | Auto-added search queries |
| `dynamic_accounts.json` | `strategy_agent` + `scout_agent` | Auto-added accounts to engage |
| `pruned_accounts.json` | `evolution_agent` | Demoted accounts (TTL 30d) |
| `reinforced_accounts.json` | `evolution_agent` | 2x-weight accounts |
| `respect_list.json` | `respect_list.py` | Soft-list of protected handles |
| `external_signal.json` | `rss_signal_bot` + `hn_signal_bot` + `x_home_scout_bot` | Merged real-time pulse |
| `follower_history.json` | `follower_tracker_bot` | Time series of follower count |
| `replied_tweets.json` | `reply_bot` + `direct_reply` | URL dedup |
| `replied_back.json` | `notify_bot` | Replyback dedup |
| `retweeted.json` | `retweet_bot` | Retweet dedup |
| `quoted_tweets.json` | `quote_tweet_bot` | Quote-post dedup |
| `followed_accounts.json` | `engage_bot` | Tracked follows |
| `do_not_refollow.json` | `smart_unfollow_bot` | Anti-churn list |
| `safari_health.json` | `health.py` | Per-bot success/failure counts |
| `suppression_state.json` | `suppression_watch_bot` | Shadowban-pause state |
| `boost_history.json` | `notify_bot` | Boost dedup |
| `breakout_history.json` | `breakout_bot` | Breakout dedup |
| `spike_history.json` | `spike_bot` | Spike orchestration dedup |
| `viral_followed_up.json` | `viral_followup_bot` | Followup dedup |
| `pin_history.json` | `pin_bot` | Pin dedup |
| `promoted_replies.json` | `promote_bot` | Promo dedup |

Counter / state files (one per bot):
`thread_daily_state.json`, `digest_thread_state.json`, `breakout_state.json`, `spicy_state.json`, `quote_daily_state.json`, `retweet_daily_state.json`, `pin_daily_state.json`, `cleanup_state.json`, `roast_state.json`.

---

## 7. Common operations

| What | How |
|---|---|
| Stop the bot now | `./bin/stop.sh` |
| Reset daily counters | `echo '{"date":"'$(date +%Y-%m-%d)'","news":0,"hotakes":0}' > daily_state.json` |
| Force a news cycle now (foreground) | `python3 -c "from src.bot import run_bot_cycle; run_bot_cycle()"` |
| Force monthly Top 10 recaps now | `python3 main.py --monthly-recap-now` |
| Force a retweet cycle now | `python3 -c "from src.retweet_bot import run_retweet_cycle; run_retweet_cycle()"` |
| Force a quote cycle now | `python3 -c "from src.quote_tweet_bot import run_quote_tweet_cycle; run_quote_tweet_cycle()"` |
| Manually pin a tweet | `python3 -c "from src.twitter_client import pin_own_tweet; pin_own_tweet('https://x.com/<you>/status/<id>')"` |
| Add a handle to respect list | `python3 -c "from src.respect_list import add; add('handle','reason')"` |
| Disable a specific bot temporarily | Comment out its `scheduler.add_job` call in `main.py` and restart |
| Snapshot current state to git | `git add . && git commit -m "snapshot" && git push` |
