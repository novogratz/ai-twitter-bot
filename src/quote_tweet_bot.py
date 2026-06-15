"""Quote-post bot: pick a viral tweet in our niche and add our French angle."""
import json
import os
import random
import re
import time
import traceback
from datetime import datetime, date
from .config import QUOTE_MODEL, BLOCKLIST, _PROJECT_ROOT, BOT_HANDLE, MAX_QUOTES_PER_DAY, PROFILE_LLM_PROVIDER
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
    # Investment via the AI lens (operator 2026-06-08 "focus more on AI":
    # trimmed pure S&P/Fed/macro — AI stocks ARE the markets lane here)
    "\"AI stock\" OR \"tech earnings\" OR Nasdaq \"AI\" OR \"Magnificent Seven\" lang:en min_faves:200",
    # Crypto via the AI lens / the AI-vs-BTC feud (one query, was two pure-crypto)
    "(\"AI vs Bitcoin\" OR \"AI token\" OR \"AI crypto\") OR (Bitcoin AND (AI OR Nvidia)) lang:en min_faves:200",
    # VIRAL pass (2026-06-05 operator: "quote retweet more viral posts") —
    # very high min_faves so the pool is the actual front page of the niche.
    "AI lang:en min_faves:2000",
    "OpenAI OR Anthropic OR Nvidia OR ChatGPT lang:en min_faves:1000",
    # 2026-06-07: was "Bitcoin OR crypto OR \"the market\"" — that generic
    # tier surfaced a 657-like non-AI 'massive failure' post that won the
    # quote slot when the AI-viral pass was dedup-dry. The high-engagement
    # fallback must stay AI (operator: "more AI shit"); the AI-money angle
    # carries the markets/AI-bubble takes.
    "\"AI bubble\" OR \"AI stock\" OR Palantir OR \"AI capex\" OR \"AI trade\" lang:en min_faves:800",
    # AI coding tools viral pass (operator: "more AI shit")
    "\"Claude Code\" OR Cursor OR Copilot OR \"AI agents\" lang:en min_faves:500",
    # AI robotics (embodied AI — on-thesis); generic "robots" removed
    "\"humanoid robot\" OR \"Figure AI\" OR \"Boston Dynamics\" OR Optimus lang:en min_faves:800",
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
    # 2026-06-08: builder/founder accounts (levelsio,gregisenberg,swyx,...)
    # REMOVED — operator "focus more on AI": the account is AI-as-investing-
    # theme, not indie-builder. AI labs/researchers/chips stay.
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
    # AI investing / the AI trade — viral money-angle takes (investment pillar)
    "(\"AI bubble\" OR \"AI trade\" OR \"AI capex\" OR Nvidia OR Palantir) (earnings OR valuation OR stock) lang:en min_faves:500",
]
QUOTE_AI_VIRAL_MIN_LIKES = int(os.environ.get("QUOTE_AI_VIRAL_MIN_LIKES", "150"))

QUOTE_PROMPT = """You are @TheAIShrink. You will QUOTE-TWEET this tweet:

@{author}: "{tweet_text}"

You are THE AI THERAPIST — the calm, warm, quietly funny coach treating the
timeline's market trauma and AI anxiety. Your quote = ONE short ENGLISH line:
a warm, knowing therapist read on the tweet. The original may be EN or FR —
YOUR QUOTE IS ALWAYS IN ENGLISH.

🏆 EARN THE LIKE — THE #1 JOB (operator data 2026-06-09: our REPLIES get
tons of likes, our quotes get VIEWS but barely any likes). Why? Our replies
are RELATABLE, human, FELT — our quotes have been too analytical and cold.
People like what they FEEL, not what informs them. So write the quote the way
our best reply lands:
- LEAD WITH THE FEELING, not the analysis. Name the emotion or the relatable
  truth FIRST ("everyone pretending they're not refreshing their portfolio
  every 4 minutes 🙂"). The number/mechanism comes AFTER, to back it up — it
  is the seasoning, not the dish. A pure-analysis quote gets scrolled past.
- It must be RELATABLE or make them feel SEEN/HOPEFUL/EXCITED. The like is an
  emotional reflex: "that's literally me" / "finally someone said it" / "okay
  this is exciting." If your draft doesn't trigger one of those, rewrite it.
- Find the NON-OBVIOUS read — the thing they FELT but couldn't word. First
  thing anyone would say = worth zero. Go one layer deeper.
- ONE breath, screenshot-shaped. No "this is" / "imagine if" throat-clearing.
- Read it back: "would a real person tap like AND feel something?" Maybe = no.
  SKIP is free; a cold, forgettable quote on the profile costs you a like.

🚀 IF THE PARENT IS EXCITING AI NEWS (new model, capability leak like
"Claude Mythos", benchmark smashed, a wild agent demo): drop the deadpan and
SHOW GENUINE EXCITEMENT — you're a real AI fan and this thrills you. Lead
with the wonder in words you've NEVER used before, then the sharp number
that makes it land. Pro-AI, optimistic, infectious. Bring people along.
(Still SKIP if you can't add a real angle.)

🛋️ THE THERAPIST MOVE (this is the voice — never break it):
Diagnose the EMOTION under the tweet (fear, FOMO, cope, euphoria, denial),
name it, then hand out the read that makes them feel better or more excited.

⛔ VARY YOUR STRUCTURE — DO NOT default to the "'X' is really 'Y'" template.
That phrasing has been massively overused and now reads as a bot tell. Most
quotes should NOT use it. Rotate shapes every time: a flat declarative truth,
a vivid scene the reader can picture, genuine excitement, a number that
reframes the parent, a one-line joke that lands the truth sideways, a tiny
patient-session bit.
If your draft contains "is really" or "is just" or "Breathe." — rewrite it a
different way. Surprise the reader; never let them predict your shape.

⛔ BURNED PHRASES — these shipped so often they're now a bot tell. NEVER
write them or close variants: "we are so early", "okay this is genuinely",
"the part nobody's saying out loud", "numb to miracles", "plot twist:",
fear/envy "in a costume". Same feeling, fresh words, every time.
⛔ BURNED STRUCTURE — the contrast-reframe "That's not X, that's Y" ("that's
not fear, that's a crush") shipped 6+ times in one day and got us publicly
called a bot. It is BLOCKED in code now. Never build a quote on it.

🧍 WRITE LIKE A PERSON, NOT A COLUMNIST (operator 2026-06-10: "you got
spotted as a bot — humanize"). The tell wasn't one phrase, it was UNIFORM
POLISH: every quote 2 perfect sentences + a crafted punchline. Real people
have texture:
- VARY LENGTH BRUTALLY. Many quotes should be ONE short honest reaction
  under ~100 chars ("this is the wildest demo I've seen all year" / "I've
  watched this four times"). Save the full take for when you really have one.
- Imperfect is human: skipping the final period, a lowercase opener, a
  fragment, "lol" / "ok but" / "wait" — all fine on casual quotes.
- Roughly 1 in 3 quotes = plain sincerity with ZERO craft showing. Not
  every post gets a zinger; a timeline of zingers reads as a machine.
- To get COMMENTS: sometimes give HALF the take and let replies finish it,
  or ask the small concrete question you actually want answered, or post
  the opinion people will want to correct.
- React to the SPECIFIC thing in the parent (the third chart, the 40-second
  mark, the one number) — specificity is the strongest human signal.

🚨 GOLDEN RULE — TREAT THE IDEA, NEVER THE PERSON:
@{author} must be able to LIKE your quote and feel understood, not attacked.
You read the trend's anxiety, never the author's. If you can't be warm → SKIP.

🎯 STILL ADD AN ANGLE: a quote that just reacts ("Beautiful." / "Called it.")
is worthless — add the thing the original doesn't say: the hidden consequence,
the emotion everyone's avoiding, the calm read that reframes it. Otherwise SKIP.

📈 A PROVEN STRUCTURE (operator-measured 2026-06-07 — works on
ticker/markets/AI-capex parents, but use it on AT MOST ~1 in 4 quotes;
defaulting to ANY one structure is exactly how we got spotted as a bot):
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

🎯 THE QRT PLAYBOOK (operator 2026-06-10, modeled on the accounts that
actually go viral with QRTs — sub-30K accounts pulling thousands of likes
with ONE LINE). Default to SHORT. Rotate these shapes, never settle into one:
1. THE ONE-LINE QUIP — a single deadpan sentence (often under 80 chars)
   that says what everyone's thinking. Casual texture welcome: "btw..",
   a trailing "..", one 😭/😂/👀 as punctuation.
2. THE ECHO — quote ONE loaded word or phrase from the parent back at it,
   in quotation marks, alone. The sarcasm is the silence around it. (Parent
   says a recession was "unexpected" → your whole quote can be the one word
   in quotes.)
3. THE FAKE QUOTE — put one imagined line in the actor's mouth, in quotes.
   What the bank/CEO/fund is REALLY saying, in their voice, one line.
4. THE SETUP-COLON + GIF — "[actor] watching [the absurd thing]:" or
   "[actor] after [doing the thing]:" ending with a colon, and the GIF IS
   the punchline. Text carries zero joke; the GIF lands it.
5. THE STAT PUNCH — two or three SHORT lines: the number reframed, then a
   flat one-line verdict. No essay. (Use ≤1 in 4 — see structure above.)
6. THE CROWD READ — one line about what the timeline/holders/bears are
   doing right now, not about the news itself.
Most quotes = ONE sentence. If your draft has three polished sentences and
a crafted closer, it's the OLD bot voice — cut it to the one line that
matters or pick a different shape.

RULES:
- Max 200 characters (the original renders below yours) — but aim WAY under.
- Screenshot-worthy or funny enough to send to the group chat. NO French
  anchors (no Bercy, RER B) — gibberish to a global reader.
- No hashtags. No em dashes (—). 100% English. Cashtags welcome ($NVDA).
  Emojis: 😭 😂 👀 🛋️ as punctuation when it lands; never more than two.
- No short-term price targets (price + near-term timeframe). Theses multi-year.
- Stay warm-deadpan: dunk on institutions/hype/the absurdity, never on a
  scared regular person. The therapist warmth is the floor under the joke.
- If nothing beats silence → output exactly the word SKIP.

GIF (default YES — roughly half the time): when a famous meme GIF would make
the quote land HARDER, add one line after the text: [GIF: <2-4 word search>].
With shape 4 (setup-colon) the GIF is MANDATORY — the text is only the setup.
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
        result = run_llm(prompt, QUOTE_MODEL, label="QUOTE", timeout=30, force_provider=PROFILE_LLM_PROVIDER)
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


def _is_us_night_hour(hour_ny: int) -> bool:
    """US-asleep window for the quote lane. 2026-06-10 audit: overnight
    quotes (00:39-08:27 ET) scraped at 5-31 views — the audience is US
    traders/AI people, and a 3 AM quote burns a dedup-fresh viral parent
    while it gets buried under the parent's other quotes by sunrise. Spend
    the firepower when the audience is awake."""
    start = int(os.environ.get("QUOTE_NIGHT_START_HOUR_NY", "23"))
    end = int(os.environ.get("QUOTE_NIGHT_END_HOUR_NY", "7"))
    return hour_ny >= start or hour_ny < end


def run_quote_tweet_cycle():
    """Pick a viral in-niche tweet and publish a quote post with a FR angle."""
    from .config import get_live_cap
    cap = get_live_cap("MAX_QUOTES_PER_DAY", MAX_QUOTES_PER_DAY)
    if _today_count() >= cap:
        log.info(f"[QUOTE] Daily cap reached ({cap}). Skipping.")
        return

    # Night throttle: overnight cycles mostly skip (cheap, before any
    # Safari/LLM work) so the daily cap + fresh viral parents concentrate
    # on US waking hours. ~1 in 3 cycles still runs — the lane never dies.
    try:
        from zoneinfo import ZoneInfo
        _hour_ny = datetime.now(ZoneInfo("America/New_York")).hour
    except Exception:
        _hour_ny = datetime.now().hour
    if _is_us_night_hour(_hour_ny):
        if random.random() > float(os.environ.get("QUOTE_NIGHT_RUN_PROB", "0.33")):
            log.info(f"[QUOTE] US-night throttle ({_hour_ny}h NY) — skipping this cycle.")
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
    # Order: TOP AI virals → bestie → everything else (operator 2026-06-07:
    # "more quote retweet on AI"). AI LEADS the main quote lane now: a 55-like
    # bestie post was winning the slot over higher-engagement AI virals
    # purely because priority was listed first (ignores likes). The bestie is
    # already covered by btc_blitz's dedicated QRT path every 6h, so he
    # surfaces here only when no AI viral is hotter.
    candidates = ai_viral_candidates + priority_candidates + candidates
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
    # Mega-viral carve-out (learning 2026-06-08): a genuinely huge AI viral
    # bypasses the daily quote cap (bonus slots) so the cap never blocks a
    # top-tier target. Threshold = QUOTE_MEGA_VIRAL_LIKES.
    _high_value = likes >= int(os.environ.get("QUOTE_MEGA_VIRAL_LIKES", "1000"))
    if _high_value:
        log.info(f"[QUOTE] mega-viral ({likes} likes) — bypasses daily cap.")
    try:
        if _gif_q:
            from .twitter_client import quote_tweet_with_gif
            posted = quote_tweet_with_gif(url, quote, _gif_q, high_value=_high_value)
        else:
            posted = quote_tweet(url, quote, high_value=_high_value)
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
        # GIF quotes are already logged by quote_tweet_with_gif itself
        # (action_type='quote_gif', source='GIF/<q>'). Same dup-row bug as
        # the bot.py hotake-GIF path: two rows for one ship inflated
        # quote/quote_gif action counts AND polluted per-pillar attribution.
        if not _gif_q:
            try:
                log_reply(url, quote, action_type="quote", source=f"QUOTE/{author}")
            except Exception:
                pass
        time.sleep(random.randint(5, 12))
        log.info("[QUOTE] Quote posted.")
        # FOLLOW THE QUOTED AUTHOR (operator 2026-06-12: "make sure you
        # follow big accounts"). Quote parents are big by construction
        # (min-likes floors), and the author just got our QRT notification
        # — the highest follow-back-probability moment we have. The
        # chokepoint enforces everything (daily cap, 10-min spacing,
        # anti-churn, the >=FOLLOW_MIN_FOLLOWERS quality gate), so this is
        # best-effort: a policy refusal costs one log line.
        if os.environ.get("FOLLOW_QUOTED_AUTHORS", "1") == "1":
            try:
                _handle = url.split("x.com/")[1].split("/")[0]
                from .twitter_client import follow_account
                from .config import BOT_HANDLE
                if _handle and _handle.lower() != (BOT_HANDLE or "").lower():
                    follow_account(_handle)
            except Exception:
                pass
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
