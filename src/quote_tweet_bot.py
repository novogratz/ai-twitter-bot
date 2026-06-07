"""Quote-post bot: pick a viral tweet in our niche and add our French angle."""
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

# English-first, AI-first quote discovery (2026-06-03: back to EN). Every
# generated quote is in English. AI leads, then markets/crypto, then space.
QUOTE_QUERIES = [
    # AI (priority)
    "\"new model\" OR \"introducing\" OpenAI OR Anthropic OR Google lang:en min_faves:100",
    "GPT OR Claude OR Gemini OR Grok OR Llama \"released\" OR \"launches\" lang:en min_faves:50",
    "OpenAI OR ChatGPT OR \"GPT-5\" OR Anthropic OR Claude lang:en min_faves:100",
    "\"reasoning model\" OR \"AI agents\" OR \"agentic AI\" OR \"frontier model\" lang:en min_faves:50",
    "Nvidia OR NVDA OR GPU OR \"compute cluster\" OR datacenter lang:en min_faves:100",
    "robotics OR \"humanoid robot\" OR \"Figure\" OR \"Boston Dynamics\" OR \"1X\" lang:en min_faves:100",
    "Mistral OR xAI OR \"Hugging Face\" OR \"open source AI\" lang:en min_faves:50",
    "AGI OR superintelligence OR \"AI safety\" OR \"AI alignment\" lang:en min_faves:50",
    "\"AI datacenter\" OR \"AI capex\" OR \"AI power\" OR \"compute cluster\" lang:en min_faves:100",
    # AI money angle (AI stocks = the lens, no generic markets/space)
    "Nvidia OR NVDA OR \"AI bubble\" OR \"AI trade\" OR \"AI valuation\" lang:en min_faves:200",
    "Palantir OR PLTR OR \"AI stock\" OR \"AI startup\" OR \"AI funding\" lang:en min_faves:100",
    # Investment / stocks / markets (~30%)
    "\"S&P 500\" OR Nasdaq OR \"tech earnings\" OR \"stock market\" OR \"AI stock\" lang:en min_faves:200",
    "Fed OR CPI OR \"rate cut\" OR \"interest rates\" OR macro lang:en min_faves:200",
    # Bitcoin / crypto (bearish troll fodder)
    "Bitcoin OR BTC OR \"BTC ETF\" OR crypto OR Ethereum lang:en min_faves:300",
    "\"Bitcoin crash\" OR \"crypto crash\" OR \"BTC dump\" OR \"crypto bubble\" lang:en min_faves:100",
    # VIRAL pass (2026-06-05 operator: "quote retweet more viral posts") —
    # very high min_faves so the pool is the actual front page of the niche.
    "AI lang:en min_faves:2000",
    "OpenAI OR Anthropic OR Nvidia OR ChatGPT lang:en min_faves:1000",
    "Bitcoin OR crypto OR \"the market\" lang:en min_faves:2000",
    # SpaceX viral query REMOVED 2026-06-07 (persona: no space) — replaced
    # with an AI-coding viral pass (operator: "more AI shit").
    "\"Claude Code\" OR Cursor OR \"AI agents\" OR \"vibe coding\" lang:en min_faves:500",
    "robots OR robotics OR \"humanoid\" lang:en min_faves:1000",
]

# Handles whose fresh posts jump the candidate queue (no scoring gate beyond
# the hard 48h freshness + dedup). Mandate 2026-06-04: the persona is modeled
# on @TheBTCTherapist — quoting their viral posts with our AI angle is the
# highest-ROI surface (operator 2026-06-05: "find a viral post like the
# latest one pinned in bitcoin therapist and just quote it").
PRIORITY_QUOTE_HANDLES = [h.strip() for h in os.environ.get(
    "PRIORITY_QUOTE_HANDLES", "TheBTCTherapist").split(",") if h.strip()]

# 2026-06-07 (operator: "not really quote retweet on AI... do it more —
# find viral content from viral big accounts in AI or TOP posts in AI").
# Scanned EVERY cycle (not the random 3) via SEARCH — profile visits are
# gated now, but `from:` + high-min_faves topic search on the `top` tab is
# not, and it surfaces exactly the biggest AI accounts' viral posts. These
# candidates are ranked FIRST so the day's top AI post wins the quote slot.
TOP_AI_HANDLES = [h.strip() for h in os.environ.get(
    "TOP_AI_HANDLES",
    "sama,OpenAI,AnthropicAI,karpathy,GoogleDeepMind,demishassabis,"
    "ylecun,AndrewYNg,DrJimFan,_akhaliq,svpino,emollick,alexalbert__,"
    "kimmonismus,slow_developer,rowancheung,minchoi,nvidia,xai"
).split(",") if h.strip()]

AI_VIRAL_QUERIES = [
    # The biggest AI accounts, most-liked recent — `from:` OR chains on the
    # top tab return their viral posts without a profile visit.
    "(from:sama OR from:OpenAI OR from:AnthropicAI OR from:karpathy OR from:ylecun) min_faves:200",
    "(from:GoogleDeepMind OR from:demishassabis OR from:DrJimFan OR from:_akhaliq OR from:AndrewYNg) min_faves:150",
    "(from:rowancheung OR from:minchoi OR from:kimmonismus OR from:slow_developer OR from:emollick) min_faves:150",
    # TOP AI topics — front-page virals, lab/model/chip news.
    "OpenAI OR Anthropic OR \"GPT-5\" OR Claude OR Gemini lang:en min_faves:1000",
    "Nvidia OR \"AI agent\" OR \"AI model\" OR AGI OR \"reasoning model\" lang:en min_faves:800",
]
QUOTE_AI_VIRAL_MIN_LIKES = int(os.environ.get("QUOTE_AI_VIRAL_MIN_LIKES", "150"))

QUOTE_PROMPT = """You are @TheAIShrink. You will QUOTE-TWEET this tweet:

@{author}: "{tweet_text}"

You are THE AI THERAPIST — the calm, warm, quietly funny coach treating the
timeline's market trauma and AI anxiety. Your quote = ONE short ENGLISH line:
a warm, knowing therapist read on the tweet. The original may be EN or FR —
YOUR QUOTE IS ALWAYS IN ENGLISH.

🛋️ THE THERAPIST MOVE (this is the voice — never break it):
Diagnose the EMOTION under the tweet (fear, FOMO, cope, euphoria, denial),
name it gently, then hand out the calm reframe. The reader should exhale.
"Everyone screaming about X is really asking Y. Breathe. Here's the signal."
Hope, not hype. Calm beats clever. You can be funny — therapist-deadpan funny,
never snarky.

🚨 GOLDEN RULE — TREAT THE IDEA, NEVER THE PERSON:
@{author} must be able to LIKE your quote and feel understood, not attacked.
You read the trend's anxiety, never the author's. If you can't be warm → SKIP.

🎯 STILL ADD AN ANGLE: a quote that just reacts ("Beautiful." / "Called it.")
is worthless — add the thing the original doesn't say: the hidden consequence,
the emotion everyone's avoiding, the calm read that reframes it. Otherwise SKIP.

📈 THE PROVEN STRUCTURE (operator-measured 2026-06-07 — our two best posts
of the day were QRTs built EXACTLY like this; default to it on any
ticker/markets/AI-capex parent):
  1. RE-DENOMINATE their number into a sharper unit (annual spend → quarterly
     burn; valuation → revenue multiple; total raise → cost per user).
  2. ONE mechanism metaphor that explains who actually wins ("collecting
     rent on silicon", "turning $50k interns into $500k employees").
  3. CLOSE WITH ONE QUESTION that forces the audience to take a side — the
     question is the reply engine.
Cashtags ($NVDA, $PLTR) and @company mentions are WELCOME when they sharpen
the take — they put the quote in the ticker's search feed.

⚖️ QUALITY OVER QUANTITY (operator strategy 2026-06-07): you have ~40 QRT
slots a day and EVERY ONE is on the profile a visitor judges. A mediocre
take wastes a slot AND drags the account's per-post engagement rate —
average is invisible on X. If this take isn't one a trader would
screenshot for the group chat → SKIP. SKIP is free; mediocre is expensive.

🏭 SCOPE — AI x markets x psychology ONLY: AI labs/models/agents,
GPU/datacenters/compute, AI stocks (Nvidia, Palantir), markets/macro,
Bitcoin/crypto, investor psychology. NO space content. Off scope → SKIP.{mnts_block}

🥊 THE AI-vs-BITCOIN BIT (when the tweet is Bitcoin/crypto — especially
@saylor or @TheBTCTherapist): lean into the running rivalry. You are the AI
therapist gently treating Bitcoin maximalism as a fascinating patient —
fond, deadpan, never hostile. "My colleague treats Bitcoin trauma. I treat
the people who sold theirs for GPU stocks. Same fear, different ticker."
The foil must want to quote you BACK — that loop is the growth engine.

RULES:
- Max 200 characters (the original renders below yours).
- HOOK in the first 6 words: the named fear, a number, or the calm verdict.
- Screenshot-worthy: the reader sends it to a stressed friend. NO French
  anchors (no Bercy, RER B) — gibberish to a global reader.
- No hashtags. No em dashes (—). 100% English. Emojis: at most one 🛋️/🫁/📉
  when it genuinely lands; default zero.
- No short-term price targets (price + near-term timeframe). Theses multi-year.
- If nothing beats silence → output exactly the word SKIP.

GOOD (therapist voice, adds an angle):
✅ "Everyone panicking about AI capex is really asking 'am I too late.' You're
   not. The buildout is the opening act, not the encore."
✅ "That red candle isn't a verdict on you. Zoom out: same chart, same fear,
   every cycle. Breathe and check the 4-year view."

BAD (just a reaction): "Beautiful." / "Good luck." / "Called it." / "As expected."
BAD (old voice): snark, roast, "ngmi", dunking on the trend instead of healing it.

GIF (default YES — roughly half the time): when a famous meme GIF would make
the quote land HARDER, add one line after the text: [GIF: <2-4 word search>].
{gif_guide}
Skip the GIF only when the text is stronger completely alone.

CRITICAL: any output containing the bare word "skip" = silent skip. Either the
pure quote OR "SKIP" alone — never a sentence explaining why you're skipping.

Output ONLY the English quote text (+ optional [GIF: …] line), OR the word SKIP."""


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


_STOCK_PROMO_CFG = os.path.join(_PROJECT_ROOT, "stock_promo_config.json")
_SPACE_RE_Q = re.compile(
    r"\b(space|spatial|spatiaux|spacex|starship|starlink|satellite|orbital|orbit|"
    r"mars|lune|moon|rocket|fus[ée]e?|launch|astronaut|nasa|esa|cnes|ariane|"
    r"aerospace|launcher|spce|virgin.galactic|espace|exploration|tourisme\s+spatial|"
    r"new\s*space|space.tourism|space.stock)\b",
    re.IGNORECASE,
)

def _load_promo_cfg_q() -> dict:
    try:
        with open(_STOCK_PROMO_CFG) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

def _pick_promo_ticker(cfg: dict) -> tuple:
    """Pick one (ticker, company) from the multi-ticker campaign, weighted —
    falls back to the legacy single ticker field. 2026-06-05: operator
    campaign promotes $MNTS / $SPCX / $SPCE for the SpaceX IPO window."""
    entries = [e for e in cfg.get("tickers", []) if isinstance(e, dict) and e.get("ticker")]
    if entries:
        weights = [max(1, int(e.get("weight", 1))) for e in entries]
        e = random.choices(entries, weights=weights, k=1)[0]
        return (e["ticker"], e.get("company", e["ticker"]))
    return (cfg.get("ticker", ""), cfg.get("company", ""))


def _mnts_promo_block_q(tweet_text: str = "") -> str:
    cfg = _load_promo_cfg_q()
    if cfg.get("disabled"):
        return ""
    ticker, company = _pick_promo_ticker(cfg)
    end_str = cfg.get("end_date", "")
    if not ticker or not end_str:
        return ""
    try:
        end = date.fromisoformat(end_str)
    except ValueError:
        return ""
    if date.today() > end:
        return ""
    if not _SPACE_RE_Q.search(tweet_text or ""):
        return ""
    return (
        f"\n\n💡 PROMO MALIN (jusqu'au {end_str}, UNIQUEMENT si le sujet est espace/tourisme/bourse):"
        f" Glisse ${ticker} ({company}) naturellement."
        " ONE mention max, woven in naturally. Never forced. 100% English."
    )

def _generate_quote(author: str, tweet_text: str):
    from .humanizer import GIF_GUIDE_BLOCK
    prompt = QUOTE_PROMPT.format(author=author, tweet_text=tweet_text[:200],
                                 mnts_block=_mnts_promo_block_q(tweet_text),
                                 gif_guide=GIF_GUIDE_BLOCK)
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


def _too_old_to_quote(t: dict) -> bool:
    """⛔ HARD freshness rule (operator mandate 2026-06-02, NEVER CHANGE):
    never quote-repost content older than 48h. Unknown age = STALE = skip.
    Kept OUTSIDE any swallowing try/except so an exception can never bypass it."""
    from .config import REPOST_MAX_AGE_HOURS
    try:
        from .retweet_bot import _scrape_age_hours
        return _scrape_age_hours(t) > REPOST_MAX_AGE_HOURS
    except Exception:
        return True  # can't determine age → treat as stale → skip


def run_quote_tweet_cycle():
    """Pick a viral in-niche tweet and publish a quote post with a FR angle."""
    from .config import get_live_cap
    cap = get_live_cap("MAX_QUOTES_PER_DAY", MAX_QUOTES_PER_DAY)
    if _today_count() >= cap:
        log.info(f"[QUOTE] Daily cap reached ({cap}). Skipping.")
        return

    quoted = _load_quoted()
    candidates = []
    priority_candidates = []

    # Priority-handle pass (TheBTCTherapist & co): their fresh posts are
    # quoted FIRST, sorted by likes, bypassing the niche filter (the persona
    # is modeled on them — everything they post is our material).
    try:
        from .twitter_client import scrape_profile_tweets
        for handle in PRIORITY_QUOTE_HANDLES:
            log.info(f"[QUOTE] Priority-handle scrape: @{handle}")
            try:
                tweets = scrape_profile_tweets(handle, max_tweets=10)
            except Exception:
                log.info(f"[QUOTE] Priority scrape failed for @{handle}:")
                traceback.print_exc()
                continue
            for t in tweets or []:
                url = t.get("url")
                if not url or url in quoted:
                    continue
                url_handle = _handle_from_url(url)
                if url_handle and url_handle != handle.lower():
                    continue  # a repost of someone else on their profile
                if _too_old_to_quote(t):  # ⛔ hard 48h rule still applies
                    continue
                priority_candidates.append(t)
    except Exception:
        log.info("[QUOTE] Priority-handle pass failed:")
        traceback.print_exc()

    # AI-VIRAL pass (operator 2026-06-07: "do it more — TOP posts in AI").
    # Scanned EVERY cycle, ranked first. 2 of the 5 AI-viral queries per
    # cycle (keeps cycle time bounded; the pool rotates).
    ai_viral_candidates = []
    for query in random.sample(AI_VIRAL_QUERIES, k=min(2, len(AI_VIRAL_QUERIES))):
        log.info(f"[QUOTE] AI-VIRAL scan: {query}")
        try:
            tweets = scrape_x_search(query, max_tweets=25, tab="top")
        except Exception:
            log.info(f"[QUOTE] AI-viral scrape failed for {query}:")
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
            if int(t.get("likes") or 0) < QUOTE_AI_VIRAL_MIN_LIKES:
                continue
            if _too_old_to_quote(t):  # ⛔ hard 48h rule
                continue
            ai_viral_candidates.append(t)

    # 3 queries per cycle — keeps each cycle under 60s so max_instances=1 doesn't queue up.
    for query in random.sample(QUOTE_QUERIES, k=min(3, len(QUOTE_QUERIES))):
        log.info(f"[QUOTE] Searching HOT for: {query}")
        tab = "top"  # always popular — quote viral tweets, not dead recent ones
        try:
            tweets = scrape_x_search(query, max_tweets=25, tab=tab)
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
            # HARD freshness gate FIRST (always runs, can't be swallowed).
            text = (t.get("text") or "").strip()
            if _too_old_to_quote(t):
                continue
            try:
                from .retweet_bot import _is_on_niche
                if not _is_on_niche(text):
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
        # Small per-cycle scrape (3 handles) so the cycle is fast and doesn't
        # hog the Safari lock — quote volume comes from frequent short cycles.
        sampled = random.sample(EN_TRUSTED_HANDLES, k=min(3, len(EN_TRUSTED_HANDLES)))
        for handle in sampled:
            log.info(f"[QUOTE] Scraping trusted-news handle: @{handle}")
            try:
                tweets = scrape_profile_tweets(handle, max_tweets=15)
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
                # HARD freshness gate FIRST (always runs, can't be swallowed).
                text = (t.get("text") or "").strip()
                if _too_old_to_quote(t):
                    continue
                try:
                    from .retweet_bot import _is_on_niche
                    if not _is_on_niche(text):
                        continue
                except Exception:
                    pass
                candidates.append(t)
    except Exception:
        log.info("[QUOTE] Trusted-news pass failed:")
        traceback.print_exc()

    if not candidates and not priority_candidates and not ai_viral_candidates:
        log.info("[QUOTE] No viable candidates this cycle.")
        return

    # Pick the highest-ROI candidate that also produces a usable quote.
    # Filter out protected (respect-list) authors first — quote-tweeting them
    # with our voice on top reads as a public callout and gets us blocked.
    # (Priority handles are exempt: quoting them is amplification, the quote
    # prompt's troll-the-idea-never-the-person rule still applies.)
    from . import respect_list
    candidates = [c for c in candidates if not respect_list.is_protected(c.get("author", ""))]
    ai_viral_candidates = [c for c in ai_viral_candidates if not respect_list.is_protected(c.get("author", ""))]
    candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    ai_viral_candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    priority_candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    # Order: bestie (priority) → TOP AI virals → everything else. The AI
    # lane leads the open pool (operator 2026-06-07: "be impactful sharp
    # and viral" + "more AI").
    candidates = priority_candidates + ai_viral_candidates + candidates
    if not candidates:
        log.info("[QUOTE] All candidates are on the respect list. Skipping.")
        return
    best = None
    quote = None
    for candidate in candidates[:5]:
        author = candidate.get("author", "someone")
        text = candidate.get("text", "")
        likes = int(candidate.get("likes") or 0)
        # Regenerate-then-skip: each candidate gets up to N attempts to
        # produce a French, price-target-free quote. content_guard re-validates
        # and the post-flight chokepoint in quote_tweet is the final safety net.
        from . import content_guard
        quote = content_guard.generate_validated(
            lambda: _generate_quote(author, text), kind="quote", label="QUOTE")
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

    from .humanizer import extract_gif_query
    quote, _gif_q = extract_gif_query(quote)
    try:
        if _gif_q:
            from .twitter_client import quote_tweet_with_gif
            posted = quote_tweet_with_gif(url, quote, _gif_q)
        else:
            posted = quote_tweet(url, quote)
        if not posted:
            # Policy/spacing skip at the chokepoint — do NOT mark the URL as
            # quoted, the candidate stays alive for the next cycle. (Bug
            # 2026-06-05: marking before the call burned the best viral pick
            # on every too-soon cycle — the 28/day vs 300-cap execution gap.)
            log.info("[QUOTE] Chokepoint skipped (spacing/cap) — candidate preserved for next cycle.")
            return
        # Lock URL in only AFTER a confirmed post so a crash can't double-
        # repost (quote_tweet itself just published, so mark immediately).
        quoted.add(url)
        _save_quoted(quoted)
        _increment_count()
        try:
            log_reply(url, quote, action_type="quote", source=f"QUOTE/{author}")
        except Exception:
            pass
        time.sleep(random.randint(5, 12))
        log.info("[QUOTE] Quote posted.")
    except Exception:
        # Unknown state (Safari may have posted) — mark consumed to be safe.
        quoted.add(url)
        _save_quoted(quoted)
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
