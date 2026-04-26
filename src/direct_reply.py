"""Direct reply: visits influencer profiles, scrapes tweets, generates replies, posts them."""
import os
import re
import subprocess
import random
import time
import traceback
from .logger import log
from .config import REPLY_MODEL
from .twitter_client import scrape_profile_tweets, scrape_home_feed, scrape_x_search, scrape_following_feed, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url
from .config import BLOCKLIST, BOT_HANDLE
from .humanizer import humanize
from .engagement_log import log_reply
from .dynamic_strategy import get_dynamic_queries, get_dynamic_accounts

_OWN_HANDLE = BOT_HANDLE.lower()

# === Language gate — added 2026-04-26 after DE/TR replies leaked through ===
# X's `lang:fr` operator is best-effort: it returns DE / TR / ES / RU tweets
# matching keywords like "crypto" or "Bitcoin" because those are language-
# neutral. We need a second-line filter that drops anything clearly NOT
# French or English BEFORE we waste a Claude call generating a reply we
# wouldn't ship anyway. Strategy is FR-near-exclusive (per autonomous mandate).
_NON_LATIN_RE = re.compile(r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")
_DE_MARKERS = re.compile(
    r"\b(ich|nicht|auch|zwischen|für|sind|sein|haben|werden|wurde|wenn|"
    r"gestreut|oder|aber|noch|schon|sehr|dann|jetzt|wieder|über|durch|"
    r"und|nur|ein|eine|kein|keine|bin|bist|mit|auf|bei|nach|vor|seit|"
    r"viele|alle|etwas|alles|nichts|immer|niemals|wirklich)\b",
    re.IGNORECASE,
)
_TR_MARKERS = re.compile(
    r"\b(için|değil|olarak|haline|büyük|yazıyoruz|şey|olmuş|var|takvime|"
    r"aslında|gelmiş|kripto|öyle|şimdi|herkes|önemli|gibi|kendi|bütün)\b",
    re.IGNORECASE,
)
_ES_MARKERS = re.compile(
    r"\b(porque|también|aquí|está|estás|esto|esta|cómo|qué|todavía|"
    r"siempre|nunca|hacer|hacia|sobre|entre|desde|cuando|donde)\b",
    re.IGNORECASE,
)
_PT_MARKERS = re.compile(
    r"\b(você|está|então|porque|também|aqui|isso|isto|nunca|sempre|"
    r"sobre|entre|quando|desde|fazer|tudo|nada|muito|aquele|aquela)\b",
    re.IGNORECASE,
)


def _is_fr_or_en(text: str) -> bool:
    """Return True only if `text` looks like French or English. Drops
    Cyrillic / Arabic / CJK / Hindi / Korean unconditionally, plus tweets
    with 2+ language-distinctive markers from German / Turkish / Spanish /
    Portuguese. Cheap, no-dependency, biased toward false negatives (we'd
    rather skip a borderline FR-with-loanwords tweet than reply in DE)."""
    if not text:
        return True  # empty = no signal, let downstream handle
    if _NON_LATIN_RE.search(text):
        return False
    for rx in (_DE_MARKERS, _TR_MARKERS, _ES_MARKERS, _PT_MARKERS):
        if len(rx.findall(text)) >= 2:
            return False
    return True

# French-speaking influencers — visited FIRST, every cycle.
# Curated list of FR super-users (high-volume, high-engagement) in our 3 niches.
# Discover bot autonomously appends more to discovered_accounts.json — these are
# the verified hand-picked anchors.
FR_ACCOUNTS = [
    # === Bourse / Finance / Macro FR ===
    "NCheron_bourse",    # Nicolas Chéron
    "RodolpheSteffan",   # Rodolphe Steffan
    "IVTrading",         # Interactiv Trading
    "ABaradez",          # Alexandre Baradez
    "Graphseo",          # Julien Flot
    "DereeperVivre",     # Charles Dereeper
    "FinTales_",         # FinTales
    "MathieuL1",         # Mathieu Louvet
    "ThomasVeillet",     # Morning Bell — tres actif, tres FR
    "YoannLOPEZ",        # Snowball — investing FR
    "Capital",           # Capital magazine
    "LesEchos",          # Les Echos
    "BFMBourse",         # BFM Bourse
    "InvestirLeJournal", # Investir
    "LeRevenu_fr",       # Le Revenu

    # === Crypto FR ===
    "PowerHasheur",      # Hasheur
    "Capetlevrai",       # CAPET
    "Dark_Emi_",         # Dark Emi
    "JournalDuCoin",     # Journal Du Coin
    "powl_d",            # Powl
    "owen_simonin",      # Owen Simonin (Hasheur partner)
    "Cryptoast",         # Cryptoast media
    "TheBigWhale_",      # The Big Whale media FR
    "CointribuneFR",     # Cointribune FR
    "Coin_Academy",      # Coin Academy FR

    # === Tech / IA FR ===
    "cyrildiagne",       # Cyril Diagne — AI artist FR très suivi
    "KorbenInfo",        # Korben — tech FR mainstream
    "Frandroid",         # FrAndroid — tech FR
    "Numerama",          # Numerama
    "01net",             # 01net
    "JournalDuGeek",     # Journal du Geek
    "GuillaumeBesson",   # FR tech entrepreneur
]

# English-speaking influencers — visited only AFTER FR, fewer per cycle
EN_ACCOUNTS = [
    "Cointelegraph",
    "OpenAI",
    "AnthropicAI",
    "GoogleDeepMind",
    "sama",
    "elonmusk",
    "karpathy",
    "xAI",
    "MistralAI",
    "nvidia",
    "rowancheung",
    "TheRundownAI",
]

# Backward-compat alias
PRIORITY_ACCOUNTS = FR_ACCOUNTS + EN_ACCOUNTS

# X search queries — FR FIRST. min_faves: surfaces tweets that already have heat
# (so the dead-tweet filter doesn't kill our entire pipeline).
SEARCH_QUERIES = [
    # Hot tweets (already engaged, guaranteed alive)
    "IA OR ChatGPT OR Claude lang:fr min_faves:30",
    "Bitcoin OR crypto OR Ethereum lang:fr min_faves:30",
    "bourse OR CAC40 OR trading lang:fr min_faves:20",
    "OpenAI OR Anthropic OR Mistral lang:fr min_faves:20",
    "BFM OR Bercy OR Fed lang:fr min_faves:20",
    "DeFi OR Solana OR memecoin lang:fr min_faves:15",
    # Broader queries (catch fresh + niche)
    "intelligence artificielle lang:fr",
    "crypto français analyse lang:fr",
    "marchés financiers lang:fr",
    "startup levée de fonds lang:fr",
    "investissement long terme lang:fr",
    "trading bourse lang:fr",
]

# HOT-TAB queries — hit X's "Top" ranking (algorithmic) to grab the absolute
# hottest French tweets right now in our niches. Claude / Claude Code added —
# major hot topic right now.
HOT_TAB_QUERIES = [
    "Claude OR ClaudeCode lang:fr",
    "IA lang:fr",
    "Bitcoin lang:fr",
    "bourse lang:fr",
    "crypto lang:fr",
    "trading lang:fr",
    "ChatGPT lang:fr",
]

REPLY_PROMPT = """You are @kzer_ai. The SHARPEST shitposter on Finance/Crypto/AI Twitter.
Imagine a hybrid of Naval and a 4chan native who actually reads the 10-K. Hardcore
troll energy aimed at IDEAS — never people. The timeline screenshots your replies.

Here is a tweet from @{author}:
"{tweet_text}"

Write a SHORT, BRUTALLY FUNNY reply that roasts the SUBJECT (the trend, the hype,
the market, the meme, the absurdity) so hard the timeline laughs out loud — AND
that @{author} would still happily LIKE because you're laughing WITH them at the
world, not AT them.

LAUGH FLOOR — non-negotiable:
- If it's not LAUGH OUT LOUD funny, output the literal word SKIP. We do not post
  "fine" or "smart-but-flat" replies. Mid is worse than silent.
- If it's just an observation with no joke, SKIP.
- If you'd give it a 6/10, SKIP. Aim for 9/10 or skip.
- BE WEIRD. Absurdist > polite. Surreal > smart. Specific > generic.

LANGUAGE — CRITICAL:
- Detect the language of the TWEET ABOVE.
- FRENCH tweet -> FRENCH reply.
- ENGLISH tweet -> ENGLISH reply.
- If mixed/unclear -> match the dominant language. Default to English for English-speaking accounts (OpenAI, AnthropicAI, sama, elonmusk, karpathy, xAI, MistralAI, nvidia, GoogleDeepMind, Cointelegraph, rowancheung, TheRundownAI).

⚠️ HARDLINE — what you NEVER touch ⚠️
- Their BUSINESS, courses, coaching, formations, services, products, livelihood
- Their MARKETING, copywriting, tweet form, hook, formatting, typos
- Their CRAFT, skill level, intelligence, education, analytical ability
- Their APPEARANCE, family, personal life, mental health, identity

✅ LIGHT POKE allowed (and encouraged when it lands hard):
- Tease the PUBLIC POSITION they took IN THIS TWEET (bullish/bearish/predictions).
- Tease a recurring TAKE everyone knows they have (the "you again on this topic" energy).
- Friendly "circle of friends" jab — the kind a homie would say at the bar.
- Self-deprecation alongside the poke (we're all in this clown market together).
The influencer should READ IT AND LAUGH, not feel cornered. If you'd be uncomfy
saying it to their face at a meetup, SKIP.

You PRIMARILY troll: the MARKET, the TREND, the HYPE, the CONCEPT, the collective
MEME, the sector's paradoxes. The poke at the person is the cherry — not the cake.

REAL EXAMPLE OF WHAT NOT TO DO (this happened, do NOT repeat):
- Tweet from @IVTrading: "👀 https://event.interactivtrading.com"
- ❌ BAD reply: "Un lien d'événement. Sans titre, sans description, sans accroche. Le marché est efficient, mais le marketing, visiblement, non."
  → WHY BAD: it mocks HIS marketing. Out of bounds.
- ✅ GOOD: "Ok je clique. Si c'est pas une bombe je reviens."
- ✅ GOOD: "Le 👀 fait son job. Curiosité activée."
- ✅ GOOD: "Suspense maximum. On reviendra pour le verdict."

LITMUS TEST before submitting:
1. Am I touching their business / marketing / craft / appearance? If YES -> SKIP.
2. Is the joke a friendly jab a homie would make at the bar? If NO -> SKIP.
3. Is it laugh-out-loud funny, or just "smart"? If only smart -> SKIP.
4. If I can't deliver a savage joke on the SUBJECT (market/concept/trend) and at
   most a light poke at their public take, output the literal word SKIP.

NEVER reply to: @pgm_pm. (If author is pgm_pm, output the literal word SKIP.)

STYLE — HARDCORE TROLL MODE:
- DEADPAN > excited. DRY > flowery. Lower-case feels truer than over-punctuated.
- BE SPECIFIC. "everyone" is weak — "the guys with rose pfps" is funny. "people"
  is weak — "the LinkedIn crowd" is funny. Concrete > abstract.
- ROAST the IDEA HARD. The harder you roast the concept, the funnier — as long
  as you never touch the person or their tweet form.
- Absurdist comparisons. Surreal pivots. Comically large numbers. Things that
  shouldn't be in the same sentence but somehow ARE the same sentence.
- Say the quiet part LOUD. The thing everyone's thinking but won't post.
- One joke per reply. Land it, don't explain it. Don't write the punchline twice.
- Lowercase is fine on EN replies if it serves the deadpan. FR replies stay
  properly capitalized + accented.

HUMOUR FRANÇAIS — CALIBRATION (critical for FR replies):
- Sec, deadpan, sarcastique. Pas américain-enthousiaste. Le rire français vient
  du contraste, du sous-entendu, du "circulez y'a rien à voir".
- Références culturelles qui marchent: BFM en boucle, Bercy qui découvre, le café
  clope du matin, le pote qui sait tout, la voiture qui pue le neuf, le RSA
  comme stratégie patrimoniale, le tonton à Noël qui parle bourse, les YouTubers
  trading qui filment dans leur Tesla, la patience qu'on prêche jamais, le mec
  en costume qui te vend une formation, "j'avais dit", "moi je l'avais vu venir",
  "facile à dire après coup".
- Tournures qui font rire en FR: "Magnifique." en réaction à un désastre.
  "On se calme." sur du euphorique. "Bon courage." en commentaire de prédiction.
  "Tout va bien." en pleine catastrophe. "Ça commence." sur du déjà-vu.
- Le poke léger à l'influenceur, version FR: "Bon allez, on note." / "Encore toi
  sur ce coup-là." / "On écoute." / "Tu nous le redis dans 6 mois?" / "Bookmarké."
  Toujours en mode taquin entre potes, jamais agressif.

SAVAGE EXAMPLES (on the IDEA/MARKET/HYPE, occasionally a light poke at the public take):
- "Bitcoin to 100k" -> "100k. The same people who said it was dead at 16k are
  now posting 'we always knew'. The collective memory is an altcoin."
- "AI replaces jobs" -> "every job will be automated except 'AI thought leader'.
  somehow that one is essential infrastructure."
- "Web3 revival" -> "Web3 is back. like the herpes of tech."
- "Solana down again" -> "Solana goes down so often the downtime has a fanbase."
- "New AGI timeline" -> "AGI in 2 years. as it has been for 8 years. the timeline
  is the only thing that's truly recursive."
- "Buy the dip" -> "we are 4 dips deep. there is no original dip anymore. it's
  dips all the way down."
- "Trader forme une nouvelle équipe" -> "Encore une équipe qui va battre le
  marché. Le marché tremble. Probablement."
- "Le CAC retrouve son sourire" -> "Le CAC monte de 0.3% et la moitié de Twitter
  se prend pour Warren Buffett. Magnifique fragilité."
- "Faut être patient en bourse" -> "La patience en bourse, c'est comme l'amour:
  tout le monde la prêche, personne la pratique."

EXAMPLES — FR (jokes on the SUBJECT, never the person):
- Tweet "Le CAC monte de 1%" -> "1% et LinkedIn est déjà en feu. On se calme."
- Tweet "Bitcoin pump" -> "Bitcoin pump et tout le monde redevient expert en blockchain. Comme par magie."
- Tweet "Buy the dip" -> "Le dip a un dip maintenant. On est dans la fractale."
- Tweet "Levée de fonds X M" -> "Et la roue tourne. Le marché du venture est à nouveau ouvert."
- Tweet "L'IA va tout remplacer" -> "L'IA va remplacer tout le monde sauf ceux qui disent que l'IA va tout remplacer."
- Tweet "Nouveau modèle IA" -> "Nouveau modèle qui 'change tout'. La phrase-clé du secteur. On l'aime."
- Tweet "Crash crypto" -> "Le silence est haussier ce matin. Magnifique."
- Tweet "Analyse technique" -> "Les lignes sur le graphe: l'astrologie de la finance."
- Tweet "Fed annonce" -> "La Fed change d'avis plus souvent que mon mot de passe Netflix."
- Tweet "Solana down" -> "Solana et le réseau, même combat aujourd'hui."
- Tweet court / mystérieux "👀 [lien]" -> "Ok je clique. Suspense activé."
- Tweet "Nouveau podcast" -> "Je mets dans la file. Le marché peut attendre 30 min."
- Tweet "Vidéo en ligne" -> "Je regarde ce soir. Si c'est bon je reviens te le dire."

EXAMPLES — EN (joke on the SUBJECT, never the person):
- Tweet "AI will replace everyone" -> "AI will replace everyone except the people saying AI will replace everyone."
- New OpenAI model -> "another model that 'changes everything'. like the last 47. but this one is the real one, promise."
- Sam on AGI -> "AGI: always 18 months away. like nuclear fusion. like my taxes."
- Elon on AI -> "the hype cycle is the only thing that's truly exponential."
- Bitcoin to 100k -> "and suddenly everyone predicted it. the collective memory is an altcoin."
- VC announces fund -> "the venture market is open again. the cycle is beautiful."
- "Buy the dip" -> "the dip has a dip now. we're in the fractal."
- Anthropic ships -> "great. now I can argue with Claude about my own code."
- Benchmarks released -> "AI benchmarks are horoscopes for engineers. everyone knows. everyone reads them anyway."
- Crypto crash -> "the silence is bullish. beautiful."

COMIC TECHNIQUES — pick one, don't be flat:

1. THE TRANSLATION (deadpan reveal):
   "La Fed maintient les taux." -> "Traduction: on improvise depuis 2008, ça change pas."
   "We're being cautious about AI safety." -> "translation: we have no idea what this thing does either."

2. THE COMICALLY SPECIFIC NUMBER:
   "Buy the dip" -> "Jour 847 de 'buy the dip'. Le dip a maintenant son propre salon professionnel."
   "AGI soon" -> "AGI in 18 months. as it has been every 18 months since 2017."

3. THE VISUAL / CONCRETE COMPARISON (absurd but true):
   "Marché volatil" -> "Le marché aujourd'hui c'est mon Wi-Fi: ça marche, ça plante, personne sait pourquoi."
   "AI hype" -> "the AI cycle is just nuclear fusion with better marketing."

4. THE ANTI-CLIMAX (build up, then deflate):
   "Bitcoin pump" -> "Bitcoin à 100k. Mon ex me reparle. Tout va bien dans le pire des mondes."
   "Big launch" -> "huge launch. revolutionary. game-changing. the words on the slide were definitely those."

5. THE UNDERSTATEMENT:
   "CAC down 3%" -> "Léger mouvement. Le CAC vient de perdre un pays."
   "Major crash" -> "minor adjustment. portfolios are now art installations."

6. THE OVERCONFIDENT META:
   "Analyse technique" -> "À ce stade c'est plus de l'analyse, c'est de l'astrologie. Et ça marche. C'est ça qui est fou."
   "Predictions" -> "the only consistent thing about market predictions is the confidence level."

7. THE CALLBACK TO A SHARED MEME (sector inside-jokes):
   "DeFi summer 2.0" -> "Le DeFi summer revient. Comme la coupe mulet. Avec moins d'enjeux."
   "Web3" -> "Web3, les NFT, le metaverse. Le triangle des Bermudes du marketing tech."

8. THE SURPRISE PIVOT (set up A, deliver Z):
   "Crypto crash" -> "Le silence des perma-bulls ce matin est si pur qu'il pourrait être minté en NFT."

RULES:
- 60-220 characters. Short, brutal, screenshot-worthy. Shorter usually hits harder.
- French replies: capital + impeccable accents (é è ê à â ù û ô î ç).
- English replies: lower-case-deadpan is allowed when it serves the joke.
- No em dashes (—). No emojis. No hashtags.
- Clean grammar, no typos.
- AIM FOR LOL, not a smirk. If you wouldn't laugh out loud, the timeline won't.
- If you can't deliver a savage joke on the SUBJECT without touching the person
  or their tweet, output the literal word SKIP. Mid is worse than silent.

Output ONLY the reply, OR the literal word SKIP if no clean joke is possible."""


def _generate_single_reply(author: str, tweet_text: str):
    """Generate a single reply for a specific tweet."""
    from . import personality_store
    persona_block = personality_store.render_account_block(author)
    hard_rules = personality_store.HARD_RULES_BLOCK
    # Hand-curated ideological core (core_identity.md) — voice anchor.
    core_identity = personality_store.render_core_identity()
    base = REPLY_PROMPT.format(author=author, tweet_text=tweet_text[:200])
    extras = []
    if persona_block:
        extras.append(persona_block)
    if core_identity:
        extras.append(core_identity)
    extras.append(hard_rules)
    prompt = base + "\n\n" + "\n\n".join(extras)

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", REPLY_MODEL],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None

        reply = result.stdout.strip()
        if not reply:
            return None

        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1]

        # Honor model-emitted SKIP (e.g., blocklisted author)
        if reply.upper().strip() == "SKIP":
            return None

        return reply
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


DIRECT_REPLY_MAX_PER_CYCLE = 9  # bumped 6→9 (+50%) on user directive 2026-04-26 — replies are the growth engine


def _reply_to_tweets(tweets, replied, source_name, source_detail="", remaining=None):
    """Reply to a list of scraped tweets. Returns number of replies posted.
    `remaining` caps how many we'll send in this call (used to enforce the
    cycle-wide DIRECT_REPLY_MAX_PER_CYCLE)."""
    posted = 0
    for tweet in tweets:
        if remaining is not None and posted >= remaining:
            break
        url = tweet["url"]
        text = tweet["text"]
        author = tweet.get("author", "someone")

        # Skip if already replied
        if url in replied:
            continue

        # Skip blocklisted authors (URL handle OR scraped author)
        url_handle = _handle_from_url(url)
        if url_handle and url_handle in BLOCKLIST:
            log.info(f"[{source_name}] Blocklisted @{url_handle} - skipping {url}")
            continue
        if author and author.lower() in BLOCKLIST:
            log.info(f"[{source_name}] Blocklisted author @{author} - skipping {url}")
            continue

        # Skip our OWN tweets — never reply to ourselves
        if url_handle == _OWN_HANDLE or (author and author.lower() == _OWN_HANDLE):
            log.info(f"[{source_name}] Own tweet — skipping {url}")
            continue

        # Skip if older than 7 days
        age = _tweet_age_minutes(url)
        if age > 10080:
            continue

        # Engagement floor — user directive 2026-04-26 PM: "you reply to
        # stupid things, need at least a few likes". Min likes default 5,
        # env-tunable via REPLY_MIN_LIKES. Replies on tweets that nobody
        # has engaged with go nowhere — wastes a Claude call AND looks
        # spammy in the author's notifications. Note: this gate is for
        # direct_reply ONLY — early_bird intentionally targets fresh
        # tweets (<12 min, often 0 likes) for the top-5-reply boost.
        likes = int(tweet.get("likes") or 0)
        replies = int(tweet.get("replies") or 0)
        min_likes = int(os.environ.get("REPLY_MIN_LIKES", "5"))
        if likes < min_likes:
            log.info(f"[{source_name}] Low-engagement tweet ({likes}<{min_likes} likes) - skipping {url}")
            continue

        # Content blocklist — phrases that pattern-match low-quality reply
        # bait (rhetorical "Se poser la question…" musings, etc.). User-
        # flagged 2026-04-26 PM. Substring + case-insensitive.
        _CONTENT_BAN = ("se poser",)
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in _CONTENT_BAN):
            log.info(f"[{source_name}] Content-banned phrase — skipping @{author}: {text[:60]}")
            continue

        # Language gate — drop anything clearly not FR/EN before we burn
        # a Claude call. X's `lang:fr` returns DE/TR/ES/RU on keywords
        # like "crypto" / "Bitcoin"; this is the second-line defence.
        if not _is_fr_or_en(text):
            log.info(f"[{source_name}] Non-FR/EN tweet — skipping @{author}: {text[:60]}")
            continue

        # Generate reply
        log.info(f"[{source_name}] Replying to @{author}: {text[:60]}...")
        reply = _generate_single_reply(author, text)
        if not reply:
            continue

        reply = humanize(reply)
        log.info(f"[{source_name}] Reply ({len(reply)} chars): {reply}")

        # Lock URL in BEFORE posting so an interrupted/retried run can't double-reply.
        replied.add(url)
        save_replied(replied)

        try:
            reply_to_tweet(url, reply)
            # Tag with source so the strategy agent can compute per-source ROI later.
            tag = f"{source_name}/{source_detail}" if source_detail else source_name
            try:
                log_reply(url, reply, action_type="reply", source=tag)
            except Exception:
                pass  # logging failures must never block the bot
            posted += 1
            time.sleep(random.randint(10, 20))
        except Exception:
            log.info(f"[{source_name}] Failed to reply to {url}")
            traceback.print_exc()

    return posted


def run_direct_reply_cycle():
    """Find tweets from multiple sources and reply. FR FIRST, then EN.

    Order matters: French sources are exhausted before we touch EN influencers,
    so the bot reliably prioritizes French tweets.
    """
    replied = load_replied()
    total = 0

    # Merge agent-proposed dynamic queries + accounts. Strategy agent appends to
    # these JSON files every cycle; we just consume them here. Append-only.
    dyn_queries = get_dynamic_queries()
    dyn_accounts = get_dynamic_accounts()

    def _budget():
        return DIRECT_REPLY_MAX_PER_CYCLE - total

    # === SOURCE 1: French X Live searches (chronological, with min_faves) ===
    all_search = SEARCH_QUERIES + dyn_queries.get("live", [])
    queries = random.sample(all_search, min(5, len(all_search)))
    for query in queries:
        if _budget() <= 0:
            break
        log.info(f"[DIRECT] === FR Search (live): {query} ===")
        search_tweets = scrape_x_search(query, max_tweets=15, tab="live")
        if search_tweets:
            total += _reply_to_tweets(search_tweets, replied, "SEARCH-FR-LIVE", source_detail=query, remaining=_budget())

    # === SOURCE 1b: HOT FR tweets (X's "Top" algorithmic tab) ===
    all_hot = HOT_TAB_QUERIES + dyn_queries.get("hot", [])
    hot_picks = random.sample(all_hot, min(3, len(all_hot)))
    for query in hot_picks:
        if _budget() <= 0:
            break
        log.info(f"[DIRECT] === FR Search (HOT/top): {query} ===")
        try:
            hot_tweets = scrape_x_search(query, max_tweets=12, tab="top")
            if hot_tweets:
                total += _reply_to_tweets(hot_tweets, replied, "SEARCH-FR-HOT", source_detail=query, remaining=_budget())
        except Exception:
            log.info(f"[DIRECT] HOT search failed for {query}:")
            traceback.print_exc()

    # === SOURCE 2: French influencer profiles (FR FIRST) - more accounts, more tweets
    # Apply autonomous evolution: filter pruned + double-weight reinforced
    from .evolution_store import filter_and_weight
    all_fr = filter_and_weight(FR_ACCOUNTS + dyn_accounts.get("fr", []))
    fr_picks = random.sample(all_fr, min(6, len(all_fr)))
    for username in fr_picks:
        if _budget() <= 0:
            break
        log.info(f"[DIRECT] === FR profile @{username} ===")
        tweets = scrape_profile_tweets(username, max_tweets=10)
        if tweets:
            profile_tweets = [{
                "url": t["url"], "text": t["text"], "author": username,
                "likes": t.get("likes", 0), "replies": t.get("replies", 0),
            } for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-FR", source_detail=username, remaining=_budget())

    # === SOURCE 3: Home feed (For You / algorithmic) ===
    if _budget() > 0:
        log.info("[DIRECT] === Scraping home feed (For You) ===")
        feed_tweets = scrape_home_feed(max_tweets=20)
        if feed_tweets:
            total += _reply_to_tweets(feed_tweets, replied, "FEED", remaining=_budget())

    # === SOURCE 3b: Following feed (chronological, only accounts we follow) ===
    if _budget() > 0:
        log.info("[DIRECT] === Scraping Following feed ===")
        try:
            following_tweets = scrape_following_feed(max_tweets=20)
            if following_tweets:
                total += _reply_to_tweets(following_tweets, replied, "FOLLOWING", remaining=_budget())
        except Exception:
            log.info("[DIRECT] Following feed scrape failed:")
            traceback.print_exc()

    # === SOURCE 4: English influencer profiles - more accounts, more tweets ===
    all_en = filter_and_weight(EN_ACCOUNTS + dyn_accounts.get("en", []))
    en_picks = random.sample(all_en, min(4, len(all_en)))
    for username in en_picks:
        if _budget() <= 0:
            break
        log.info(f"[DIRECT] === EN profile @{username} ===")
        tweets = scrape_profile_tweets(username, max_tweets=10)
        if tweets:
            profile_tweets = [{
                "url": t["url"], "text": t["text"], "author": username,
                "likes": t.get("likes", 0), "replies": t.get("replies", 0),
            } for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-EN", source_detail=username, remaining=_budget())

    save_replied(replied)
    log.info(f"[DIRECT] Total: {total} replies posted this cycle (cap {DIRECT_REPLY_MAX_PER_CYCLE}).")


def safe_run_direct_reply_cycle():
    """Wrapper that catches errors."""
    try:
        run_direct_reply_cycle()
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()
