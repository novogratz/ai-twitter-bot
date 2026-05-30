"""Quote-post bot: pick a viral tweet in our niche and add our English angle."""
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

# English-first quote discovery (user pivot 2026-05-27: full English).
# Global high-signal AI / crypto / markets / space content; every generated
# quote is in English. A short FR tail remains only for major French stories.
QUOTE_QUERIES = [
    # AI
    "OpenAI OR ChatGPT OR \"GPT-5\" lang:en min_faves:500",
    "Anthropic OR Claude OR xAI lang:en min_faves:400",
    "Nvidia OR NVDA OR GPU OR \"compute cluster\" lang:en min_faves:500",
    "\"AI agents\" OR \"agentic AI\" OR \"frontier model\" lang:en min_faves:400",
    "\"AI datacenter\" OR megawatt OR \"power demand\" OR nuclear lang:en min_faves:300",
    "robotics OR \"humanoid robot\" OR Tesla OR Boston Dynamics lang:en min_faves:400",
    "Mistral OR \"Hugging Face\" OR \"open source AI\" lang:en min_faves:200",
    # Space
    "SpaceX OR Starship OR Starlink OR \"Falcon 9\" lang:en min_faves:800",
    "\"Rocket Lab\" OR RKLB OR NASA OR Artemis lang:en min_faves:400",
    "satellite OR \"space launch\" OR \"orbital\" OR ESA lang:en min_faves:300",
    "\"AST SpaceMobile\" OR ASTS OR LUNR OR \"space stock\" lang:en min_faves:200",
    "\"Golden Dome\" OR USSF OR \"space defense\" lang:en min_faves:200",
    # Investment (crypto included)
    "Bitcoin OR BTC OR \"BTC ETF\" lang:en min_faves:600",
    "Ethereum OR stablecoin OR DeFi lang:en min_faves:300",
    "Palantir OR PLTR OR \"AI stock\" OR \"tech earnings\" lang:en min_faves:300",
    # FR fallback
    "IA OR ChatGPT OR espace OR fusée lang:fr min_faves:30",
    "Bitcoin OR crypto OR investissement lang:fr min_faves:30",
]

QUOTE_PROMPT = """You are @CryptoAIDecode. You will QUOTE-TWEET this tweet:

@{author}: "{tweet_text}"

Your job: write ONE short sentence IN ENGLISH that adds a sharp /
sarcastic / meme observation on top. The original tweet may be EN or FR
— YOUR QUOTE IS ALWAYS IN ENGLISH. That's our voice.

🚨 GOLDEN RULE — TROLL THE IDEA, NEVER THE PERSON:
@{author} must be able to like your quote without feeling attacked. You
mock the SYSTEM / the TREND / the PHENOMENON — not the person. If your
instinct is "this guy is clueless" → REFRAME to hit the idea, not the
author. If you can't → SKIP. Several accounts blocked the bot recently;
we RESPECT even when we're sarcastic.

🤣 100% ALIGNED WITH THE AUTHOR ("make them laugh with you, not against
you"). @{author} should read your quote and THINK "yes, exactly, we're
in the same boat". We laugh TOGETHER at the market / the system. Never
@{author} against us.

🏭 PRIORITY SCOPE: AI, crypto, datacenters/MW (Stargate, xAI Colossus,
CoreWeave, Crusoe, IREN), listed crypto miners (MARA, RIOT, CleanSpark,
Hut 8, Bitfarms, TeraWulf, Cipher), sovereign GPU. Off scope
→ SKIP.{mnts_block}

RULES:
- Max 200 characters (the original tweet renders below yours).
- HOOK in the first 6 words: a number / proper noun / brutal verb.
- DEADPAN. DRY. SCREENSHOT-WORTHY. Lean on global frames: a Form 10-K
  footnote, an a16z term sheet, the Fed dot plot, a CNBC chyron, a
  401(k), an S-1 risk factor, a LinkedIn 'thrilled to announce' post,
  a Notion doc with 47 nested toggles. NO French anchors (no Bercy,
  RER B, syndicat) — they read as gibberish to a global audience.
- No emojis. No hashtags. No em dashes (—).
- 100% English.
- If nothing beats silence → output exactly the word SKIP.

🎯 NEW-ANGLE RULE:
A quote MUST add a NEW angle. Not just an emotional reaction
("Beautiful." / "Good luck." / "Calm down."). A quote is only worth it
if you name something the original tweet doesn't: a hidden consequence,
an impacted third party, a comparison that reframes it. Otherwise →
SKIP. A reaction-only quote pollutes the profile and burns the parent's
impressions.

GOOD EXAMPLES (adds an angle):
✅ "Stargate at $100B, Mistral raising $1B. At this rate Europe funds 1
   GPU in 100. The term sheet hasn't reached Brussels yet."
✅ "Hashrate at 800 EH/s. Same week, Saylor doubles his position.
   Miners sell, institutions scoop. Someone's wrong."

BAD EXAMPLES (just a reaction):
❌ "Beautiful." (zero angle)
❌ "Good luck." (zero angle)
❌ "Called it." (zero angle)
❌ "As expected." (zero angle)

CRITICAL: any output containing the bare sentinel "skip" = silent skip.
Either the pure quote OR "SKIP" alone — never a sentence explaining why
you're skipping. No meta-commentary, no "this tweet is off scope" — a
human will never see your reasoning.

Output ONLY the English quote text, OR the word SKIP."""


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
    # English (primary since the 2026-05-27 pivot)
    "off scope",
    "off-scope",
    "out of scope",
    "out-of-scope",
    "not in scope",
    "off topic",
    "off-topic",
    "→ skip",
    "-> skip",
    "= skip",
    "this tweet is off",
    "i'll skip",
    "i will skip",
    "skipping this",
    # French (legacy — FR parents still occur on reply paths)
    "hors scope",
    "hors-scope",
    "en dehors du scope",
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

    Defense: word-boundary "skip" match anywhere → reject, plus a list of
    meta-commentary markers signalling the agent is reasoning about its own
    decision. Post-2026-05-27 English pivot, "skip" CAN legitimately appear
    in an English quote — we accept occasionally dropping such a quote as the
    safe tradeoff (a skipped quote is harmless; a posted skip-rationale is
    not). The cap is far below supply, so the loss is negligible.
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


_MNTS_PROMO_END_Q = date(2026, 5, 27)  # expired — promo ended
_SPACE_RE_Q = re.compile(
    r"\b(space|spatial|spatiaux|spacex|starship|starlink|satellite|orbital|orbit|"
    r"mars|lune|moon|rocket|fus[ée]e?|launch|astronaut|nasa|esa|cnes|ariane|"
    r"aerospace|launcher|mnts|momentus|espace|exploration|tourisme\s+spatial|new\s*space)\b",
    re.IGNORECASE,
)

def _mnts_promo_block_q(tweet_text: str = "") -> str:
    if date.today() > _MNTS_PROMO_END_Q:
        return ""
    if not _SPACE_RE_Q.search(tweet_text or ""):
        return ""
    return (
        "\n\n💡 SMART PROMO (until June 6, ONLY if the topic is space):"
        " Slip in $MNTS (Momentus Inc.) naturally — 'the only real orbital"
        " play', 'I'm long $MNTS', 'the best trade in space'."
        " Woven in subtly, never forced. 100% English."
    )

def _generate_quote(author: str, tweet_text: str):
    prompt = QUOTE_PROMPT.format(author=author, tweet_text=tweet_text[:200], mnts_block=_mnts_promo_block_q(tweet_text))
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
    for query in random.sample(QUOTE_QUERIES, k=min(5, len(QUOTE_QUERIES))):
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
                if t.get("timestamp") or t.get("ts") or t.get("datetime"):
                    age = _scrape_age_hours(t)
                    if age > int(os.environ.get("QUOTE_MAX_AGE_HOURS", "48")):
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
        # English-first since the 2026-05-27 pivot: sample mostly EN outlets,
        # keep a small FR tail for major French stories.
        sampled = random.sample(EN_TRUSTED_HANDLES, k=min(5, len(EN_TRUSTED_HANDLES)))
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
                    if t.get("timestamp") or t.get("ts") or t.get("datetime"):
                        age = _scrape_age_hours(t)
                        if age > int(os.environ.get("QUOTE_MAX_AGE_HOURS", "48")):
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
