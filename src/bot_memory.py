"""Lightweight on-disk memory so the bot has continuity + a personality.

The account should feel like one sharp mind that REMEMBERS what it said — able
to call back to an earlier thesis when it's now playing out ("la thèse RKLB que
je posais il y a 3 semaines: +40% depuis"). This reads the existing
tweet_history.json (no new state to maintain) and produces a compact French
digest that gets injected into every content prompt via lang_mode.

It is advisory context, NOT a command to force a callback — the prompt tells
the model to reference a past take ONLY when it genuinely adds value, with the
date, so it reads as memory and never as spam.
"""
import json
import os
import re
import time
from datetime import datetime

from .config import _PROJECT_ROOT

_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")

_CACHE_TEXT = ""
_CACHE_AT = 0.0
_CACHE_TTL = 600  # 10 min — history changes slowly; keep prompt-building cheap.


def _clean(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    # Drop the trailing source URL so the digest is pure thesis.
    t = re.sub(r"https?://\S+\s*$", "", t).strip()
    return t


def _first_line_summary(text: str, limit: int = 110) -> str:
    """A one-line gist: prefer the substantive line over the '🔎 The Decode #N'
    header so the memory captures the actual take, not the boilerplate."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    body = ""
    for l in lines:
        if l.startswith("🔎") or re.match(r"^(le d[ée]code|the decode)", l, re.IGNORECASE):
            continue
        body = l
        break
    body = _clean(body or (lines[0] if lines else ""))
    return (body[:limit] + "…") if len(body) > limit else body


def recent_digest(max_items: int = 6) -> str:
    """Return a compact French 'MÉMOIRE RÉCENTE' block of the last few posts,
    or '' if there's no usable history. Cached for _CACHE_TTL seconds."""
    global _CACHE_TEXT, _CACHE_AT
    if _CACHE_TEXT and (time.time() - _CACHE_AT) < _CACHE_TTL:
        return _CACHE_TEXT
    try:
        with open(_HISTORY_FILE) as f:
            hist = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(hist, list) or not hist:
        return ""

    items = []
    for entry in reversed(hist):
        if len(items) >= max_items:
            break
        if not isinstance(entry, dict):
            continue
        gist = _first_line_summary(entry.get("text", ""))
        if not gist or len(gist) < 20:
            continue
        ts = entry.get("timestamp", "")
        day = ""
        try:
            day = datetime.fromisoformat(ts).strftime("%d/%m") if ts else ""
        except ValueError:
            day = ""
        items.append(f"- {day + ' — ' if day else ''}{gist}")

    if not items:
        _CACHE_TEXT, _CACHE_AT = "", time.time()
        return ""

    block = (
        "\n==================================================\n"
        "MÉMOIRE RÉCENTE (tes derniers posts — tu es UN cerveau qui se souvient)\n"
        "==================================================\n"
        + "\n".join(items)
        + "\n→ Tu PEUX faire un rappel à une de tes prises passées UNIQUEMENT si "
        "ça apporte une vraie valeur (une thèse qui se confirme, un chiffre qui "
        "évolue), toujours avec la date. Jamais de répétition gratuite, jamais "
        "le même angle deux fois. Si ça n'ajoute rien → ignore ce bloc.\n"
    )
    _CACHE_TEXT, _CACHE_AT = block, time.time()
    return block
