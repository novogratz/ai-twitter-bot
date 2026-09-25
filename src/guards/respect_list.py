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
  scrub_text_or_skip(text, addressee="") -> (cleaned_text, reason_if_skipped)
       Final-line defense: if generated content names a protected
       handle, returns (None, "names protected handle @x"). `addressee`
       is the author a Reply answers: its `@handle` passes, never its
       name next to a derisive word. An Original has no addressee. The
       write chokepoints refuse the post, dry run included: `post_tweet`
       for an Original, Reply admission for a Reply, which sets the
       post aside for good.
  render_block() -> str — for prompt injection, every handle named.

The file is guarded: while respect_list.json is unreadable, every function
that reads it raises StateUnreadable, render_block included, and nothing
overwrites it.
"""
import os
import re
from datetime import datetime
from typing import Optional, Tuple

from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile

RESPECT = StateFile("respect_list.json", {}, GUARDED)

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
    if os.path.exists(RESPECT.path):
        return RESPECT.read()
    # First-time init — seed with defaults.
    seed = {
        "handles": {h: {"reason": r, "added": datetime.now().isoformat()} for h, r in _DEFAULTS.items()},
    }
    try:
        RESPECT.write(seed)
    except StateUnreadable:
        pass
    return seed


def _save_raw(d: dict):
    RESPECT.write(d)


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


def scrub_text_or_skip(text: str, addressee: str = "") -> Tuple[Optional[str], str]:
    """Final-line defense before any bot ships generated content.

    If the text NAMES a protected handle (either as `@foo` or as the
    bare token `foo` in a sentence with a clear-attack signal), we return
    (None, reason). Caller MUST treat None as a SKIP — this is more
    important than the daily cap. The `@addressee` of a Reply is not a
    mention; the attack signal next to its name still is.

    Returns (text, "") on pass.
    """
    if not text:
        return text, ""
    protected = load()
    if not protected:
        return text, ""
    addressee = (addressee or "").lower().lstrip("@")

    # 1. @handle mentions of protected accounts
    for m in re.finditer(r"@([A-Za-z0-9_]{1,15})", text):
        h = m.group(1).lower()
        if h in protected and h != addressee:
            return None, f"output names protected handle @{h}"

    # 2. Bare-token "ridicule" mentions (e.g. "Korben dit n'importe quoi"
    #    where "Korben" is a known display-name handle). To keep the
    #    false-positive rate low, we only trigger if the bare handle and a
    #    clearly-derisive token appear in the same sentence.
    derisive_markers = (
        " ridicule", " bullshit", " mensonge", " arnaque", " zéro talent",
        " comprend rien", " incompétent", " escroc",
        " menteur", " menteuse", "nuls", " naïf", " naïve",
    )
    for sentence in re.split(r"(?<=[.!?…])\s+|\n+", text.lower()):
        sentence = f" {sentence}"
        if not any(d in sentence for d in derisive_markers):
            continue
        for h in protected:
            # Bare handle must appear surrounded by word boundaries.
            if re.search(rf"\b{re.escape(h)}\b", sentence):
                return None, f"derisive language alongside protected handle '{h}'"

    return text, ""


def render_block() -> str:
    """Prompt block injected into HARD rules. Names are present so the
    model sees them up-front rather than relying on post-hoc scrub.

    Raises StateUnreadable while the file is unreadable."""
    handles = sorted(load())
    if not handles:
        return ""
    names = ", ".join(f"@{h}" for h in handles)
    return (
        "==================================================\n"
        "RESPECT LIST — accounts you must NEVER criticize BY NAME\n"
        "==================================================\n"
        "You may engage (replies, likes) with these accounts' content,\n"
        "but you must NEVER:\n"
        "- name them in a hot take, news post, breakout or spicy take\n"
        "- quote-tweet them with a critical observation\n"
        "- ridicule them, be ironic about them as people, or mock their work\n"
        "If the idea in their post deserves criticism, criticize the IDEA,\n"
        "never the person. When in doubt -> SKIP.\n\n"
        f"Current list: {names}.\n"
    )
