#!/usr/bin/env python3
"""Suggester agent (operator 2026-06-24: "an agent suggesting new things for
the bot to make it more active and get more likes and more followers").

SUGGESTS ONLY — never edits code or config (operator wants the bot static).
Every cycle it reads the real engagement data and appends concrete,
prioritized ideas to suggestions.md with a timestamp. Deterministic analysis
+ (best-effort) a few fresh Claude-generated ideas. Safe to run forever.

Run once:   python scripts/suggest_improvements.py
Loop:       python scripts/suggest_improvements.py --loop   (every ~60 min)
"""
import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENG = os.path.join(ROOT, "engagement_log.csv")
PERF = os.path.join(ROOT, "performance_log.json")
FOLL = os.path.join(ROOT, "follower_history.json")
OUT = os.path.join(ROOT, "suggestions.md")
INTERVAL = int(os.environ.get("SUGGEST_INTERVAL_SECONDS", "3600"))


def _recent_actions(hours: int = 24) -> Counter:
    cut = (datetime.now() - timedelta(hours=hours)).isoformat()
    c: Counter = Counter()
    try:
        with open(ENG) as f:
            for r in csv.reader(f):
                if r and len(r) > 1 and r[0] >= cut:
                    c[r[1]] += 1
    except OSError:
        pass
    return c


def _follower_delta(hours: int = 24):
    try:
        d = json.load(open(FOLL))
        if not isinstance(d, list) or not d:
            return None, None
        now = d[-1].get("count")
        cut = (datetime.now() - timedelta(hours=hours)).isoformat()
        past = next((e["count"] for e in d if e.get("ts", "") >= cut), d[0].get("count"))
        return now, (now - past if now is not None and past is not None else None)
    except (OSError, ValueError, KeyError):
        return None, None


def _top_posts(n: int = 5):
    try:
        d = json.load(open(PERF))
        rows = sorted(d, key=lambda x: x.get("likes", 0), reverse=True)[:n]
        return [(r.get("likes", 0), r.get("views", 0), (r.get("text") or "")[:90]) for r in rows]
    except (OSError, ValueError):
        return []


def _claude_ideas(summary: str) -> str:
    """Best-effort: ask Claude for 3 fresh growth ideas. Skips if unavailable."""
    if not subprocess.run(["which", "claude"], capture_output=True).returncode == 0:
        return ""
    prompt = (
        "You advise an AI-news Twitter/X bot (@TheAIShrink, AI Therapist voice). "
        "Goal: more activity, more likes, more followers. Here is the last 24h:\n\n"
        f"{summary}\n\n"
        "Give 3 SPECIFIC, concrete, do-able suggestions (new content angle, a "
        "format to try, an account type to engage, a timing tweak). One line "
        "each, no preamble, no fluff. Be sharp and actionable."
    )
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True,
                           text=True, timeout=120, cwd="/tmp")
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def run_once() -> None:
    acts = _recent_actions(24)
    followers, fdelta = _follower_delta(24)
    tops = _top_posts(5)

    summary_lines = [
        f"- Actions (24h): {dict(acts) or 'none'}",
        f"- Followers: {followers if followers is not None else '?'} "
        f"({'+' if (fdelta or 0) >= 0 else ''}{fdelta if fdelta is not None else '?'} /24h)",
    ]
    if tops:
        summary_lines.append("- Top posts by likes:")
        summary_lines += [f"    {l}L {v}V  {t}" for l, v, t in tops]
    summary = "\n".join(summary_lines)

    # Deterministic flags
    flags = []
    replies = acts.get("reply", 0)
    quotes = acts.get("quote", 0) + acts.get("quote_gif", 0)
    posts = acts.get("post", 0) + acts.get("hotake", 0)
    if replies < 100:
        flags.append(f"Replies low ({replies}/24h) — likely downtime; keep the watchdog up.")
    if posts < 15:
        flags.append(f"Originals low ({posts}/24h) — check news/hotake cadence + caps.")
    if fdelta is not None and fdelta <= 0:
        flags.append("Followers flat/down — lean into replying under the biggest AI accounts + "
                     "follow-back from big AI followers.")
    if tops and max((l for l, _, _ in tops), default=0) <= 1:
        flags.append("Posts getting ~0 likes — push the funny/relatable one-liner format; "
                     "lead with the feeling, not the data.")

    ideas = _claude_ideas(summary)

    block = [
        f"\n## {datetime.now().isoformat(timespec='minutes')}",
        summary,
    ]
    if flags:
        block.append("\n**Flags:**")
        block += [f"- {x}" for x in flags]
    if ideas:
        block.append("\n**Fresh ideas:**\n" + ideas)
    block.append("")

    with open(OUT, "a") as f:
        f.write("\n".join(block) + "\n")
    print(f"[suggest] appended suggestions to {OUT}")


def main() -> None:
    if not os.path.exists(OUT):
        with open(OUT, "w") as f:
            f.write("# Bot improvement suggestions (auto-generated, SUGGEST-ONLY)\n"
                    "# The suggester never edits code/config. Operator reviews + decides.\n")
    if "--loop" in sys.argv:
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[suggest] error: {e}")
            time.sleep(INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()
