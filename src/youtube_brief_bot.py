"""YouTube brief bot — daily aggregator that turns the bot's day into
a video-script-ready brief.

User pivot 2026-05-09 PM: the bot is now the research engine for a
YouTube channel. It posts FR news + reshares EN content + drops sharp
takes. Every day, the operator wants a single Markdown file they can
open and turn into a 3-7 minute video script.

Strategy:
  - Once per day (idempotent via youtube_brief_state.json).
  - Aggregate from the past 24h:
      * Top 10 own posts by engagement (from performance_log)
      * Top 10 retweets (from retweeted.json + daily_news_picks.md)
      * Top 5 quote-tweets
      * Top 5 viral reply targets
      * RSS / HN signal hits we covered
  - Group by theme (AI / crypto / bourse).
  - Write to `youtube_brief.md` (overwritten each day) AND append a
    dated section to `youtube_brief_archive.md` (append-only history).
  - Auto-push both to git.

Output format is intentionally script-friendly: each item has a
hook, the source, and a "video angle" suggestion the operator can
hand directly to a YouTube voiceover.
"""
import csv
import json
import os
import traceback
from collections import defaultdict
from datetime import date, datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE, BOT_HANDLE
from .logger import log

YT_BRIEF_FILE = os.path.join(_PROJECT_ROOT, "youtube_brief.md")
YT_ARCHIVE_FILE = os.path.join(_PROJECT_ROOT, "youtube_brief_archive.md")
YT_STATE_FILE = os.path.join(_PROJECT_ROOT, "youtube_brief_state.json")
DAILY_PICKS_FILE = os.path.join(_PROJECT_ROOT, "daily_news_picks.md")
PERF_FILE = os.path.join(_PROJECT_ROOT, "performance_log.json")
EXTERNAL_SIGNAL_FILE = os.path.join(_PROJECT_ROOT, "external_signal.json")


# --- theme classifier ---

_AI = re.compile(
    r"\b(ai|ia|llm|gpt|claude|chatgpt|gemini|llama|mistral|nvidia|nvda|"
    r"openai|anthropic|deepmind|hugging\s?face|datacenter|gpu|tpu|"
    r"agi|copilot|perplexity|robot|agent)\b",
    re.IGNORECASE,
) if False else None  # placeholder, defined below

import re
_RE_AI = re.compile(
    r"\b(ai|ia|llm|gpt|claude|chatgpt|gemini|llama|mistral|nvidia|nvda|"
    r"openai|anthropic|deepmind|hugging\s?face|datacenter|gpu|tpu|"
    r"agi|copilot|perplexity|robot|agent|huggingface)\b",
    re.IGNORECASE,
)
_RE_CRYPTO = re.compile(
    r"\b(bitcoin|btc|ethereum|eth|crypto|stablecoin|coinbase|binance|"
    r"defi|nft|solana|ripple|xrp|etf|halving|sec lawsuit)\b",
    re.IGNORECASE,
)
_RE_BOURSE = re.compile(
    r"\b(stock|nasdaq|s&p|s\&p|cac40|ipo|earnings|fed|fomc|"
    r"tesla|apple|google|alphabet|meta|amazon|microsoft|valuation|"
    r"billion|trillion|merger|acquisition)\b",
    re.IGNORECASE,
)


def _classify_theme(text: str) -> str:
    """Pick the dominant theme. AI > crypto > bourse > other."""
    if _RE_AI.search(text):
        return "AI"
    if _RE_CRYPTO.search(text):
        return "Crypto"
    if _RE_BOURSE.search(text):
        return "Bourse"
    return "Other"


# --- input loaders ---

def _load_perf() -> list:
    if not os.path.exists(PERF_FILE):
        return []
    try:
        with open(PERF_FILE, "r") as f:
            return json.load(f) or []
    except Exception:
        return []


def _load_engagement_24h() -> list:
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return []
    cutoff = datetime.now() - timedelta(hours=24)
    rows = []
    try:
        with open(ENGAGEMENT_LOG_FILE, "r") as f:
            r = csv.reader(f)
            for row in r:
                if not row or len(row) < 4:
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                rows.append({
                    "ts": ts,
                    "type": row[1],
                    "text": row[2] if len(row) > 2 else "",
                    "url": row[3] if len(row) > 3 else "",
                    "source": row[4] if len(row) > 4 else "",
                })
    except Exception:
        pass
    return rows


def _load_signal() -> list:
    if not os.path.exists(EXTERNAL_SIGNAL_FILE):
        return []
    try:
        with open(EXTERNAL_SIGNAL_FILE, "r") as f:
            d = json.load(f) or {}
        return d.get("items", [])[:10]
    except Exception:
        return []


def _load_daily_picks_today() -> str:
    """Read today's section from daily_news_picks.md (the YouTube research
    doc retweet_bot writes to)."""
    if not os.path.exists(DAILY_PICKS_FILE):
        return ""
    try:
        with open(DAILY_PICKS_FILE, "r") as f:
            body = f.read()
    except Exception:
        return ""
    today = date.today().isoformat()
    # Find the most recent "## YYYY-MM-DD" section.
    parts = body.split(f"\n## {today}")
    if len(parts) < 2:
        # Fall back to last "## " section.
        last = body.rsplit("\n## ", 1)
        if len(last) == 2:
            return "## " + last[1].split("\n## ")[0]
        return ""
    section = parts[1].split("\n## ")[0]
    return f"## {today}{section}"


# --- state ---

def _already_ran_today() -> bool:
    if not os.path.exists(YT_STATE_FILE):
        return False
    try:
        with open(YT_STATE_FILE, "r") as f:
            return json.load(f).get("date") == date.today().isoformat()
    except Exception:
        return False


def _mark_ran_today():
    with open(YT_STATE_FILE, "w") as f:
        json.dump({"date": date.today().isoformat(), "ts": datetime.now().isoformat()}, f)


# --- brief assembly ---

def _build_brief() -> str:
    today = date.today().isoformat()
    perf = _load_perf()
    engage = _load_engagement_24h()
    signal = _load_signal()
    picks = _load_daily_picks_today()

    # Top own posts by likes (from performance_log).
    posts = sorted(perf, key=lambda x: int(x.get("likes") or 0), reverse=True)[:10]

    # 24h activity grouped by type.
    by_type = defaultdict(list)
    for r in engage:
        by_type[r["type"]].append(r)

    # Top retweets (already filtered by retweet_bot, listed in daily_picks).
    # Top quotes / replies (from engage by likes is hard — we only have text +
    # source, not the like count yet — those get scraped by performance later).

    # Theme grouping for posts.
    by_theme = defaultdict(list)
    for p in posts:
        text = p.get("text", "")
        by_theme[_classify_theme(text)].append(p)

    out = []
    out.append(f"# YouTube brief — {today}")
    out.append("")
    out.append(
        "*Auto-generated daily by the bot. Pick 3-5 items from this brief, "
        "voice them in 3-7 minutes, you have a video.*"
    )
    out.append("")

    # === Headline number block ===
    out.append("## 🔢 Activity (last 24h)")
    out.append("")
    out.append(f"- Total actions logged: **{len(engage)}**")
    for t, items in sorted(by_type.items(), key=lambda kv: len(kv[1]), reverse=True):
        out.append(f"- {t}: **{len(items)}**")
    out.append("")

    # === Top posts by theme ===
    out.append("## 🥇 Top own posts (by likes)")
    out.append("")
    for theme in ("AI", "Crypto", "Bourse", "Other"):
        items = by_theme.get(theme, [])[:5]
        if not items:
            continue
        out.append(f"### {theme}")
        out.append("")
        for it in items:
            likes = int(it.get("likes") or 0)
            views = int(it.get("views") or 0)
            text = (it.get("text") or "").strip()[:200].replace("\n", " ")
            out.append(f"- **{likes} likes / {views} views** — {text}")
        out.append("")

    # === Curated retweet picks (already YouTube-formatted) ===
    if picks:
        out.append("## 📡 Today's news picks (from retweet_bot)")
        out.append("")
        out.append("*The retweet bot scores trusted-source tweets 1-10 and "
                   "logs the best to daily_news_picks.md. Below is today's "
                   "section — these are the strongest stories you should "
                   "consider for your video.*")
        out.append("")
        out.append(picks)
        out.append("")

    # === External signal pulse ===
    if signal:
        out.append("## ⚡ Real-time external signal (RSS + HN + Reddit)")
        out.append("")
        for it in signal[:8]:
            src = it.get("src", "?")
            title = (it.get("title") or "").strip()[:160]
            url = it.get("url", "")
            out.append(f"- **[{src}]** {title}")
            if url:
                out.append(f"  - {url}")
        out.append("")

    # === Video angles ===
    out.append("## 🎬 Suggested video angles")
    out.append("")
    out.append(
        "Pick the theme that has the densest activity above. Recipe:\n"
        "- 30s hook: the most surprising number or quote of the day.\n"
        "- 2min context: the 2-3 biggest stories in that theme.\n"
        "- 1min angle: what no other YT channel is saying about it.\n"
        "- 30s call-to-action: comment + subscribe + the bot's @kzer_ai handle.\n"
    )
    out.append("")
    out.append(f"*Generated {datetime.now().isoformat(timespec='seconds')}*")
    return "\n".join(out)


def _append_archive(today: str, body: str):
    """Append today's brief to the historical archive."""
    section = f"\n\n========== {today} ==========\n\n{body}\n"
    try:
        with open(YT_ARCHIVE_FILE, "a") as f:
            f.write(section)
    except Exception:
        log.info("[YT-BRIEF] Archive append failed:")
        traceback.print_exc()


def run_youtube_brief_cycle():
    if _already_ran_today():
        return

    log.info("[YT-BRIEF] Generating daily YouTube brief...")
    brief = _build_brief()

    try:
        with open(YT_BRIEF_FILE, "w") as f:
            f.write(brief)
    except Exception:
        log.info("[YT-BRIEF] Write failed:")
        traceback.print_exc()
        return

    _append_archive(date.today().isoformat(), brief)
    _mark_ran_today()
    log.info(f"[YT-BRIEF] Wrote {YT_BRIEF_FILE} ({len(brief)} chars).")


def safe_run_youtube_brief_cycle():
    from . import health
    try:
        run_youtube_brief_cycle()
        health.record_success("youtube_brief")
        try:
            from .git_ops import auto_push
            auto_push(
                ["youtube_brief.md", "youtube_brief_archive.md", "youtube_brief_state.json"],
                "Autonomous YouTube brief — daily content rollup",
            )
        except Exception:
            log.info("[YT-BRIEF] auto_push failed (non-fatal):")
            traceback.print_exc()
    except Exception:
        log.info("[YT-BRIEF] Error during cycle:")
        traceback.print_exc()
        health.record_failure("youtube_brief")
