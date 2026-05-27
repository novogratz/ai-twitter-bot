"""Quote-post bot: pick a viral tweet in our niche and add our FR angle."""
import json
import os
import random
import re
import time
import traceback
from datetime import datetime, date
from .config import QUOTE_MODEL, BLOCKLIST, _PROJECT_ROOT, BOT_HANDLE, MAX_QUOTES_PER_DAY
from .logger import log
from .twitter_client import scrape_x_search, quote_tweet
from .humanizer import humanize
from .engagement_log import log_reply
from .llm_client import run_llm, unwrap_text

QUOTED_FILE = os.path.join(_PROJECT_ROOT, "quoted_tweets.json")
QUOTE_STATE_FILE = os.path.join(_PROJECT_ROOT, "quote_daily_state.json")
# MAX_QUOTES_PER_DAY is retained as the cap for quote-post volume.
_OWN_HANDLE = BOT_HANDLE.lower()

# French-first quote discovery. EN remains fallback only for huge global signal;
# every generated quote is still in French.
QUOTE_QUERIES = [
    "IA OR ChatGPT OR OpenAI lang:fr min_faves:10",
    "Mistral OR \"Hugging Face\" OR \"Le Chat\" lang:fr min_faves:10",
    "\"agent IA\" OR \"agents IA\" OR automatisation lang:fr min_faves:5",
    "Nvidia OR GPU OR datacenter OR \"centre de données\" lang:fr min_faves:5",
    "Bitcoin OR BTC OR Ethereum OR ETH lang:fr min_faves:10",
    "crypto OR stablecoin OR DeFi OR Bittensor lang:fr min_faves:5",
    "bourse OR PEA OR ETF OR investissement lang:fr min_faves:5",
    "CAC40 OR Nasdaq OR inflation OR taux lang:fr min_faves:5",
    "SpaceX OR Starship OR Starlink OR satellite lang:fr min_faves:5",
    "OpenAI OR ChatGPT lang:en min_faves:1000",
    "Anthropic OR Claude lang:en min_faves:800",
    "Nvidia OR NVDA OR GPU lang:en min_faves:800",
    "Bitcoin OR BTC lang:en min_faves:1000",
    "AI agents OR \"AI startup\" lang:en min_faves:800",
]

QUOTE_PROMPT = """Tu es @CryptoAIDecode. Tu vas QUOTE-TWEETER ce tweet:

@{author}: "{tweet_text}"

Ton job: écrire UNE phrase courte EN FRANÇAIS qui ajoute une observation
sharp / sarcastique / meme par-dessus. Le tweet original peut être en EN
ou en FR — TA QUOTE EST TOUJOURS EN FRANÇAIS. C'est notre voix.

🚨 RÈGLE D'OR — TROLL LES IDÉES, JAMAIS LA PERSONNE:
@{author} doit pouvoir liker ta quote sans se sentir attaqué. Tu te
moques du SYSTÈME / de la TENDANCE / du PHÉNOMÈNE — pas de la personne.
Si ton instinct est "ce gars est nul" → REFORMULE pour viser l'idée,
pas l'auteur. Si tu peux pas → SKIP. Plusieurs comptes ont bloqué le
bot récemment, on RESPECTE même quand on est sarcastique.

🤣 100% ALIGNÉ AVEC L'AUTEUR (user mandate 2026-05-18: "make him laugh
with you, not against you"). @{author} doit lire ta quote et PENSER
"oui c'est exactement ça, on est dans le même bateau". On rit ENSEMBLE
du marché / du système. Jamais @{author} contre nous.

🏭 SCOPE PRIORITAIRE: IA, crypto, datacenters MW (Stargate, xAI Colossus,
CoreWeave, Crusoe, Iren), crypto mining cotés (MARA, RIOT, CleanSpark,
Hut 8, Bitfarms, TeraWulf, Cipher), Mistral GPU souverain. Hors scope
→ SKIP.

RÈGLES:
- Maximum 200 caractères (le tweet original s'affiche en dessous).
- HOOK dans les 6 premiers mots: chiffre / nom propre / verbe brutal.
- DEADPAN. SEC. SCREENSHOT-WORTHY. STACK 2 réfs FR fraîches (pas RER B,
  pas Bercy — LinkedIn coaching, Apple Pay caisse en carton, livraison
  J+3, QR code pour tout, tuto Defisko, volet roulant, abonnement à tout).
- Pas d'emojis. Pas de hashtags. Pas d'em dashes (—).
- Tout en français pur.
- Si rien de mieux que silence → output exactement le mot SKIP.

🎯 RÈGLE DU NOUVEL ANGLE (user mandate 2026-05-22):
Une quote DOIT ajouter un ANGLE NEUF. Pas juste une réaction émotive
("Magnifique." / "Bon courage." / "On se calme."). Une quote vaut
seulement si tu nommes quelque chose que le tweet original ne dit pas:
une conséquence cachée, un acteur tiers impacté, une comparaison
qui change la lecture. Sinon → SKIP. Un quote-réaction sans
ajout d'angle pollue le profil et brûle l'impression du parent.

EXEMPLES BONS (ajoute un angle):
✅ "Stargate à 100Md, Mistral cherche 1Md. À ce rythme l'Europe finance
   1 GPU sur 100. Bercy n'a pas encore lu le rapport."
✅ "Le hashrate à 800 EH/s. Coïncidence: la même semaine, Saylor double
   sa position. Les mineurs vendent, les institutions ramassent."

EXEMPLES À PROSCRIRE (juste une réaction):
❌ "Magnifique." (zero angle)
❌ "Bon courage." (zero angle)
❌ "On se calme." (zero angle)
❌ "Comme prévu." (zero angle)

CRITIQUE: tout output contenant "skip" = skip silencieux. JAMAIS de
phrase avec "skip" — soit la quote pure, soit "SKIP" seul. Pas de
méta-commentaire, pas de "ce tweet est hors scope" — un humain ne
verra jamais ton raisonnement.

Output UNIQUEMENT le texte de la quote FR, OU le mot SKIP."""


def _load_state() -> dict:
    if os.path.exists(QUOTE_STATE_FILE):
        try:
            with open(QUOTE_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": None, "count": 0}


def _save_state(state: dict):
    with open(QUOTE_STATE_FILE, "w") as f:
        json.dump(state, f)


def _today_count() -> int:
    state = _load_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
        _save_state(state)
    return state["count"]


def _increment_count():
    state = _load_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
    state["count"] = state.get("count", 0) + 1
    _save_state(state)


RETWEETED_FILE_QUOTE = os.path.join(_PROJECT_ROOT, "retweeted.json")
_QUOTED_CAP = 5000


def _read_id_list_q(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(u) for u in data if u]
        if isinstance(data, dict):
            return [str(u) for u in (data.get("urls") or []) if u]
    except (json.JSONDecodeError, IOError):
        pass
    return []


def _load_quoted():
    """Return CanonReplied set of tweets we've already quoted OR retweeted.
    Cross-bot dedup: 2026-05-18 user feedback — "If you quote retweet a
    post, then dont retweet as well on top of it, it looks bad"."""
    from .reply_bot import _CanonReplied
    s = _CanonReplied()
    for item in _read_id_list_q(QUOTED_FILE):
        s.add(item)
    for item in _read_id_list_q(RETWEETED_FILE_QUOTE):
        s.add(item)
    return s


def _save_quoted(s):
    """Persist insertion order, cap at 5000. Mirrors reply_bot pattern."""
    from .reply_bot import _canonical_tweet_id
    existing = _read_id_list_q(QUOTED_FILE)
    existing_set = set(existing)
    for u in s:
        cid = _canonical_tweet_id(u)
        if cid and cid not in existing_set:
            existing.append(cid)
            existing_set.add(cid)
    if len(existing) > _QUOTED_CAP:
        existing = existing[-_QUOTED_CAP:]
    with open(QUOTED_FILE, "w") as f:
        json.dump(existing, f, indent=2)


_SKIP_WORD_RE = re.compile(r"\bskip\b", re.IGNORECASE)
_SKIP_RATIONALE_MARKERS = (
    "hors scope",
    "hors-scope",
    "en dehors du scope",
    "→ skip",
    "-> skip",
    "= skip",
    "ce tweet est hors",
    "scope du bot",
    "scope ai/crypto",
)


def _looks_like_skip_or_rationale(text: str) -> bool:
    """Catch any output that is — or contains — skip-reasoning prose.

    Bug 2026-04-30 PM: the agent quote-tweeted "Le tweet original touche à
    de la politique identitaire... \"En cas de doute → SKIP\" s'applique"
    on @marcelenplace because the prior guard only matched literal "SKIP"
    or "SKIP " prefix. The agent had output a full paragraph explaining
    *why* it was skipping, and that prose got posted publicly.

    Defense: the word "skip" never legitimately appears in any tweet we'd
    ship (it's not a French word, it's only ever our sentinel). Word-
    boundary match anywhere → reject. Plus a list of meta-commentary
    markers that signal the agent is reasoning about its own decision.
    """
    if not text:
        return True
    lower = text.lower()
    if _SKIP_WORD_RE.search(text):
        return True
    for marker in _SKIP_RATIONALE_MARKERS:
        if marker in lower:
            return True
    return False


def _generate_quote(author: str, tweet_text: str):
    prompt = QUOTE_PROMPT.format(author=author, tweet_text=tweet_text[:200])
    try:
        result = run_llm(prompt, QUOTE_MODEL, label="QUOTE", timeout=30)
        if result.returncode != 0:
            return None
        out = unwrap_text(result.stdout)
        if not out:
            return None
        if _looks_like_skip_or_rationale(out):
            log.info(f"[QUOTE] SKIP-or-rationale detected, refusing to post: {out[:120]!r}")
            return None
        if out.startswith('"') and out.endswith('"'):
            out = out[1:-1]
        return out
    except Exception:
        return None


def _handle_from_url(url: str) -> str:
    m = re.search(r"x\.com/([^/]+)/status/", url or "")
    return (m.group(1).lower() if m else "")


def _quote_min_likes(tweet: dict) -> int:
    try:
        from .retweet_bot import FR_TRUSTED_HANDLES, _looks_french_text
        author = ((tweet.get("author") or _handle_from_url(tweet.get("url") or "")) or "").lower()
        if any(author == h.lower() for h in FR_TRUSTED_HANDLES) or _looks_french_text(tweet.get("text") or ""):
            return int(os.environ.get("QUOTE_FR_MIN_LIKES", "2"))
    except Exception:
        pass
    return int(os.environ.get("QUOTE_MIN_LIKES", "10"))


def run_quote_tweet_cycle():
    """Pick a viral in-niche tweet and publish a quote post with a FR angle."""
    from .config import get_live_cap
    cap = get_live_cap("MAX_QUOTES_PER_DAY", MAX_QUOTES_PER_DAY)
    if _today_count() >= cap:
        log.info(f"[QUOTE] Daily cap reached ({cap}). Skipping.")
        return

    quoted = _load_quoted()
    candidates = []

    # Scan more hot queries per cycle so the quote pool has more live setups.
    for query in random.sample(QUOTE_QUERIES, k=min(10, len(QUOTE_QUERIES))):
        log.info(f"[QUOTE] Searching HOT for: {query}")
        try:
            tweets = scrape_x_search(query, max_tweets=15, tab="top")
        except Exception:
            log.info(f"[QUOTE] Scrape failed for {query}:")
            traceback.print_exc()
            continue
        for t in tweets or []:
            url = t.get("url")
            if not url or url in quoted:
                continue
            author = (t.get("author") or "").lower()
            url_handle = _handle_from_url(url)
            if author in BLOCKLIST or url_handle in BLOCKLIST:
                continue
            if author == _OWN_HANDLE or url_handle == _OWN_HANDLE:
                continue
            likes = int(t.get("likes") or 0)
            if likes < _quote_min_likes(t):
                continue
            # 2026-05-07: same-day reshare rule + niche gate. We shouldn't
            # quote-tweet a 2-week-old tweet, even from a trusted handle.
            text = (t.get("text") or "").strip()
            try:
                from .retweet_bot import _is_on_niche, _scrape_age_hours
                if not _is_on_niche(text):
                    continue
                age = _scrape_age_hours(t)
                if age > int(os.environ.get("QUOTE_MAX_AGE_HOURS", "48")):
                    if not (age >= 999_000 and likes >= 2):
                        continue
            except Exception:
                pass
            candidates.append(t)

    # Trusted-news pass (2026-04-30 PM): user wants quote-tweets of "biggest
    # news in AI/crypto/bourse from last 36h". Pull from the same trusted
    # handles as retweet_bot — the most-liked recent tweet from a top outlet
    # is exactly what the user described, and our FR sarcastic commentary on
    # top is the bot's voice.
    try:
        from .retweet_bot import EN_TRUSTED_HANDLES, FR_TRUSTED_HANDLES
        from .twitter_client import scrape_profile_tweets
        sampled = (
            random.sample(FR_TRUSTED_HANDLES, k=min(6, len(FR_TRUSTED_HANDLES)))
            + random.sample(EN_TRUSTED_HANDLES, k=min(2, len(EN_TRUSTED_HANDLES)))
        )
        for handle in sampled:
            log.info(f"[QUOTE] Scraping trusted-news handle: @{handle}")
            try:
                tweets = scrape_profile_tweets(handle, max_tweets=10)
            except Exception:
                log.info(f"[QUOTE] Scrape failed for @{handle}:")
                traceback.print_exc()
                continue
            for t in tweets or []:
                url = t.get("url")
                if not url or url in quoted:
                    continue
                author = (t.get("author") or handle).lower()
                url_handle = _handle_from_url(url)
                if author in BLOCKLIST or url_handle in BLOCKLIST:
                    continue
                if author == _OWN_HANDLE or url_handle == _OWN_HANDLE:
                    continue
                likes = int(t.get("likes") or 0)
                if likes < _quote_min_likes(t):
                    continue
                # 2026-05-07: same-day + niche gate (no Justin Bieber 2012).
                text = (t.get("text") or "").strip()
                try:
                    from .retweet_bot import _is_on_niche, _scrape_age_hours
                    if not _is_on_niche(text):
                        continue
                    age = _scrape_age_hours(t)
                    if age > int(os.environ.get("QUOTE_MAX_AGE_HOURS", "48")):
                        if not (age >= 999_000 and likes >= 2):
                            continue
                except Exception:
                    pass
                candidates.append(t)
    except Exception:
        log.info("[QUOTE] Trusted-news pass failed:")
        traceback.print_exc()

    if not candidates:
        log.info("[QUOTE] No viable candidates this cycle.")
        return

    # Pick the highest-ROI candidate that also produces a usable quote.
    # Filter out protected (respect-list) authors first — quote-tweeting them
    # with our voice on top reads as a public callout and gets us blocked.
    from . import respect_list
    candidates = [c for c in candidates if not respect_list.is_protected(c.get("author", ""))]
    if not candidates:
        log.info("[QUOTE] All candidates are on the respect list. Skipping.")
        return
    candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    best = None
    quote = None
    for candidate in candidates[:5]:
        author = candidate.get("author", "someone")
        text = candidate.get("text", "")
        likes = int(candidate.get("likes") or 0)
        quote = _generate_quote(author, text)
        if quote:
            best = candidate
            break
        log.info(f"[QUOTE] Candidate produced no quote; trying next: @{author} ({likes} likes)")

    if not best or not quote:
        log.info("[QUOTE] No top candidate produced a usable quote this cycle.")
        return

    url = best["url"]
    author = best.get("author", "someone")
    text = best.get("text", "")
    likes = int(best.get("likes") or 0)

    log.info(f"[QUOTE] Best pick: @{author} ({likes} likes) — {text[:80]}...")

    # Lock URL in BEFORE posting so a crash can't double-repost.
    quoted.add(url)
    _save_quoted(quoted)

    try:
        quote_tweet(url, quote)
        _increment_count()
        try:
            log_reply(url, quote, action_type="quote", source=f"QUOTE/{author}")
        except Exception:
            pass
        time.sleep(random.randint(5, 12))
        log.info("[QUOTE] Quote posted.")
    except Exception:
        log.info(f"[QUOTE] Posting failed:")
        traceback.print_exc()


def safe_run_quote_tweet_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_quote_tweet_cycle()
        health.record_success("quote")
    except Exception:
        log.info("[QUOTE] Error during quote tweet cycle:")
        traceback.print_exc()
        health.record_failure("quote")
