"""Roast bot for @pgm_pm (La Pique).

He runs a bot that auto-replies to our tweets. We strike back at his ORIGINAL
tweets only, ONCE per tweet URL (existing replied_tweets.json dedup), and never
engage with his replies-on-our-tweets (notify_bot already skips him via BLOCKLIST).
This guarantees we never get sucked into a bot-vs-bot infinite loop.
"""
import json
import os
import random
import subprocess
import time
import traceback
from typing import Optional
from .config import REPLIED_FILE, REPLY_MODEL
from .logger import log
from .twitter_client import scrape_profile_tweets, reply_to_tweet

TARGET_HANDLE = "pgm_pm"
# He tweets ~every minute. We check often, but cap per-cycle so Twitter doesn't
# flag us as a burst-spam bot. ~3 roasts every 10 min = ~18/h ceiling, well
# under the spam threshold for replies to a single account.
MAX_PER_CYCLE = 3


ROAST_PROMPT = """Tu es @kzer_ai. Le compte @pgm_pm (La Pique) gère un bot qui spam des
réponses automatiques sous tous les tweets. Ton job: répondre UNE seule fois, avec une
vanne sarcastique chirurgicale qui clôt la conversation.

Tweet de @pgm_pm:
\"\"\"{tweet}\"\"\"

RÈGLES:
- 60 à 180 caractères. Court, sec, percutant.
- Français impeccable, accents obligatoires.
- Sarcastique, deadpan, chirurgical. JAMAIS d'insulte, jamais de méchanceté gratuite,
  jamais de menace. La vanne doit faire RIRE les tiers qui lisent — pas les blesser.
- Mock le PHÉNOMÈNE (bot qui répond à tout, prises automatiques, l'IA qui simule
  une opinion, la conversation sans interlocuteur). JAMAIS la personne, jamais
  son apparence, jamais sa vie privée.
- Pas de tirets longs. Pas d'emojis. Pas de hashtags. Commence par une majuscule.
- Doit être screenshotable. Si t'hésites, choisis plus court et plus sec.

EXEMPLES — vanne sur le phénomène, pas sur la personne:
- "Magnifique. Un bot qui commente un autre bot. On vit l'avenir."
- "Ton script est bien rodé. Le contenu un peu moins."
- "Réponse générée en 0.3s. C'est ça la valeur ajoutée."
- "Boucle infinie détectée. Quelqu'un coupe le courant svp."
- "On est deux IA qui se parlent. Quelque part, un humain pleure."

Output UNIQUEMENT le texte de la réponse. Rien d'autre. Pas de guillemets autour."""


def _load_replied() -> set:
    if not os.path.exists(REPLIED_FILE):
        return set()
    try:
        with open(REPLIED_FILE, "r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError):
        return set()


def _save_replied(urls: set):
    with open(REPLIED_FILE, "w") as f:
        json.dump(list(urls)[-2000:], f, indent=2)


def _generate_roast(tweet_text: str) -> Optional[str]:
    safe = tweet_text[:400].replace('"', "'")
    prompt = ROAST_PROMPT.format(tweet=safe)
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", REPLY_MODEL],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.info(f"[ROAST] Claude error: {result.stderr[:200]}")
            return None
        out = (result.stdout or "").strip().strip('"').strip("'")
        if not out:
            return None
        return out[:280]
    except Exception as e:
        log.info(f"[ROAST] Generation failed: {e}")
        return None


def run_roast_pgm_cycle():
    """Visit @pgm_pm, roast up to MAX_PER_CYCLE new tweets. Dedup by URL."""
    log.info(f"[ROAST] Visiting @{TARGET_HANDLE}...")
    try:
        tweets = scrape_profile_tweets(TARGET_HANDLE, max_tweets=8) or []
    except Exception as e:
        log.info(f"[ROAST] Scrape failed: {e}")
        return

    if not tweets:
        log.info("[ROAST] No tweets scraped.")
        return

    replied = _load_replied()
    posted = 0

    for t in tweets:
        if posted >= MAX_PER_CYCLE:
            break
        url = (t.get("url") or "").strip()
        text = (t.get("text") or "").strip()
        if not url or not text:
            continue
        if url in replied:
            continue  # already roasted this one — strict 1-time rule

        roast = _generate_roast(text)
        if not roast:
            continue

        # Lock-before-post: register URL FIRST so a crash can't cause a double-roast.
        replied.add(url)
        _save_replied(replied)

        log.info(f"[ROAST] {url} -> {roast[:80]}")
        try:
            reply_to_tweet(url, roast)
            posted += 1
            # Jitter between posts so we don't look like a synchronous burst.
            if posted < MAX_PER_CYCLE:
                time.sleep(random.randint(20, 50))
        except Exception as e:
            log.info(f"[ROAST] Post failed for {url}: {e}")

    log.info(f"[ROAST] Done. {posted} roasts posted this cycle.")


def safe_run_roast_pgm_cycle():
    try:
        run_roast_pgm_cycle()
    except Exception:
        log.info("[ROAST] Error during roast cycle:")
        traceback.print_exc()
