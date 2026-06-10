"""Engine-health watchdog — catch a collapsed surface in hours, not days.

Post-mortem 2026-06-05: retweets ran 140/day → 0 for TWO DAYS (dropped scrape
timestamps) and replies 397 → 42 (eaten JSON) before anyone noticed — the
collapse was invisible in bot.log noise and only obvious in engagement_log.csv
daily counts.

This bot runs hourly: for each action type it compares today's count SO FAR
against the average count at the same hour-of-day over the previous 7 days.
If today's pace is below ALERT_RATIO (40%) of the baseline (and the baseline
is meaningful), it logs a loud alert and records it in
engine_health_alerts.json (picked up by the daily digest / operator).
"""
import csv
import json
import os
import traceback
from collections import defaultdict
from datetime import date, datetime, timedelta

from .config import _PROJECT_ROOT
from .logger import log

ENGAGEMENT_LOG = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
ALERTS_FILE = os.path.join(_PROJECT_ROOT, "engine_health_alerts.json")

ALERT_RATIO = float(os.environ.get("ENGINE_HEALTH_ALERT_RATIO", "0.4"))
MIN_BASELINE = float(os.environ.get("ENGINE_HEALTH_MIN_BASELINE", "5"))
WATCHED_TYPES = ("reply", "retweet", "quote", "post", "hotake")

# Env-var caps that govern each watched surface. When the operator sets a cap
# to 0 (e.g. MAX_RETWEETS_PER_DAY=0 under the 2026-06-05 PM monetization
# mandate — bare retweets OFF), the surface is INTENTIONALLY disabled.
# Comparing 0 today against a multi-day pre-mandate baseline would otherwise
# fire a "collapsed" alert every cycle and burn the self-heal cooldown on a
# surface that was deliberately turned off. Read at call time so live edits
# to live_strategy.json / .env take effect without restart.
_CAP_ENVS: dict = {
    "reply": ("MAX_REPLIES_PER_DAY",),
    "retweet": ("MAX_RETWEETS_PER_DAY",),
    "quote": ("MAX_QUOTES_PER_DAY", "MAX_QUOTE_REPOSTS_PER_DAY"),
    "post": ("MAX_ORIGINALS_PER_DAY",),
    "hotake": ("MAX_HOTAKES_PER_DAY",),
}


def _is_surface_disabled(kind: str) -> bool:
    """A surface is disabled only when EVERY cap that governs it is 0.
    Unset env var = not disabled (defaults live elsewhere)."""
    env_names = _CAP_ENVS.get(kind, ())
    if not env_names:
        return False
    caps = []
    for name in env_names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return False
        try:
            caps.append(int(raw))
        except ValueError:
            return False
    return all(c == 0 for c in caps)


def _daily_cap_for(kind: str) -> int | None:
    """Smallest positive daily cap that governs this surface, or None if no
    cap is set in the env. The baseline is then clamped by this cap so the
    watchdog cannot compare today against an unreachable historical level
    after the operator lowered a cap (e.g. hotake: cap 8 → 2 under the
    2026-06-05 PM monetization mandate left a 7-day baseline of ~19 by mid-
    morning, against which today's 2 — a fully-spent quota — looked
    'collapsed' at 11% and burned the self-heal cooldown every cycle)."""
    env_names = _CAP_ENVS.get(kind, ())
    if not env_names:
        return None
    caps: list = []
    for name in env_names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        try:
            v = int(raw)
        except ValueError:
            continue
        if v > 0:
            caps.append(v)
    return min(caps) if caps else None


def _counts_by_day_hour() -> tuple[dict, dict]:
    """Returns ``(counts, latest_hour_today)`` for the last 8 days.

    ``counts``: ``{(date_str, type): count_up_to_current_hour}`` — same-hour-of-day
    sums for the baseline.
    ``latest_hour_today``: ``{type: max_hour_seen_today}`` — used to tell whether
    a surface fired recently. A below-baseline-but-still-firing surface is not a
    collapse, just a slower cadence; sustained silence is what we actually want
    to alert on.
    """
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=8)).isoformat()
    hour_now = datetime.now().hour
    counts: dict = defaultdict(int)
    latest_hour_today: dict = {}
    try:
        with open(ENGAGEMENT_LOG) as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if len(row) < 2:
                    continue
                ts, kind = row[0], row[1]
                # GIF variants are the SAME surface (2026-06-10 02:06 false
                # alarm: "quote collapsed: 4 today" while quote_gif ships at
                # 01:16/01:36/01:58 were invisible to the 'quote' bucket —
                # both the count AND the recent-fire guard missed them, and
                # a self-heal run was burned on a healthy lane).
                if kind == "quote_gif":
                    kind = "quote"
                if len(ts) < 13 or ts[:10] < cutoff:
                    continue
                try:
                    row_hour = int(ts[11:13])
                except ValueError:
                    continue
                # Same-hour-of-day comparison: only count actions up to the
                # current hour so today's partial day compares fairly.
                if row_hour <= hour_now:
                    counts[(ts[:10], kind)] += 1
                if ts[:10] == today:
                    prev = latest_hour_today.get(kind, -1)
                    if row_hour > prev:
                        latest_hour_today[kind] = row_hour
    except OSError:
        pass
    return counts, latest_hour_today


# Process start time — a cumulative-by-hour comparison is meaningless right
# after boot: if the bot was stopped for hours (operator purge, restart),
# every surface reads 0-by-this-hour vs baseline and the watchdog fires a
# false "collapse" for each one, burning self-heal Claude runs on a healthy
# engine (witnessed live 2026-06-07: emergency session spawned for "reply
# collapsed: 0 today" minutes after a boot). Surfaces need runway to act
# before today's count can be judged.
_PROCESS_START = datetime.now()
WARMUP_MINUTES = int(os.environ.get("ENGINE_HEALTH_WARMUP_MINUTES", "90"))


def _in_warmup(now=None) -> bool:
    now = now or datetime.now()
    return (now - _PROCESS_START) < timedelta(minutes=WARMUP_MINUTES)


# Originals are SLOT-SCHEDULED (08:30-21:30 NY crons since 2026-06-07; no
# overnight interval jobs anymore) — but the 7-day baseline still contains
# pre-slot-era overnight firing. At 02:06 on 2026-06-10 this produced
# "hotake collapsed: 1 today vs ~8 by this hour" on an engine that was
# QUIET BY DESIGN, and burned a self-heal run. Overnight/early-morning
# silence on a slot surface is policy, not collapse: skip evaluation
# outside the slot window (+runway for the first morning slots).
_SLOT_SURFACES = ("post", "hotake")
SLOT_EVAL_FROM_HOUR = int(os.environ.get("ENGINE_HEALTH_SLOT_EVAL_FROM", "11"))
SLOT_EVAL_UNTIL_HOUR = int(os.environ.get("ENGINE_HEALTH_SLOT_EVAL_UNTIL", "22"))


def _in_slot_quiet_hours(kind: str, hour_now: int) -> bool:
    if kind not in _SLOT_SURFACES:
        return False
    return hour_now < SLOT_EVAL_FROM_HOUR or hour_now >= SLOT_EVAL_UNTIL_HOUR


def run_engine_health_cycle():
    if _in_warmup():
        mins = int((datetime.now() - _PROCESS_START).total_seconds() / 60)
        log.info(f"[ENGINE_HEALTH] Warmup ({mins}/{WARMUP_MINUTES} min since "
                 f"boot) — surfaces need runway before today's counts mean "
                 f"anything. Skipping checks.")
        return
    today = date.today().isoformat()
    hour_now = datetime.now().hour
    counts, latest_hour_today = _counts_by_day_hour()
    prev_days = [(date.today() - timedelta(days=i)).isoformat() for i in range(1, 8)]

    alerts = []
    summary = []
    for kind in WATCHED_TYPES:
        if _is_surface_disabled(kind):
            summary.append(f"{kind}: OFF (cap=0)")
            continue
        if _in_slot_quiet_hours(kind, hour_now):
            summary.append(f"{kind}: slot-quiet hours — not evaluated")
            continue
        baseline_vals = [counts.get((d, kind), 0) for d in prev_days]
        active_days = [v for v in baseline_vals if v > 0]
        if not active_days:
            continue  # surface was never active this week — nothing to compare
        baseline = sum(active_days) / len(active_days)
        cap = _daily_cap_for(kind)
        if cap is not None:
            baseline = min(baseline, cap)
        today_count = counts.get((today, kind), 0)
        summary.append(f"{kind}: {today_count} vs {baseline:.0f} avg")
        if baseline >= MIN_BASELINE and today_count < ALERT_RATIO * baseline:
            # A surface that fired in the current or previous hour is alive —
            # slow, not collapsed. The baseline averages full-runtime days; if
            # today started behind (operator-restart, slower cadence, a stretch
            # of skips) and is now firing again, comparing the cumulative against
            # a steady-state baseline produces a false positive. Sustained
            # silence — ≥2 clock hours without a single fire — still alerts.
            # Born from 2026-06-06/07: hotake fired at 03:23, 03:43, 04:02 (max
            # 20-min cadence) but the 04:01 cycle still reported "collapsed:
            # 2 vs 10" and burned the self-heal cooldown on a healthy bot.
            # NOTE: a missing entry must NEVER count as "fired recently" —
            # the old `.get(kind, -1) >= hour_now - 1` sentinel collided at
            # midnight (hour_now=0 → -1 >= -1) and suppressed every alert
            # during the 00:00 hour (found 2026-06-10 when the guard tests
            # flaked only after midnight).
            latest_fire = latest_hour_today.get(kind)
            if latest_fire is not None and latest_fire >= hour_now - 1:
                continue
            alerts.append(
                f"{kind} collapsed: {today_count} today vs ~{baseline:.0f} "
                f"by this hour over the last 7 days ({today_count / baseline:.0%})"
            )

    log.info(f"[ENGINE_HEALTH] {'; '.join(summary) if summary else 'no baseline yet'}")
    if not alerts:
        return

    for a in alerts:
        log.error(f"[ENGINE_HEALTH] ⚠️ ALERT: {a}")
    payload = {"ts": datetime.now().isoformat(), "alerts": alerts}
    try:
        existing = []
        if os.path.exists(ALERTS_FILE):
            with open(ALERTS_FILE) as f:
                existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
        existing.append(payload)
        with open(ALERTS_FILE, "w") as f:
            json.dump(existing[-50:], f, indent=2)
    except (OSError, json.JSONDecodeError):
        pass
    _maybe_trigger_self_heal(alerts)


_SELF_HEAL_STAMP = os.path.join(_PROJECT_ROOT, ".last_self_heal")


def _maybe_trigger_self_heal(alerts: list) -> None:
    """Self-healing (full-agentic mandate 2026-06-05): a collapse alert
    launches an EMERGENCY headless Claude run (bin/auto_improve.sh
    --emergency) to root-cause and fix it — instead of waiting for a human
    to read the log. Rate-limited to one run per SELF_HEAL_COOLDOWN_HOURS;
    the script itself is single-flight and never starts the bot.

    Env vars (ENABLE_SELF_HEAL, SELF_HEAL_COOLDOWN_HOURS) are read at call
    time, not import time. Born from a 2026-06-07 incident: the test suite
    calls run_engine_health_cycle() with synthetic 'reply collapsed' data
    and sets monkeypatch.setenv('ENABLE_SELF_HEAL', '0') to suppress the
    subprocess — but the kill-switch was a module-level constant evaluated
    at import, so the env patch had no effect and the test launched a real
    headless Claude emergency run (which then ran THIS file as 'emergency
    diagnose'). Reading at call time means monkeypatch + live .env edits
    both take effect without restart."""
    enable_self_heal = os.environ.get("ENABLE_SELF_HEAL", "1") == "1"
    cooldown_h = float(os.environ.get("SELF_HEAL_COOLDOWN_HOURS", "6"))
    if not enable_self_heal or not alerts:
        return
    try:
        if os.path.exists(_SELF_HEAL_STAMP):
            age_h = (datetime.now().timestamp() - os.path.getmtime(_SELF_HEAL_STAMP)) / 3600
            if age_h < cooldown_h:
                log.info(f"[ENGINE_HEALTH] self-heal on cooldown ({age_h:.1f}h < {cooldown_h}h).")
                return
        with open(_SELF_HEAL_STAMP, "w") as f:
            f.write(datetime.now().isoformat())
        import subprocess
        script = os.path.join(_PROJECT_ROOT, "bin", "auto_improve.sh")
        subprocess.Popen(
            [script, "--emergency", "; ".join(alerts)[:500]],
            cwd=_PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        log.error("[ENGINE_HEALTH] 🚑 Self-heal triggered: emergency Claude diagnose run launched.")
    except Exception as e:
        log.info(f"[ENGINE_HEALTH] self-heal trigger failed (non-fatal): {e}")


def safe_run_engine_health_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_engine_health_cycle()
        health.record_success("engine_health")
    except Exception:
        log.info("[ENGINE_HEALTH] Error during health cycle:")
        traceback.print_exc()
        health.record_failure("engine_health")
