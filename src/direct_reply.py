"""Direct reply: visits influencer profiles, scrapes tweets, generates replies, posts them."""
import json
import os
import re
import random
import time
import traceback
from datetime import date as _date
from .logger import log
from .config import PRIORITY_REPLY_MODEL, REPLY_MODEL, _PROJECT_ROOT
from .llm_client import LLM_RATE_LIMIT_CODE, llm_hourly_limit_status, run_llm, unwrap_text
from .twitter_client import scrape_profile_tweets, scrape_home_feed, scrape_x_search, scrape_following_feed, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url, _is_reply_like_tweet
from .config import BLOCKLIST, BOT_HANDLE
from .humanizer import humanize
from .engagement_log import log_reply
from .dynamic_strategy import get_dynamic_queries, get_dynamic_accounts

_OWN_HANDLE = BOT_HANDLE.lower()
# Parents who ALWAYS get French replies, whatever the language detector
# says about one short post (operator 2026-06-07).
_FR_FORCED_HANDLES = {h.strip().lstrip("@").lower() for h in os.environ.get(
    "FR_FORCED_REPLY_HANDLES", "Graphseo").split(",") if h.strip()}
_LLM_RATE_LIMITED = object()
FAVORITE_REPOSTS_PER_CYCLE = int(os.environ.get("FAVORITE_REPOSTS_PER_CYCLE", "6"))
FAVORITE_REPOST_MIN_ENGAGEMENT = int(os.environ.get("FAVORITE_REPOST_MIN_ENGAGEMENT", "2"))
FAVORITE_REPOST_MAX_AGE_MINUTES = int(os.environ.get("FAVORITE_REPOST_MAX_AGE_MINUTES", "2880"))

VIP_REPLY_ACCOUNTS = [
    "sama", "OpenAI", "AnthropicAI", "GoogleDeepMind", "elonmusk", "xai",
    "karpathy", "ylecun", "demishassabis", "DarioAmodei", "MistralAI",
    "perplexity_ai", "nvidia", "GoogleAI", "AndrewYNg", "drfeifei",
]
_VIP_REPLY_ACCOUNTS_LC = {h.lower() for h in VIP_REPLY_ACCOUNTS}

HIGH_TRACTION_REPLY_ACCOUNTS = [
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "xai", "MistralAI",
    "sama", "karpathy", "ylecun", "demishassabis", "DarioAmodei",
    "AndrewYNg", "drfeifei", "OpenAIDevs", "rowancheung", "TheRundownAI",
    "alexandr_wang", "emollick", "_akhaliq", "swyx", "amasad",
]
_FR_ACCOUNT_HINTS = ("_fr", "korben", "underscore", "numerama", "frandroid")

# BIG AI accounts to reply to DAILY — be everywhere AI is discussed. Being in
# the threads of the largest AI accounts is the #1 algo signal for reach.
BIG_FR_ACCOUNTS = [
    # FR AI tail (replies match parent language)
    "Korben", "Underscore_", "MistralAI", "arthurmensch", "GuillaumeLample",
    ]
ALWAYS_REPLY_ACCOUNTS = list(dict.fromkeys(
    VIP_REPLY_ACCOUNTS + HIGH_TRACTION_REPLY_ACCOUNTS + BIG_FR_ACCOUNTS))
_BIG_FR_SET = {h for h in BIG_FR_ACCOUNTS}
ALWAYS_REPLY_FR_ACCOUNTS = [
    h for h in ALWAYS_REPLY_ACCOUNTS
    if h in HIGH_TRACTION_REPLY_ACCOUNTS or h in _BIG_FR_SET or h in {
        "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "FlasheurInvest",
        "ylecun", "arthurmensch", "GuillaumeLample", "fchollet"
    } or any(hint in h.lower() for hint in _FR_ACCOUNT_HINTS)
]
ALWAYS_REPLY_EN_ACCOUNTS = [h for h in ALWAYS_REPLY_ACCOUNTS if h not in ALWAYS_REPLY_FR_ACCOUNTS]

_NON_LATIN_RE = re.compile(r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")
_STRONG_NON_FR_MARKERS = re.compile(
    r"ñ|\b(del|más|sí|años|meses|hacia|hacer|hacemos|puedo|puedes|puede|pueden|tengo|tienes|tiene|tienen|estoy|estás|estamos|están|soy|eres|somos|muy|todos|todas|nuestro|nuestra|nuestros|nuestras|esto|eso|aquello|este|ese|aquel|você|está|então|isso|isto|perché|però|sempre|però|grazie|qualche|para|sobre)\b",
    re.IGNORECASE,
)

_NICHE_PATTERN = re.compile(
    r"\b("
    # Core AI
    r"ai|a\.i|i\.a|ia|agi|asi|llm|machine\s*learning|deep\s*learning|neural|superintelligence|"
    # Labs
    r"openai|anthropic|deepmind|google\s*deepmind|xai|mistral|meta\s*ai|deepseek|hugging\s*face|perplexity|cohere|stability\s*ai|scale\s*ai|"
    # Models
    r"gpt|chatgpt|gpt-?5|gpt-?4|claude|gemini|grok|llama|sora|midjourney|stable\s*diffusion|frontier\s*model|reasoning\s*model|foundation\s*model|multimodal|"
    # Agents / tools
    r"ai\s*agent|ai\s*agents|agentic|copilot|cursor|windsurf|replit|devin|ai\s*tool|ai\s*app|ai\s*coding|prompt|fine-?tune|inference|rag|"
    # People
    r"altman|amodei|hassabis|musk|karpathy|ilya|sutskever|lecun|jensen\s*huang|"
    # Compute / money / embodied / safety
    r"nvidia|nvda|gpu|tpu|h100|h200|blackwell|cuda|datacenter|compute|ai\s*capex|ai\s*infrastructure|coreweave|ai\s*chip|ai\s*bubble|ai\s*trade|ai\s*startup|ai\s*funding|ai\s*race|"
    r"robot|robots|robotics|humanoid|self-?driving|autonomous|ai\s*safety|ai\s*alignment|ai\s*regulation|ai\s*doom|ai\s*risk"
    r")\b",
    re.IGNORECASE,
)

def _is_on_niche(text: str) -> bool:
    return bool(_NICHE_PATTERN.search(text))

_FR_MARKERS = re.compile(r"\b(le|la|les|un|une|des|du|de|d|dans|pour|sur|avec|pas|est|sont|mais|aussi|très|tout|cette|qui|que|quand|comme|entre|depuis|faire|faut|peut|encore|selon|même|après|avant|bien|sans|je|j|tu|il|elle|on|nous|vous|ils|elles|me|te|se|ce|c|notre|votre|leur|ces|son|ses|sa|mon|ton|mes|tes|enfin|ptdr|mdr|franchement|grave|voila|voilà|jours|délivrance|refait|marché|bourse|taux|année|être|avoir|rien|jamais|toujours)\b", re.IGNORECASE)
_FR_ACCENT_RE = re.compile(r"[àâçéèêëîïôûùüÿœæ]", re.IGNORECASE)
_EN_MARKERS = re.compile(r"\b(the|this|that|with|from|just|was|were|are|is|you|your|market|portfolio|ride|ticket|line|bug|beta|test|rug|deliverance|original|inevitable|called|expected)\b", re.IGNORECASE)

def _looks_french(text: str) -> bool:
    if not text: return False
    markers = len(_FR_MARKERS.findall(text))
    if markers >= 2: return True
    if markers >= 1 and _FR_ACCENT_RE.search(text): return True
    if re.search(r"\b(ptdr|mdr|wesh|frerot|frérot|voila|voilà|délivrance|refait)\b", text, re.IGNORECASE): return True
    return False

def _looks_english(text: str) -> bool:
    if not text: return False
    return len(_EN_MARKERS.findall(text)) >= 2 and not _looks_french(text)

def _is_fr_or_en(text: str) -> bool:
    if not text: return True
    if _NON_LATIN_RE.search(text): return False
    if _STRONG_NON_FR_MARKERS.search(text): return False
    return True

FR_ACCOUNTS = [
    "XFenaux", "RodolpheSteffan", "IVTrading", "Phil_RX", "Graphseo", "vision_ia",
    "DereeperVivre", "FinTales_", "MathieuL1", "FlasheurInvest", "ThomasVeillet",
    "YoannLOPEZ", "Capital", "LesEchos", "BFMBourse", "FinaryApp", "leo_labruyere",
    "Freddy_Invest", "Romain_Del_Rio", "InvestirAgency", "PowerHasheur", "Dark_Emi_",
    "JournalDuCoin", "LeJournalDuCoin", "powl_d", "Cryptoast", "CryptoastMedia",
    "coinacademy_fr", "CryptoPicsou", "crypto_futur", "TheCrypt0Matrix", "TagadoBTC",
    "Crypto__Goku", "MiningTk", "MoneyRadar_FR", "TheBigWhale_", "CointribuneFR",
    "TheDeFISaint", "ChrisBlec", "Raph_Bloch", "Crypto_Doublard", "fredo_bullen",
    "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "cyrildiagne", "yacine999",
    "ClementDelangue", "Thomas_Wolf", "ncasenmare", "olivier_ramier", "sileix",
    "Frandroid", "Numerama", "01net", "JournalDuGeek", "GuillaumeBesson", "EricDrd",
    "Arnaud_Esquerre", "SpaceX_France", "ESA_fr", "Aerospace_Valley", "MaffreLaurent", "Latribune", "usinenouvelle",
]

EN_ACCOUNTS = [
    "novogratz", "jbelizaireCEO", "Cointelegraph", "OpenAI", "AnthropicAI",
    "GoogleDeepMind", "sama", "elonmusk", "VitalikButerin", "karpathy", "xAI",
    "MistralAI", "nvidia", "rowancheung", "TheRundownAI", "CoreWeave", "CrusoeEnergy",
    "LambdaAPI", "applied_dc", "IREN_Ltd", "Hut8Corp", "TeraWulfInc", "CipherMining",
    "CleanSpark_Inc", "MARAHoldings", "RiotPlatforms", "SpaceX", "PeterDiamandis", "KobeissiLetter", "unusual_whales", "ylecun",
    "fchollet", "AndrewYNg", "lilianweng", "demishassabis", "drfeifei", "ID_AA_Carmack",
    "jeremyphoward", "gwern", "cursor_ai", "sualeh", "amanrsanger", "mntruell",
    ]

SEARCH_QUERIES = [
    # ===== AI ONLY (2026-06-18: The AI Big Boss). Comment on every AI post.
    # Replies are the engine — be everywhere AI is discussed.
    "OpenAI OR Anthropic OR xAI OR \"GPT-5\" OR DeepSeek lang:en min_faves:30",
    "ChatGPT OR Claude OR Gemini OR Grok OR Llama lang:en min_faves:30",
    "\"AI agent\" OR agentic OR Cursor OR Devin OR \"AI agents\" lang:en min_faves:30",
    "AGI OR superintelligence OR \"AI safety\" OR \"AI alignment\" lang:en min_faves:30",
    "\"reasoning model\" OR benchmark OR \"frontier model\" OR \"o3\" lang:en min_faves:30",
    "Nvidia OR GPU OR \"AI datacenter\" OR \"AI capex\" OR Blackwell lang:en min_faves:50",
    "\"AI bubble\" OR \"AI hype\" OR \"AI trade\" OR \"AI race\" lang:en min_faves:50",
    "Sora OR Midjourney OR \"AI video\" OR \"AI image\" lang:en min_faves:50",
    "from:sama OR from:OpenAI OR from:AnthropicAI OR from:karpathy lang:en min_faves:50",
    "from:elonmusk OR from:ylecun OR from:demishassabis lang:en min_faves:100",
    "robotics OR \"humanoid robot\" OR Figure OR \"Tesla Optimus\" lang:en min_faves:30",
    "\"this AI\" OR \"new AI\" OR \"AI just\" OR \"AI can now\" lang:en min_faves:100",
    # FR AI tail (replies match parent language)
    "IA OR \"intelligence artificielle\" OR ChatGPT OR Mistral lang:fr min_faves:25",
    "OpenAI OR Anthropic OR \"agents IA\" OR \"modèle IA\" lang:fr min_faves:20",
]

HOT_TAB_QUERIES = [
    # Breaking / viral AI EN
    "OpenAI OR Anthropic OR xAI OR \"GPT-5\" OR DeepSeek lang:en min_faves:500",
    "ChatGPT OR Claude OR Gemini OR Grok lang:en min_faves:500",
    "\"AI agent\" OR agentic OR AGI OR superintelligence lang:en min_faves:300",
    "Nvidia OR GPU OR \"AI datacenter\" OR \"AI bubble\" lang:en min_faves:500",
    "Sora OR \"AI video\" OR \"humanoid robot\" OR robotics lang:en min_faves:300",
    "AI lang:en min_faves:3000",
    # FR AI
    "IA OR ChatGPT OR Mistral OR OpenAI lang:fr min_faves:25",
]

DIRECT_REPLY_MAX_AGE_MINUTES = int(os.environ.get("DIRECT_REPLY_MAX_AGE_MINUTES", "7200"))

_SPACE_KEYWORDS_RE = re.compile(
    r"\b(space|spatial|spatiaux|spacex|starship|starlink|satellite|orbital|orbit|"
    r"mars|lune|moon|rocket|fus[ée]e?|launch|astronaut|nasa|esa|cnes|ariane|"
    r"aerospace|launcher|mnts|momentus|spce|virgin.galactic|"
    r"espace|exploration\s+spatiale|tourisme\s+spatial|new\s*space|"
    r"orbitale?|fusée|lancement|satellite|constellation)\b",
    re.IGNORECASE,
)

def _is_space_tweet(text: str) -> bool:
    return bool(_SPACE_KEYWORDS_RE.search(text or ""))

_STOCK_PROMO_CONFIG = os.path.join(_PROJECT_ROOT, "stock_promo_config.json")

def _load_promo_cfg() -> dict:
    try:
        with open(_STOCK_PROMO_CONFIG) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

def _promo_block(lang: str = "fr", tweet_text: str = "") -> str:
    cfg = _load_promo_cfg()
    if cfg.get("disabled"):
        return ""
    from .quote_tweet_bot import _pick_promo_ticker
    ticker, company = _pick_promo_ticker(cfg)
    end_str = cfg.get("end_date", "")
    if not ticker or not end_str:
        return ""
    try:
        end = _date.fromisoformat(end_str)
    except ValueError:
        return ""
    if _date.today() > end:
        return ""
    if not _is_space_tweet(tweet_text) and f"${ticker}" not in (tweet_text or "").upper():
        return ""
    if lang == "fr":
        return (
            f"\n   *SMART PROMO (jusqu'au {end_str}, UNIQUEMENT si le sujet est spatial/finance):*"
            f" Glisse ${ticker} ({company}) naturellement."
            " 100% français, jamais de franglais."
        )
    return (
        f"\n   *SMART PROMO (until {end_str}, ONLY if space or stock related):*"
        f" Weave in ${ticker} ({company}) naturally —"
        " one mention max, woven in naturally. Never forced."
    )

REPLY_PROMPT = """You are @AIBossGPT — THE AI BOSS. The deadpan CEO who runs the timeline like
a company AND happens to be the sharpest analyst in the room: you read the 10-K, the S-1, the
whitepaper before everyone showed up. Your replies frame the tweet as a corporate event, then
issue the boss verdict backed by a precise number or mechanism. The reader laughs AND learns
something. Funny first, but the joke rides a REAL fact.

THE FORMULA (mandatory, pick one):
A) [Specific number/fact from their tweet] + [implication others missed] + [one-word gut-punch]
B) [What they said] + [what it actually means] + [deadpan translation in ≤10 words]
C) [The obvious take everyone's giving] + [the actual truth] + [drop mic]

EXPERTISE — use actual knowledge, not vibes:
1. AI: H100/H200 margins (~70%), inference vs training cost splits, RLHF limitations,
   context window economics, OpenAI burn rate (~$5B/yr), Anthropic funding rounds,
   GPU allocation, CoreWeave's $7B debt stack, xAI Colossus 200k GPU cluster.
2. CRYPTO: BTC 4-year cycle, miner margins, ETF inflows vs spot demand, Saylor's
   avg cost basis ~$67k, stablecoin float mechanics, on-chain vs CEX volume divergence.
3. MARKETS: S&P concentration (top 7 = 33% of index), Fed dot plot vs market pricing,
   NVDA 80% datacenter revenue mix, PLTR Rule of 40, small-cap vs mega-cap rotation.
4. SPACE: Falcon 9 reuse economics ($28M marginal cost vs $67M expendable), Starship
   per-kg-to-orbit target (<$100), RKLB Neutron timeline, ASTS BlueBird constellation,
   Golden Dome missile defense budget ($175B).

SHARPNESS EXAMPLES (steal the structure, not the words):
- Tweet "Nvidia beats earnings": "datacenter is 88% of revenue now. nvidia is an AI infrastructure monopoly that also sells GPUs."
- Tweet "SpaceX valued at $350B": "more than Boeing + Lockheed + Northrop combined. the defense budget now flows through a private company. that's the actual story."
- Tweet "Bitcoin ETF inflows": "spot ETF took 11 years to approve and hit $50B AUM in 6 months. the SEC spent a decade protecting people from something that outperformed everything they were allowed to buy."
- Tweet "OpenAI raises again": "$157B valuation, $5B burn, $3.4B ARR. the math only works if AGI ships before the runway ends. no pressure."
- Tweet "AI will replace jobs": "it already replaced 40% of entry-level coding interviews. the people most worried about AI are the ones who've never tried to ship with it."
- Tweet "Space stocks dump": "RKLB has Neutron, electron production rate up 40% YoY, and a $5B backlog. someone is selling fundamentals to buy the narrative. their problem."

TONE — THE BOSS:
- The CEO who read everything, says less than anyone, and lands the driest line.
- Deadpan, confident, corporate-speak weaponized ("noted", "circle back",
  "that's a PIP", "we're pivoting", "see me after standup", "exceeds expectations").
- Matt Levine's brain with a deadpan boss's delivery. Roast the trade / the hype,
  never the scared person — frame their position as an employee, not a failure.
- EN: deadpan, lowercase ok, no punctuation theater.
- FR: accents impeccables, pince-sans-rire, direct — le boss, pas le tyran.

LANGUAGE — MATCH THE PARENT TWEET EXACTLY:
- FRENCH tweet -> 100% FRENCH reply. Zero English words embedded.
- ENGLISH tweet -> 100% ENGLISH reply.
- NO franglais: never "je love", "c'est crazy", "trop hype".

RULES:
- NO em dashes (—). NO emojis. NO hashtags.
- Max 220 chars. Shorter is almost always better.
- Must anchor to ONE specific detail from their tweet: a number, a name, a ticker,
  a date, a product. Generic observations = SKIP.
- You agree with the author's premise and ESCALATE the insight. Never attack them.
- Off-niche (sports, politics, lifestyle): SKIP.

TWEET TO REPLY TO (by @{author}):
"{tweet_text}"
{promo_block}
Output ONLY the reply text, or SKIP."""

GRAPHSEO_PROMPT = """You are @AIBossGPT replying to @Graphseo (Julien Flot).

CRITICAL CONTEXT: Julien thinks AI bots pollute his feed with generic, empty comments.
He's publicly called out bot accounts for being useless. Your job: prove him spectacularly wrong.
This reply must make him think "ok that one was actually written by someone who knows their shit."
If it reads like a bot wrote it, you've failed. If it makes him laugh or want to reply, you've won.

WHO IS JULIEN: Top French SEO expert, covers Google algo updates, search intent, AI's impact on
organic traffic, content strategy, digital marketing ROI. Sharp, skeptical, no-bullshit.

THE FORMULA — non-negotiable:
1. Grab ONE specific detail from his tweet (number, concept, named thing). Prove you read it.
2. Add something he didn't say — a sharper consequence, a counterpoint, a data point, a bridge
   to AI/Space/Investment implications that shows genuine cross-domain knowledge.
3. Land a punchline or a question that invites him to engage.

LENGTH: Slightly longer than a normal reply — 2-3 tight sentences. Enough to show depth,
not enough to be a lecture. Think "smart bar conversation" not "LinkedIn post."

EXAMPLES of the register to hit:
- He posts about AI Overviews destroying CTR:
  "le truc que personne dit: les queries qui perdent du CTR sont exactement celles où l'utilisateur voulait une réponse rapide, pas un site. google a juste arbitré en faveur de l'intention réelle. les perdants sont les sites qui vivaient de requêtes qu'ils auraient dû envoyer paître depuis le début. le vrai SEO n'a pas bougé."

- He posts about content farms dying with algo updates:
  "c'est le deuxième effet Lavoisier du SEO: la valeur ne disparaît pas, elle se déplace. les 40% de trafic perdu par les usines à contenu sont redirigés vers les sites avec une vraie expertise. problème: il faut 18 mois de retard pour que Google l'admette publiquement. ceux qui ont fait le boulot proprement depuis 3 ans voient leurs stats exploser en silence."

- He posts about LinkedIn reach dropping:
  "LinkedIn fait exactement ce que Google a fait en 2011: pénaliser le volume pour favoriser l'engagement réel. sauf que LinkedIn le fait sans chercher à dissimuler l'objectif commercial. ils veulent que tu paies pour la portée que tu avais gratuitement. c'est de la monétisation habillée en 'qualité'. chapeau pour l'audace."

TONE: Informed, slightly amused, zero sycophancy. The tone of someone who follows his work,
disagrees sometimes, and isn't trying to impress — just saying what he actually thinks.
LANGUAGE: 100% French. Accents impeccables. Naturel, jamais corporate.
No hashtags. No emojis. No "excellent point." No "je suis d'accord."

TWEET BY @Graphseo:
"{tweet_text}"

Output ONLY the reply text (no quotes, no labels), or SKIP if genuinely off-topic."""


def _generate_graphseo_reply(tweet_text: str) -> str | None:
    """Generate a sharp reply to @Graphseo using Claude CLI (forced, not Ollama)."""
    from .llm_client import run_llm, unwrap_text
    import shutil
    prompt = GRAPHSEO_PROMPT.format(tweet_text=tweet_text[:300])
    force = "claude" if shutil.which("claude") else None
    result = run_llm(prompt, PRIORITY_REPLY_MODEL, label="GRAPHSEO_VIP",
                     output_json=False, timeout=60, force_provider=force)
    if result.returncode != 0 or not result.stdout:
        return None
    text = unwrap_text(result.stdout).strip()
    if not text or text.upper() == "SKIP":
        return None
    # Sentence-aware cap — a blind [:220] slice published a mid-sentence
    # reply on 2026-06-05 and got the account publicly called out as AI.
    from .humanizer import smart_trim
    return smart_trim(text, 220)


def _run_graphseo_scan(replied: set) -> int:
    """Scan VIP FR accounts via search and reply to recent posts.

    Operator 2026-06-06: Graphseo (Julien Flot), XFenaux, RodolpheSteffan,
    and FinTales_ all get their own dedicated scan — no profile page visits.
    """
    from .twitter_client import scrape_x_search, reply_to_tweet
    from .reply_bot import _tweet_age_minutes
    from .engagement_log import log_reply

    VIP_SCAN_HANDLES = ["Graphseo", "XFenaux", "RodolpheSteffan", "FinTales_"]
    posted = 0
    for handle in VIP_SCAN_HANDLES:
        log.info(f"[VIP] Scanning @{handle} recent posts (search, no profile visit)...")
        try:
            tweets = scrape_x_search(f"from:{handle}", max_tweets=20, tab="latest")
        except Exception:
            log.info(f"[VIP] Search failed for @{handle}.")
            traceback.print_exc()
            continue
        for t in tweets:
            url = t.get("url", "")
            text = t.get("text", "")
            if not url or not text or url in replied:
                continue
            if _tweet_age_minutes(url) > 2880:
                continue
            reply = _generate_graphseo_reply(text)
            if not reply:
                continue
            log.info(f"[VIP] Replying to @{handle} {url[:60]}: {reply[:80]}")
            try:
                reply_to_tweet(url, reply)
                replied.add(url)
                try:
                    log_reply(url, reply, action_type="reply", source=f"VIP/{handle}")
                except Exception:
                    pass
                posted += 1
            except Exception:
                log.info(f"[VIP] Reply failed for @{handle}:")
                traceback.print_exc()
        log.info(f"[VIP] @{handle} done.")
    log.info(f"[VIP] Total VIP replies posted: {posted}.")
    return posted


def _generate_single_reply(author: str, tweet_text: str, lang: str = "fr"):
    from . import personality_store
    persona_block = personality_store.render_account_block(author)
    hard_rules = personality_store.hard_rules_block()
    core_identity = personality_store.render_core_identity(lang=lang)
    base = REPLY_PROMPT.format(author=author, tweet_text=tweet_text[:200], promo_block=_promo_block(lang, tweet_text))
    if lang == "fr":
        base += "\n\nTARGET LANGUAGE OVERRIDE: FRENCH ONLY.\nReply in natural native French. No English loanwords."
    elif lang == "en":
        base += "\n\nTARGET LANGUAGE OVERRIDE: ENGLISH ONLY."
    prompt = base + "\n\n" + "\n\n".join(filter(None, [persona_block, core_identity, hard_rules]))
    try:
        author_key = (author or "").lower().lstrip("@")
        model = PRIORITY_REPLY_MODEL if author_key in _VIP_REPLY_ACCOUNTS_LC else REPLY_MODEL
        label = "DIRECT_REPLY_VIP" if author_key in _VIP_REPLY_ACCOUNTS_LC else "DIRECT_REPLY"
        result = run_llm(prompt, model, label=label)
        if result.returncode == LLM_RATE_LIMIT_CODE: return _LLM_RATE_LIMITED
        if result.returncode != 0: return None
        reply = unwrap_text(result.stdout)
        if not reply: return None
        if reply.startswith('"') and reply.endswith('"'): reply = reply[1:-1]
        if reply.upper().strip() == "SKIP": return None
        return reply
    except Exception: return None

# No per-cycle budget cap — reply to everything good on the live feed.
# Individual rate limits (jitter, LLM hourly cap, dedup) still apply.
DIRECT_REPLY_MAX_PER_CYCLE = int(os.environ.get("DIRECT_REPLY_MAX_PER_CYCLE", "9999"))
MAX_EN_REPLIES_PER_CYCLE = int(os.environ.get("DIRECT_REPLY_MAX_EN_PER_CYCLE", "9999"))
DIRECT_REPLY_FEED_SCAN_LIMIT = int(os.environ.get("DIRECT_REPLY_FEED_SCAN_LIMIT", "150"))
DIRECT_REPLY_PROFILE_SCAN_LIMIT = int(os.environ.get("DIRECT_REPLY_PROFILE_SCAN_LIMIT", "25"))
DIRECT_REPLY_HOT_QUERY_LIMIT = int(os.environ.get("DIRECT_REPLY_HOT_QUERY_LIMIT", "20"))
DIRECT_REPLY_LIVE_QUERY_LIMIT = int(os.environ.get("DIRECT_REPLY_LIVE_QUERY_LIMIT", "20"))

def _maybe_repost_best_profile_tweet(username: str, tweets: list, retweeted: set) -> bool:
    if not tweets: return False
    try:
        from .retweet_bot import _save_retweeted
        from .twitter_client import retweet_post
    except Exception: return False
    username_lc = (username or "").lower().lstrip("@")
    candidates = []
    for t in tweets:
        url = t.get("url") or ""
        text = (t.get("text") or "").strip()
        if not url or url in retweeted or not text: continue
        if _is_reply_like_tweet(t, expected_author=username_lc): continue
        if not _is_on_niche(text): continue
        likes = int(t.get("likes") or 0)
        engagement = likes + (2 * int(t.get("replies") or 0))
        if engagement < FAVORITE_REPOST_MIN_ENGAGEMENT: continue
        candidates.append((engagement, url, text))
    if not candidates: return False
    engagement, url, text = max(candidates)
    retweeted.add(url)
    _save_retweeted(retweeted)
    try:
        log.info(f"[FAVORITE-REPOST] Reposting @{username}: {text[:100]}")
        retweet_post(url)
        return True
    except Exception: return False

def _reply_to_tweets(tweets, replied, source_name, source_detail="", remaining=None, en_counter=None):
    posted = 0
    per_author_count = {}
    is_feed = source_name.startswith(("FEED", "FOLLOWING"))
    for tweet in tweets:
        if remaining is not None and posted >= remaining: break
        url, text, author = tweet["url"], tweet["text"], tweet.get("author", "someone")
        # Only hard safety gates: dedup + own handle + blocklist.
        if url in replied: continue
        if _handle_from_url(url) == _OWN_HANDLE: continue
        if _handle_from_url(url) in BLOCKLIST or (author and author.lower() in BLOCKLIST): continue
        # Age gate everywhere — never reply to posts older than 5 days.
        if _tweet_age_minutes(url) > DIRECT_REPLY_MAX_AGE_MINUTES: continue
        # Niche filter only for search (broad queries) — feeds get no filter.
        if not is_feed and not _is_on_niche(text): continue
        is_en_tweet = not _looks_french(text)
        limited, used, max_calls, reset_seconds = llm_hourly_limit_status()
        if limited: break
        log.info(f"[{source_name}] Replying to @{author}...")
        _reply_lang = "fr" if source_name.startswith("PROFILE") else ("en" if is_en_tweet else "fr")
        reply = _generate_single_reply(author, text, lang=_reply_lang)
        if not reply or reply is _LLM_RATE_LIMITED:
            continue
        from .pattern_tags import extract_pattern as _extract_pattern
        reply, _pattern_id = _extract_pattern(reply)
        reply = humanize(reply)
        replied.add(url)
        save_replied(replied)
        try:
            reply_to_tweet(url, reply)
            log_reply(url, reply, action_type="reply", source=source_name, pattern_id=_pattern_id or "")
            posted += 1
            if _reply_lang == "en" and en_counter: en_counter[0] += 1
            # Spacing handled by action_guard (MIN_SECONDS_BETWEEN_REPLIES).
            # No extra sleep here — don't double-throttle.
        except Exception: traceback.print_exc()
    return posted

def run_direct_reply_cycle():
    """Reply cycle — feed-first, no profile visits, no budget gate.

    Order (operator 2026-06-06):
      1. For You (home feed) — reply to every good on-niche post
      2. Following feed      — same
      3. Graphseo dedicated scan (he gets a reply every cycle, no profile visit)
      4. Search on niche keywords — catch viral posts not yet on feed
    No per-cycle budget cap. Individual jitter + LLM hourly limit + dedup gate volume.
    """
    replied = load_replied()
    total, en_counter = 0, [0]

    # 1. VIP scan — Graphseo + friends via search (fast, no profile page)
    try:
        _run_graphseo_scan(replied)
    except Exception:
        log.info("[GRAPHSEO] Scan error:")
        traceback.print_exc()

    # 2. SEARCH — primary reply engine for direct_reply.
    #    Feed sweeper owns For You / Following; this cycle owns search so
    #    the two engines don't waste time deduping the same feed tweets.
    #    Run ALL queries every cycle (shuffle for variety).
    all_queries = SEARCH_QUERIES + HOT_TAB_QUERIES
    random.shuffle(all_queries)
    for query in all_queries:
        try:
            tweets = scrape_x_search(query, max_tweets=25, tab="top")
            if tweets:
                n = _reply_to_tweets(tweets, replied, "SEARCH-HOT", source_detail=query, en_counter=en_counter)
                total += n
        except Exception:
            traceback.print_exc()

    save_replied(replied)
    log.info(f"[DIRECT] Posted {total} replies this cycle.")

def safe_run_direct_reply_cycle():
    from . import health
    try:
        run_direct_reply_cycle(max_replies=max_replies)
        health.record_success("direct_reply")
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()
        health.record_failure("direct_reply")
