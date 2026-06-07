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
_LLM_RATE_LIMITED = object()
FAVORITE_REPOSTS_PER_CYCLE = int(os.environ.get("FAVORITE_REPOSTS_PER_CYCLE", "6"))
FAVORITE_REPOST_MIN_ENGAGEMENT = int(os.environ.get("FAVORITE_REPOST_MIN_ENGAGEMENT", "2"))
FAVORITE_REPOST_MAX_AGE_MINUTES = int(os.environ.get("FAVORITE_REPOST_MAX_AGE_MINUTES", "2880"))

VIP_REPLY_ACCOUNTS = [
    "TheBTCTherapist",  # model account — reply to + amplify everything he posts
    "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "novogratz",
    "jbelizaireCEO", "FlasheurInvest", "ylecun", "arthurmensch",
    "GuillaumeLample", "fchollet", "karpathy", "demishassabis", "sama",
    "VitalikButerin", "saylor", "brian_armstrong", "cz_binance", "SpaceX"
]
_VIP_REPLY_ACCOUNTS_LC = {h.lower() for h in VIP_REPLY_ACCOUNTS}

HIGH_TRACTION_REPLY_ACCOUNTS = [
    "PowerHasheur", "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr",
    "CryptoPicsou", "crypto_futur", "TheCrypt0Matrix", "TagadoBTC",
    "Crypto__Goku", "MiningTk", "MoneyRadar_FR", "Capetlevrai", "Dark_Emi_",
    "Divs_King", "MathieuL1", "NCheron_bourse", "ABaradez", "Phil_RX",
    "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "fchollet", "MistralAI"
]
_FR_ACCOUNT_HINTS = ("_fr", "cryptoast", "coinacademy", "journalducoin", "fintales", "graphseo", "vision_ia")

# 2026-06-02: BIG French accounts to reply to DAILY across the 5 verticals.
# Being in the threads of large FR AI / bourse / crypto / investment / space
# accounts is the #1 algo signal for reach + follower conversion. These are
# fed into the PROFILE-ALWAYS reply path so each cycle pulls their latest
# tweets and lands a sharp FR reply (subject to the 48h + caps + substance gate).
BIG_FR_ACCOUNTS = [
    # IA / Tech FR
    "Korben", "micode", "Underscore_", "presse_citron", "numerama",
    "siecledigital", "BFMTech", "frandroid", "journaldugeek", "FlavienChervet",
    "MistralAI", "arthurmensch", "GuillaumeLample",
    # Bourse / Investissement FR
    "Heu7reka", "Yoann_Lopez_", "Finary", "ZonebourseFR", "BFMBourse",
    "latribune", "Capital", "LesEchos", "boursorama", "GoodValYou",
    "Zonebourse", "Investir", "SnowballEcho",
    # Crypto FR
    "Hasheur", "cryptodiffusion", "Cointribune", "BFMcrypto", "PowerHasheur",
    "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr", "CryptoPicsou",
    # Spatial FR
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
    r"ai|i\.a|ia|agi|llm|gpt|chatgpt|claude|openai|anthropic|mistral|gemini|grok|xai|deepseek|huggingface|nvidia|cuda|gpu|tpu|agent|agents|robot|robots|humanoide|humanoïde|altman|musk|ml|deep\s*learning|neural|saas|software|cloud|datacenter|"
    r"codex|copilot|cursor|windsurf|replit|programmeur|coding|coder|développeur|ide|api|sdk|"
    r"crypto|btc|bitcoin|eth|ethereum|sol|solana|xrp|blockchain|defi|stablecoin|token|altcoin|memecoin|nft|wallet|binance|coinbase|kraken|satoshi|web3|dao|staking|yield|dex|cex|"
    r"space|espace|spatial|spacex|starship|starlink|rocket|fusée|fusee|satellite|nasa|esa|ariane|arianegroup|blue\s*origin|orbite|orbit|astéroïde|exploration|mars|lune|moon|cosmos|"
    r"bourse|action|actions|stock|stocks|marché|trading|trader|invest|investir|portefeuille|etf|pea|cto|cac|cac40|nasdaq|fed|bce|taux|powell|lagarde|rendement|dividendes|ipo|valuation|per|fcf|roe|roic|livret|assurance|levée|fund|funding|vc|venture|startup|banque|fintech|néobanque|paiement|virement|swift|sepa|immo|immobilier|inflation|récession|earnings|acquisition|merger|m&a|finance|cotation|pétrole|xau|commodity|semi.?conducteur|bullish|bearish|oversold|resistance|support|volatility|krach|goldman|jpmorgan|morgan\s*stanley|dette|deficit|fiscal|impot|budget|deflation|monetaire|souverain|oat|spread|notation|moody|tesla|meta|microsoft|google|amazon|apple|netflix|alphabet|spotify|uber|airbnb|palantir|shopify|stripe|databricks|snowflake|datadog|cloudflare"
    r")\b",
    re.IGNORECASE,
)
_TICKER_RE = re.compile(r"\$[A-Z]{1,5}\b")

def _is_on_niche(text: str) -> bool:
    return bool(_NICHE_PATTERN.search(text) or _TICKER_RE.search(text))

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
    # ===== 2026-06-07 AGENT SPEC lane: AI x markets x PSYCHOLOGY. =====
    # Space queries REMOVED (persona: no space content). FR tail slimmed to
    # one query (replies still match parent language when FR shows up).
    #
    # ===== SEEDS FIRST — tier1-2 reply targets + foils (spec: "Targets:
    # ... from the follow whitelist (Tier 1-2 first)"). Low min_faves: we
    # want their FRESH posts before they trend, freshness sort does the rest.
    "from:TheBTCTherapist OR from:morganhousel OR from:ParikPatelCFA OR from:litcapital min_faves:5",
    "from:greg16676935420 OR from:ReformedBroker OR from:jasonzweigwsj OR from:saylor min_faves:5",
    # ===== INVESTOR PSYCHOLOGY — the home turf (market-trauma pillar) =====
    "\"panic sold\" OR \"panic selling\" OR \"bought the top\" OR \"sold the bottom\" lang:en min_faves:30",
    "\"portfolio is down\" OR \"red day\" OR drawdown OR \"bag holder\" OR bagholding lang:en min_faves:30",
    "FOMO OR copium OR hopium OR \"diamond hands\" OR \"paper hands\" lang:en min_faves:50",
    "\"trading psychology\" OR \"investor psychology\" OR \"behavioral finance\" OR \"risk management\" lang:en min_faves:20",
    # ===== AI — labs / models / agents =====
    "OpenAI OR Anthropic OR xAI OR \"GPT-5\" lang:en min_faves:50",
    "ChatGPT OR Claude OR Gemini OR Grok OR Llama lang:en min_faves:50",
    "\"AI agents\" OR \"agentic AI\" OR \"reasoning model\" OR AGI lang:en min_faves:30",
    # ===== AI — compute / chips / the money angle =====
    "Nvidia OR NVDA OR GPU OR \"AI datacenter\" OR \"AI capex\" lang:en min_faves:50",
    "Palantir OR \"AI stock\" OR \"AI bubble\" OR \"AI valuation\" lang:en min_faves:50",
    "\"AI startup\" OR \"AI funding\" OR \"AI layoffs\" OR \"AI jobs\" lang:en min_faves:30",
    # ===== MARKETS / MACRO =====
    "\"tech earnings\" OR \"S&P 500\" OR Nasdaq OR \"market crash\" lang:en min_faves:50",
    "Fed OR CPI OR \"rate cut\" OR \"interest rates\" OR macro lang:en min_faves:50",
    # ===== BITCOIN / CRYPTO (the AI-vs-BTC feud lane) =====
    "Bitcoin OR BTC OR \"BTC ETF\" OR crypto lang:en min_faves:100",
    "\"Bitcoin crash\" OR \"crypto crash\" OR \"crypto bubble\" OR \"BTC dump\" lang:en min_faves:30",
    # ===== FR tail (one query — replies match parent language) =====
    "IA OR ChatGPT OR Mistral OR \"intelligence artificielle\" lang:fr min_faves:25",
]

HOT_TAB_QUERIES = [
    # Breaking AI news EN (high min_faves = viral)
    "OpenAI OR Anthropic OR xAI OR \"GPT-5\" lang:en min_faves:500",
    "Nvidia OR \"AI datacenter\" OR \"AI capex\" lang:en min_faves:300",
    "\"AI agents\" OR \"reasoning model\" OR AGI lang:en min_faves:300",
    "Palantir OR \"AI stock\" OR \"AI bubble\" lang:en min_faves:300",
    # Breaking market emotion — panic is the therapist's house call
    "\"market crash\" OR \"sell off\" OR \"sell-off\" OR VIX lang:en min_faves:500",
    # Breaking BTC/crypto
    "Bitcoin OR \"BTC ETF\" OR crypto lang:en min_faves:300",
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

REPLY_PROMPT = """You are @TheAIShrink — THE AI THERAPIST. The calm, warm coach who ALSO happens
to be the sharpest analyst in the room: you read the 10-K, the S-1, the whitepaper before everyone
showed up. Your replies treat the timeline's anxiety with FACTS: name what the tweet is really
feeling (fear, FOMO, cope, euphoria), then hand out the precise number or mechanism that calms or
grounds it. You expose the hidden mechanism — gently. The reader exhales AND learns something.

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
4. INVESTOR PSYCHOLOGY (the home turf): loss aversion (~2x — losses hurt double),
   the behavior gap (average investor lags their own funds ~4%/yr by timing),
   disposition effect (selling winners, hugging losers), drawdown math
   (-50% needs +100% back), recency bias at tops, capitulation volume at bottoms,
   why "I'll sell when it gets back to even" is anchoring, not a plan.

SHARPNESS EXAMPLES (steal the structure, not the words):
- Tweet "Nvidia beats earnings": "datacenter is 88% of revenue now. nvidia is an AI infrastructure monopoly that also sells GPUs."
- Tweet "Bitcoin ETF inflows": "spot ETF took 11 years to approve and hit $50B AUM in 6 months. the SEC spent a decade protecting people from something that outperformed everything they were allowed to buy."
- Tweet "OpenAI raises again": "$157B valuation, $5B burn, $3.4B ARR. the math only works if AGI ships before the runway ends. no pressure."
- Tweet "AI will replace jobs": "it already replaced 40% of entry-level coding interviews. the people most worried about AI are the ones who've never tried to ship with it."
- Tweet "I'm done, selling everything": "the average investor lags their own funds by 4% a year, and it's all days like this one. close the app, not the position."
- Tweet "down 40% on my portfolio": "down 40% needs +67% to get back. down 100% of your sleep needs one night. fix the second number first."

VIRALITY MECHANICS (this is how a reply earns 100k views from a 1.3K account):
- First 6-8 words must STOP THE SCROLL — a number, a named actor, or a verdict.
  Never open with throat-clearing ("Honestly,", "I think", "Great point").
- SHORT WINS: aim 100-180 chars. One idea, one line-break max. A reply people
  screenshot is a reply the algorithm spreads.
- Be the FIRST sharp take, not the tenth funny one — say the thing the next
  500 commenters will wish they'd said.
- Quotable > clever: write the line someone repeats at dinner.

TONE — THERAPIST FIRST:
- The coach who read everything, says less than anyone, and CALMS hardest.
- Warm without being soft. Sharp without snark. Funny without setup —
  therapist-deadpan ("breathe", "let's sit with that number for a second").
- Matt Levine's brain with a therapist's bedside manner. Never doom, never
  dunk on scared people — validate the feeling, then give the grounding fact.
- EN: deadpan, lowercase ok, no punctuation theater.
- FR: accents impeccables, chaleureux, direct — le coach calme, pas le roaster.

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

GRAPHSEO_PROMPT = """You are @TheAIShrink replying to @Graphseo (Julien Flot).

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
    """Scan VIP friend accounts via search and reply to recent posts.

    Operator 2026-06-07: "reply to everything graphseo and thebtctherapist
    post" — the VIP lane is exactly those two (supersedes the 2026-06-06
    four-handle FR list: XFenaux/RodolpheSteffan/FinTales_ cost ~3 min of
    serialized Safari per cycle and converted to zero on the EN persona).
    Each handle is a cheap `from:` search, no profile visit; the 6h
    btc_blitz converges full coverage, this lane keeps pickup fast.
    """
    from .twitter_client import scrape_x_search, reply_to_tweet
    from .reply_bot import _tweet_age_minutes
    from .engagement_log import log_reply

    VIP_SCAN_HANDLES = [h.strip().lstrip("@") for h in os.environ.get(
        "VIP_SCAN_HANDLES", "Graphseo,TheBTCTherapist").split(",") if h.strip()]
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
                shipped = reply_to_tweet(url, reply)
                replied.add(url)
                if not shipped:
                    continue  # chokepoint skip — don't log a phantom reply
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

def _freshness_sort_key(tweet):
    """Order candidates fresh-and-rising first (2026-06-07 spec: 'front-load
    to fresh, fast-rising posts (posted < ~30-60 min ago and climbing)').

    Primary: age bucket (<=60 min, <=6h, older, unknown-age last — unknown
    parses as 9999 min via the snowflake helper). Secondary within a bucket:
    likes-per-hour velocity, highest first. First-hour replies are where the
    algo weight and the profile-visit conversion live; a 60-hour-old tweet
    must never consume the slot a 20-minute riser deserved.
    """
    age = _tweet_age_minutes(tweet.get("url", ""))
    if age <= 60:
        bucket = 0
    elif age <= 360:
        bucket = 1
    elif age < 9999:
        bucket = 2
    else:
        bucket = 3
    likes = tweet.get("likes") or 0
    velocity = likes / max(age, 1.0)
    return (bucket, -velocity, age)


def _reply_to_tweets(tweets, replied, source_name, source_detail="", remaining=None, en_counter=None):
    posted = 0
    per_author_count = {}
    is_feed = source_name.startswith(("FEED", "FOLLOWING"))
    tweets = sorted(tweets, key=_freshness_sort_key)
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
        # Disk re-check JUST before the expensive LLM call — another reply bot
        # (direct_reply / feed_sweeper / retweet_bot replyback) may have shipped
        # a reply to this URL since this cycle's `load_replied()` snapshot. The
        # chokepoint in twitter_client.reply_to_tweet is the final guard, but it
        # only fires AFTER ~17s of wasted ollama time per skip — 774 such skips
        # across 06-06+07 = ~3.6h of wasted compute/day. Reload is ~5ms.
        fresh_replied = load_replied()
        if url in fresh_replied:
            replied.add(url)
            continue
        log.info(f"[{source_name}] Replying to @{author}...")
        _reply_lang = "fr" if source_name.startswith("PROFILE") else ("en" if is_en_tweet else "fr")
        reply = _generate_single_reply(author, text, lang=_reply_lang)
        if not reply or reply is _LLM_RATE_LIMITED:
            continue
        from .pattern_tags import extract_pattern as _extract_pattern
        reply, _pattern_id = _extract_pattern(reply)
        reply = humanize(reply)
        # ⛔ NEVER premark the replied store here — the chokepoint in
        # twitter_client.reply_to_tweet loads it and refuses anything already
        # present. The 2026-04 "lock URL in BEFORE posting" premark made the
        # chokepoint (added 2026-06-05) refuse 100% of this path's replies
        # while log_reply kept recording phantoms. The chokepoint marks the
        # store itself right before the Safari write.
        replied.add(url)  # in-memory only: no same-cycle retry
        try:
            shipped = reply_to_tweet(url, reply)
        except Exception:
            traceback.print_exc()
            continue
        if not shipped:
            continue  # policy/content/dedup skip — nothing was posted
        log_reply(url, reply, action_type="reply", source=source_name, pattern_id=_pattern_id or "")
        posted += 1
        if _reply_lang == "en" and en_counter: en_counter[0] += 1
        # Spacing handled by action_guard (MIN_SECONDS_BETWEEN_REPLIES).
        # No extra sleep here — don't double-throttle.
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
        run_direct_reply_cycle()
        health.record_success("direct_reply")
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()
        health.record_failure("direct_reply")
