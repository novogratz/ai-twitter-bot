"""Quote-tweet bot: pick a viral FR tweet in our niche, post a sharp quote.

Why a separate path from replies: a quote tweet creates an entirely new post
in our followers' feed AND lands as a notification on the original author's
side. Different distribution surface than a reply — pure additive growth lever.

Cap is intentionally tiny (1-2/day): quote tweets are a *signal* feature, not
a volume feature. Spamming them looks desperate.
"""
import json
import os
import random
import re
import subprocess
import time
import traceback
from datetime import datetime, date
from .config import QUOTE_MODEL, BLOCKLIST, _PROJECT_ROOT, BOT_HANDLE, MAX_QUOTES_PER_DAY
from .logger import log
from .twitter_client import scrape_x_search, quote_tweet
from .humanizer import humanize
from .engagement_log import log_reply

QUOTED_FILE = os.path.join(_PROJECT_ROOT, "quoted_tweets.json")
QUOTE_STATE_FILE = os.path.join(_PROJECT_ROOT, "quote_daily_state.json")
# MAX_QUOTES_PER_DAY now lives in config (12/day on user directive 2026-04-26 PM).
# Quote tweets are a *different* distribution surface (lands in our followers'
# feed AND notifies the original author), so scaling them up is pure additive
# growth — not redundant with replies.
_OWN_HANDLE = BOT_HANDLE.lower()

# Pull HOT tweets (X "Top" tab) with high engagement floor — quote
# bait should be at least somewhat viral or there's no audience to capture.
# 2026-04-30 PM (user directive): "biggest tweets from france or english".
# So queries now span FR and EN — the prompt forces FR commentary either way.
QUOTE_QUERIES = [
    # FR pool — primary
    "Claude OR ClaudeCode lang:fr min_faves:50",
    "ChatGPT OR OpenAI lang:fr min_faves:50",
    "Bitcoin lang:fr min_faves:50",
    "bourse OR CAC40 lang:fr min_faves:30",
    "crypto lang:fr min_faves:50",
    "IA lang:fr min_faves:50",
    "trading lang:fr min_faves:30",
    # EN pool — only the biggest viral hits qualify (high min_faves floor)
    "OpenAI OR Anthropic OR Claude lang:en min_faves:1000",
    "Bitcoin OR Ethereum lang:en min_faves:1000",
    "AGI OR \"AI safety\" lang:en min_faves:500",
    "stock market OR S&P500 lang:en min_faves:500",
    "Nvidia OR NVDA lang:en min_faves:500",
]

QUOTE_PROMPT = """Tu es @kzer_ai. Tu vas QUOTE-TWEETER ce tweet:

@{author}: "{tweet_text}"

Ton job: écrire UNE phrase courte EN FRANÇAIS qui ajoute une couche meme/sarcastique/sharp au-dessus. Même si le tweet original est en anglais, TA QUOTE est en FRANÇAIS — c'est notre voix. Comme un commentaire BFM IA/crypto/bourse en mode coup-de-pied.

RÈGLES:
- Maximum 200 caractères (X coupe à 280 mais le tweet original est intégré, donc on a la place).
- DEADPAN. SEC. SCREENSHOT-WORTHY. Sarcastique mais intelligent.
- Troll les IDÉES, jamais la personne. @{author} doit pouvoir liker ta quote.
- Pas d'emojis. Pas de hashtags. Pas d'em dashes (—).
- Si tu peux pas faire mieux que silence, output EXACTEMENT le mot SKIP, rien d'autre. Aucune explication, aucune phrase. Juste "SKIP".

CRITIQUE: Tout output qui contient le mot SKIP est traité comme un skip silencieux. N'écris JAMAIS une phrase qui contient le mot "skip" — soit tu écris la quote pure, soit tu écris uniquement "SKIP". Pas de méta-commentaire, pas d'explication de ta décision, pas de "ce tweet est hors scope" — un humain ne verra jamais ton raisonnement, donc l'expliquer c'est shipper le raisonnement.

Output UNIQUEMENT le texte de la quote en FR, OU le mot SKIP seul."""


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


def _load_quoted() -> set:
    if os.path.exists(QUOTED_FILE):
        try:
            with open(QUOTED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_quoted(s: set):
    with open(QUOTED_FILE, "w") as f:
        json.dump(list(s)[-500:], f, indent=2)


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
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", QUOTE_MODEL, "--output-format", "json", "--no-session-persistence"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        try:
            envelope = json.loads(raw)
            out = envelope.get("result", raw).strip()
        except (json.JSONDecodeError, AttributeError):
            out = raw
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


def run_quote_tweet_cycle():
    """Pick the most viral FR tweet from our queries and quote-tweet it."""
    if _today_count() >= MAX_QUOTES_PER_DAY:
        log.info(f"[QUOTE] Daily cap reached ({MAX_QUOTES_PER_DAY}). Skipping.")
        return

    quoted = _load_quoted()
    candidates = []

    # Pick 2 random queries this cycle, scrape top tab, pick the most-liked.
    for query in random.sample(QUOTE_QUERIES, k=min(2, len(QUOTE_QUERIES))):
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
            if likes < 30:
                continue  # not viral enough to be worth amplifying
            candidates.append(t)

    # Trusted-news pass (2026-04-30 PM): user wants quote-tweets of "biggest
    # news in AI/crypto/bourse from last 36h". Pull from the same trusted
    # handles as retweet_bot — the most-liked recent tweet from a top outlet
    # is exactly what the user described, and our FR sarcastic commentary on
    # top is the bot's voice.
    try:
        from .retweet_bot import TRUSTED_NEWS_HANDLES
        from .twitter_client import scrape_profile_tweets
        sampled = random.sample(TRUSTED_NEWS_HANDLES, k=min(3, len(TRUSTED_NEWS_HANDLES)))
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
                if likes < 20:
                    continue  # trusted outlets break news fast — lower floor
                candidates.append(t)
    except Exception:
        log.info("[QUOTE] Trusted-news pass failed:")
        traceback.print_exc()

    if not candidates:
        log.info("[QUOTE] No viable candidates this cycle.")
        return

    # Pick the single most-liked candidate (max ROI on the one quote we post).
    candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    best = candidates[0]
    url = best["url"]
    author = best.get("author", "someone")
    text = best.get("text", "")
    likes = int(best.get("likes") or 0)

    log.info(f"[QUOTE] Best pick: @{author} ({likes} likes) — {text[:80]}...")
    quote = _generate_quote(author, text)
    if not quote:
        log.info("[QUOTE] Generation returned SKIP — not posting.")
        return

    quote = humanize(quote)

    # Last-line defense: even if SKIP-or-rationale slipped past _generate_quote
    # AND the humanizer preserved it, refuse to post anything that looks like
    # the agent reasoning aloud. Min-length floor catches any short sentinel.
    if _looks_like_skip_or_rationale(quote) or len(quote.strip()) < 15:
        log.info(f"[QUOTE] Final guard: refusing to post {quote!r} (skip-rationale/too short).")
        return

    log.info(f"[QUOTE] Posting ({len(quote)} chars): {quote}")

    # Lock URL in BEFORE posting so a crash can't double-quote
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
        log.info("[QUOTE] Quote tweet posted.")
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
