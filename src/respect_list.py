"""Respect list — handles the bot must NEVER criticize by name.

User incident 2026-05-06 PM: "Some big influencers blocked the bot ...
you got to be careful not attacking them." The bot's spicy / hot take /
quote-tweet / breakout paths can occasionally name an influencer in a
sharp commentary — that reads as a personal attack and gets us blocked
by the very people we want to engage with.

This module exposes a SOFT list (different from BLOCKLIST in config.py
which is HARD — never engage at all). Respect list = engage normally
(reply, like, follow), BUT:
  - NEVER name them in spicy / hot take / news / breakout content
  - NEVER quote-tweet them with a critical observation
  - REPLIES must comment on the IDEA in their tweet, not on them
  - No "@xxxx" tag in our standalone posts

Public API:
  load() -> set of lowercased handles (no @)
  add(handle, reason="") -> persists, dedups
  remove(handle)
  is_protected(handle_or_user_string) -> bool (handles common shapes)
  scrub_text_or_skip(text) -> (cleaned_text, reason_if_skipped)
       Final-line defense: if generated content names a protected
       handle, returns (None, "names protected handle @x"). Caller
       should SKIP the post.
  render_block() -> str — for prompt injection.
"""
import json
import os
import re
from datetime import datetime
from typing import Optional, Tuple

from .config import _PROJECT_ROOT
from .logger import log

RESPECT_FILE = os.path.join(_PROJECT_ROOT, "respect_list.json")

# Sensible defaults — high-traction FR accounts we engage with regularly.
# We'd rather under-include and add manually than offend them by accident.
# These are people the bot's spicy / quote / hot take output should
# NEVER name. (Replies on their content remain fine; the protection is
# about commentary that targets THEM by name.)
_DEFAULTS = {
    # FR AI / tech mega
    "korbeninfo": "Influence FR tech massive — éviter critique par nom.",
    "underscore_": "Tech FR — éviter critique par nom.",
    "micode": "Tech FR — éviter critique par nom.",
    "frandroid": "Média FR tech — éviter critique par nom.",
    "numerama": "Média FR tech — éviter critique par nom.",
    "presse_citron": "Média FR tech — éviter critique par nom.",
    "siecledigital": "Média FR tech — éviter critique par nom.",
    "01net": "Média FR tech — éviter critique par nom.",
    "usine_digitale": "Média FR tech — éviter critique par nom.",
    # FR finance / crypto media
    "lesechos": "Presse financière FR — éviter critique par nom.",
    "lemondefr": "Presse FR — éviter critique par nom.",
    "lefigaro": "Presse FR — éviter critique par nom.",
    "bfmtv": "Média FR — éviter critique par nom.",
    "bfmbusiness": "Média FR finance — éviter critique par nom.",
    "lejournalducoin": "Crypto FR — éviter critique par nom.",
    "cryptoastmedia": "Crypto FR — éviter critique par nom.",
    "cointribune": "Crypto FR — éviter critique par nom.",
    "coinacademy_fr": "Crypto FR — éviter critique par nom.",
    # Big FR crypto / bourse personalities we engage daily
    "powerhasheur": "Influenceur FR crypto — éviter critique par nom.",
    "owen_simonin": "Influenceur FR crypto — éviter critique par nom.",
    "mathieul1": "Bourse FR — éviter critique par nom.",
    "graphseo": "Bourse FR — éviter critique par nom.",
    "fintales_": "Bourse FR — éviter critique par nom.",
    "flasheurinvest": "Bourse FR — éviter critique par nom.",
    "cryptopicsou": "Crypto FR — éviter critique par nom.",
    "rodolphesteffan": "Bourse FR — éviter critique par nom.",
    "matthiasbaccino": "Bourse FR — éviter critique par nom.",
    # Mega FR + QC tech / IA voices
    "yoshua_bengio": "Légende IA québécoise — never criticize.",
    "arthurmensch": "CEO Mistral, FR AI star — never criticize.",
    "guillaumelample": "FR AI researcher (ex-Mistral) — never criticize.",
    "gaelvaroquaux": "FR AI scikit-learn — never criticize.",
    "cyrildiagne": "FR AI artist — never criticize.",
}


def _load_raw() -> dict:
    if os.path.exists(RESPECT_FILE):
        try:
            with open(RESPECT_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # First-time init — seed with defaults.
    seed = {
        "handles": {h: {"reason": r, "added": datetime.now().isoformat()} for h, r in _DEFAULTS.items()},
    }
    try:
        with open(RESPECT_FILE, "w") as f:
            json.dump(seed, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return seed


def _save_raw(d: dict):
    with open(RESPECT_FILE, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def load() -> set:
    """Return the current respect list as a set of lowercased handles."""
    return set(_load_raw().get("handles", {}).keys())


def add(handle: str, reason: str = "") -> bool:
    h = (handle or "").lower().lstrip("@").strip()
    if not h or len(h) > 15:
        return False
    d = _load_raw()
    d.setdefault("handles", {})
    if h in d["handles"]:
        return False
    d["handles"][h] = {
        "reason": reason or "manually added",
        "added": datetime.now().isoformat(),
    }
    _save_raw(d)
    log.info(f"[RESPECT] Added @{h} ({reason})")
    return True


def remove(handle: str) -> bool:
    h = (handle or "").lower().lstrip("@").strip()
    d = _load_raw()
    if h in d.get("handles", {}):
        del d["handles"][h]
        _save_raw(d)
        log.info(f"[RESPECT] Removed @{h}")
        return True
    return False


def _normalize_handle(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lstrip("@").lower()
    # Strip URL prefix shapes: "x.com/foo" -> "foo"
    m = re.search(r"(?:x\.com|twitter\.com)/([^/?#]+)", s)
    if m:
        return m.group(1).lower()
    return s


def is_protected(handle_or_user_string: str) -> bool:
    h = _normalize_handle(handle_or_user_string)
    return h in load()


def scrub_text_or_skip(text: str) -> Tuple[Optional[str], str]:
    """Final-line defense before any bot ships generated content.

    If the text NAMES a protected handle (either as `@foo` or as the
    bare token `foo` adjacent to clear-attack signals), we return
    (None, reason). Caller MUST treat None as a SKIP — this is more
    important than the daily cap.

    Returns (text, "") on pass.
    """
    if not text:
        return text, ""
    protected = load()
    if not protected:
        return text, ""

    # 1. @handle mentions of protected accounts
    for m in re.finditer(r"@([A-Za-z0-9_]{1,15})", text):
        h = m.group(1).lower()
        if h in protected:
            return None, f"output names protected handle @{h}"

    # 2. Bare-token "ridicule" mentions (e.g. "Korben dit n'importe quoi"
    #    where "Korben" is a known display-name handle). To keep the
    #    false-positive rate low, we only trigger if (a) the bare handle
    #    appears AND (b) a clearly-derisive token also appears in the
    #    same sentence/window.
    derisive_markers = (
        " ridicule", " bullshit", " mensonge", " arnaque", " zéro talent",
        " comprend rien", " sait pas", " incompétent", " escroc",
        " menteur", " menteuse", "nuls", " naïf", " naïve",
    )
    lower = text.lower()
    if any(d in lower for d in derisive_markers):
        for h in protected:
            # Bare handle must appear surrounded by word boundaries.
            if re.search(rf"\b{re.escape(h)}\b", lower):
                return None, f"derisive language alongside protected handle '{h}'"

    return text, ""


def render_block() -> str:
    """Prompt block injected into HARD rules. Names are present so the
    model sees them up-front rather than relying on post-hoc scrub."""
    handles = sorted(load())
    if not handles:
        return ""
    sample = ", ".join(f"@{h}" for h in handles[:30])
    extra = f" (+{len(handles)-30} autres)" if len(handles) > 30 else ""
    return (
        "==================================================\n"
        "RESPECT LIST — comptes a NE JAMAIS critiquer NOMMEMENT\n"
        "==================================================\n"
        "Tu peux engager (replies, likes) sur le contenu de ces comptes,\n"
        "mais tu ne dois JAMAIS:\n"
        "- les nommer dans une hot take, news, breakout, ou spicy take\n"
        "- les quote-tweeter avec une observation critique\n"
        "- les ridiculiser, ironiser sur leur personne, ou mocker leur travail\n"
        "Si l'idee dans leur tweet est critiquable, tu critiques l'IDEE,\n"
        "jamais la personne. En cas de doute -> SKIP.\n\n"
        f"Liste actuelle: {sample}{extra}.\n"
    )
