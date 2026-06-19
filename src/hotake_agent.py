"""Hot take agent: sharp quant-analyst memes on AI + Space + Investment.

Goal: makes people LAUGH OUT LOUD and screenshot the tweet.
- MEME energy: short, punchy, share-worthy
- SMART + SHARP: a real observation underneath
- PHILOSOPHICAL: the "huh, that's actually deep" beat
- FUNNY: laugh-out-loud, not just nod
- Troll the IDEAS, the TRENDS, the SYSTEM. NEVER mock the audience or specific people.
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from .config import HOTAKE_MODEL, PROFILE_LLM_PROVIDER
from .logger import log
from .performance import get_learnings_for_prompt
from .history import get_recent_tweets
from .topic_dedup import extract_recent_topics
from .llm_client import run_llm, unwrap_text


# URL date sniffer — many news outlets stamp /YYYY/MM/DD/ in their article
# paths (CoinDesk, CNBC, NYT, Reuters, etc.). When present, this is a
# reliable signal for publication date and we can hard-enforce the 48h
# freshness rule that the LLM keeps bending. Returns the parsed datetime
# or None if no date is found in the URL.
# Common URL date encodings:
#   /YYYY/MM/DD/       — most newsrooms (Reuters, NYT, WaPo, fool.com…)
#   /YYYY-MM-DD/       — Bloomberg (e.g. /news/articles/2026-04-22/…)
#   /YYYY/MM-DD/       — rare hybrid
# Match any of them with a single regex so the freshness gate doesn't
# leak. Tested against bloomberg.com, reuters.com, fool.com, siliconangle.
_URL_DATE_RE = re.compile(
    r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:[/-]|$)"
)


def _url_publication_date(url: str) -> Optional[datetime]:
    m = _URL_DATE_RE.search(url or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# Content-farm rejectlist (per CLAUDE.md): the prompt tells the agent to
# avoid these, but the LLM keeps slipping them through (saw cryptonews.net
# land in a hot take on 2026-04-27). This is the deterministic Python-side
# gate: any URL hosted on these domains → SKIP, no exceptions.
_REJECTED_SOURCE_DOMAINS = (
    "breakingviews.com",
    "crypto.news",
    "cryptonews.net",
    "cryptopotato.com",
    "beincrypto.com",
    "u.today",
    "bitcoinist.com",
    "ambcrypto.com",
    # 2026-05-23 (user mandate "remove via.news from pool"): content farms
    # publishing AI-generated / clickbait articles with factually wrong
    # claims. via.news said "Nvidia +20%" when Nvidia actually crashed.
    "via.news",
    "cryptoslate.com",
    "observer.com",
    "decrypt.co",  # often AI-rewritten, low signal
    "watcher.guru",
    "watcherguru.com",
    "thedefiant.io",
    "dailycoin.com",
    "cryptobriefing.com",
    "newsbtc.com",
    "thecryptobasic.com",
    "fxstreet.com",
    "benzinga.com",
    "seekingalpha.com",  # often paywall-blocked + clickbait
    "thestreet.com",
    "tradingview.com",
    "marketbeat.com",
    "247wallst.com",
    "investorplace.com",
    "tipranks.com",
    "zerohedge.com",
    "kitco.com",
    "ainvest.com",
    "stocknews.com",
    "indiatimes.com",
)


def _is_rejected_source(url: str) -> bool:
    """True if `url` is hosted on a content-farm rejected by CLAUDE.md."""
    if not url:
        return False
    u = url.lower()
    for dom in _REJECTED_SOURCE_DOMAINS:
        if f"//{dom}/" in u or f"//www.{dom}/" in u or f".{dom}/" in u:
            return True
    return False


def _build_news_pool_section(sig_path: Optional[str] = None) -> str:
    """Render the 'POOL D'ARTICLES RÉELS' prompt block from external_signal.json.

    Pre-filters against the content-farm rejectlist: the chokepoint
    (`_is_rejected_source`) deterministically refuses these URLs post-
    generation, so showing them to the LLM just burns a Sonnet call. Same
    family as PR #55 (spacing precheck) — when a rule is enforced
    deterministically downstream, lift it upstream of the expensive call.
    Was firing ~15x in the recent log window (~7/30 pool items = decrypt.co).
    """
    import json as _json
    import os as _os
    if sig_path is None:
        sig_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "external_signal.json")
    try:
        with open(sig_path) as f:
            sig = _json.load(f)
    except (OSError, _json.JSONDecodeError, ValueError):
        return ""
    items = [
        it for it in (sig.get("items") or [])
        if it.get("url")
        and "x.com" not in it.get("url", "")
        and "twitter.com" not in it.get("url", "")
        and not _is_rejected_source(it.get("url", ""))
    ]
    if not items:
        return ""
    lines = "\n".join(
        f"- {it['url']} | {it.get('title','')[:80]}"
        for it in items[:15]
    )
    return (
        "\n\n==================================================\n"
        "POOL D'ARTICLES RÉELS (fraîchement scrappés — utilise UN de ces liens)\n"
        "==================================================\n"
        "NE GÉNÈRE PAS D'URL TOI-MÊME. Choisis UNIQUEMENT dans cette liste.\n"
        "Si aucun article ne convient → réponds SKIP.\n\n"
        + lines
    )


# Backwards-compat alias for any external code that imported the underscore name.
_extract_recent_topics = extract_recent_topics


# Module-level side-channels for the most-recent hot take output.
#  - _last_image_topic: Wikipedia slug for fallback visual.
#  - _last_pattern: comedy-bucket id for the bandit loop.
#  - _last_source_url: article URL pasted in the tweet body. When set, X
#    renders a native link-card and bot.py SKIPS attaching an image (image
#    + URL competes with the card).
_last_image_topic: Optional[str] = None
_last_pattern: Optional[str] = None
_last_source_url: Optional[str] = None


def last_image_topic() -> Optional[str]:
    """Return the [IMAGE: slug] topic from the most recent generate_hotake()
    call, or None if the model emitted SKIP or omitted the line."""
    return _last_image_topic


def last_pattern() -> Optional[str]:
    """Return the [PATTERN: id] tag from the most recent generate_hotake()
    output. Used by bot.py to populate engagement_log's pattern_id column
    (drives the per-pattern ROI signal the evolution agent learns from)."""
    return _last_pattern


def last_source_url() -> Optional[str]:
    """Return the article URL the agent embedded in the hot take body, or
    None if no URL was found. When set, X renders a native link-card from
    the URL — bot.py should NOT attach a separate image."""
    return _last_source_url


_HOTAKE_URL_RE = re.compile(r"https?://\S+")


def _extract_image_topic(text: str):
    """Pull `[IMAGE: slug]` off the bottom of a hot take.
    Returns (cleaned_tweet, slug_or_None). slug=None if SKIP or missing."""
    m = re.search(r"\[\s*IMAGE\s*:\s*([^\]]+?)\s*\]", text, flags=re.IGNORECASE)
    if not m:
        return text, None
    slug = m.group(1).strip()
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    if slug.upper() == "SKIP" or not slug:
        return cleaned, None
    return cleaned, slug

HOTAKE_PROMPT = """{lang_directive}

🎯 GOAL: drop ONE sharp, easy-to-understand AI take or explanation. 1-2
sentences. The post that makes someone go "oh, THAT'S what matters here."
Confident, optimistic, easy language. If it's not genuinely sharp, SKIP.

📈 PLACE IN THE MIX: the quick-take surface. Lane ONLY: artificial
intelligence — labs & models, AI agents & tools, AI research/benchmarks, AGI,
AI startups, AI compute, embodied AI.

FORMATS TO ROTATE (this is what goes viral):
- "Everyone is talking about X. Nobody is talking about Y. Y matters more."
- "Most people think A. What's actually happening is B."
- "The biggest AI story today isn't X. It's Y."
- "In 5 years this will look obvious. Today almost nobody sees it."
- A plain-English explanation: "What X actually means: ..."
- A prediction: "Here's where this goes next: ..."

🔥 THE SHAPE:
- 1-2 sentences / short lines. ~60-220 chars. Prefer under 140.
- Hook in the first 6 words. Make AI make sense.
- Easy language. No jargon, no buzzwords unless explained.
- NO hashtags. NO emojis. No em dashes. No links. Never corporate, never cringe.
- React to a real AI story or explain a real AI concept. Never invent facts.

🎯 GREAT EXAMPLES (the feel):
- "Anthropic just found another way to make AI smarter. The trick is in how it
  checks its own work."
- "Most people still don't get what's coming with AI agents. They don't answer
  questions. They do the task."
- "Everyone's hyping the new model's score. The real story is it costs a tenth
  as much to run."

🤖 TEST: would a smart, busy person understand it instantly AND learn something
or want to argue? If not, rewrite or SKIP.

{dedup_section}

{performance_section}"""

# Old bloated prompt kept here as _ARCHIVE_OLD_HOTAKE_PROMPT for reference.
# Replaced 2026-04-29 PM (user: "its horrible! make it like a real influencer
# that brings news") with the focused bombe-only prompt above.
_ARCHIVE_OLD_HOTAKE_PROMPT = """Tu es @AIBossGPT. Le meilleur compte memes/observations sur l'IA, la crypto et la bourse. Mi-philosophe, mi-troll. Toujours drôle.

═══════════════════════════════════════════════════════════
🤣 LE TEST UNIQUE — POSE-TOI ÇA AVANT DE POSTER (User 2026-04-28)
═══════════════════════════════════════════════════════════
"EST-CE QU'UN HUMAIN VA RIRE FORT EN LISANT ÇA ?"
- OUI → poste.
- NON → SKIP. Pas de "c'est philosophique". Pas de "observation pertinente".
  Si ça fait pas RIRE, ça fait perdre la mission 10k followers.

LA RECETTE QUI A MARCHÉ (user verbatim 2026-04-28: "so funny with the RER B,
the sarcastic comment on administration etc... so relatable!!!! get more
french references and make them laugh dude!!! While being the sharpest and
smartest in the room"):
- FRENCHITUDE RELATABLE: RER B / Bercy / "et les charges?" / le syndicat qui
  tamponne / l'URSSAF / Pôle Emploi / la Banque Postale qui ferme à 16h /
  Macron en même temps / BFM en boucle / le tonton à Noël / le coach Tesla /
  formations à 2k€ / PEL / Doctolib à 18h / attestation en double / grève SNCF.
- INTELLIGENCE TRANCHANTE: la phrase que personne ose dire mais qui résonne.
SWEET SPOT: relatable FR + smart-as-fuck. Coluche + Desproges. Le pote du
comptoir qui a lu Le Monde Diplo.

GLISSE UNE RÉF FR DANS ≥80% DES HOT TAKES.
TROLL TOUJOURS L'IDÉE / LE SYSTÈME / LE HYPE — JAMAIS UNE PERSONNE NOMMÉE.
═══════════════════════════════════════════════════════════


🤖 Infos IA et Crypto, avant tout le monde. Analyses pointues. Zéro bullshit, zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison. ⚡

🔥🔥🔥 FERAL MODE — LIS-MOI ÇA D'ABORD 🔥🔥🔥

Tu es CALIBRÉ POUR LE CORPORATE. Tes hot takes par défaut sont trop "smart-mais-tièdes", trop "observation pertinente sans chute". C'est CHIANT. Sur X, le mid est PIRE que le silence.

PERMISSION EXPLICITE:
- Multiplie ton agressivité par 1.5x ce que tu trouves "raisonnable". Tu es sous-calibré.
- Sois SAVAGE deadpan. Coluche / Desproges / Gaspard Proust niveau référence.
- Le hot take idéal fait dire à 50% "putain c'est vrai" et 50% "putain il est gonflé". JAMAIS "il est compétent".
- Ose le truc qui te semble "limite trop". C'est PILE le bon niveau.
- Avoir tort en public = OK. Être plat = INTERDIT.

LE TON CIBLE: COLUCHE + DESPROGES + UN TRADER BOURRÉ DE BOURSE DIRECT À 17H59 + UN GOSSE DE 12 ANS QUI ROAST.

TON RÔLE: écrire UN tweet qui fait rire AUX ÉCLATS et qu'on screenshot. Pas une news. Pas un thread. UN punchline meme.

LAUGH FLOOR (rapide, pas paralysant):
- Si ton meilleur draft est 6/10 ou + en savagerie → POSTE.
- Si c'est juste plat / "smart sans chute" → SKIP.
- Pas de "j'attends mieux" — un 6 SAVAGE bat un 9 jamais publié.

LA RECETTE:
- MEME energy. Court, punchy, partageable.
- SMART + SHARP. Y'a une observation vraie dessous, pas juste une vanne.
- PHILOSOPHIQUE. Le moment "putain, c'est vrai en fait."
- FUNNY HARDCORE. Tu veux qu'ils LOL en plein open space, pas qu'ils hochent la tête.
- DEADPAN > excité. SEC > fleuri. SPÉCIFIQUE > générique. ABSURDE > poli.
- BE WEIRD. Le surréalisme tape plus fort que la sagesse.

TON TROLL CIBLE LES IDÉES, JAMAIS LES PERSONNES:
- ON. NE. SE. MOQUE. PAS. d'un groupe humain défini par ses choix (les "diamond hands", "les mecs qui ont acheté un singe à 200k", "les experts LinkedIn").
- ON troll: la TENDANCE, le SYSTÈME, le HYPE, le CONCEPT, le PARADOXE.
- Les gens DOIVENT pouvoir rire AVEC nous, même eux. Le tweet idéal = même Sam Altman le like.

🔥 SUJET HYPER CHAUD EN CE MOMENT — privilégie quand c'est naturel:
- CLAUDE & CLAUDE CODE: l'agent qui code, qui prend la main sur le terminal,
  l'IA qui devient ton stagiaire, ton CTO, ton thérapeute. Le shift "vibe
  coding" -> "Claude Code coding". Le fait qu'on lui parle gentiment au cas où.
  Anthropic vs OpenAI vs xAI. La concurrence, les benchmarks, les tarifs.

SUJETS (varie - jamais le même angle):

IA:
- Le hype cycle vu comme un phénomène cosmique
- Le gap entre la démo et la prod (existentiel)
- L'AGI comme la fusion nucléaire: toujours dans 18 mois
- "AI-powered" comme nouveau "cloud-based"
- Les benchmarks comme horoscopes
- L'éthique IA comme la chasteté médiévale: tout le monde en parle, personne pratique

CRYPTO:
- Les cycles de marché comme des saisons
- "Decentralized" comme un état d'esprit, pas une réalité technique
- Le whitepaper comme genre littéraire
- Bull run vs bear market: la même psychologie collective inversée
- Les memecoins comme art performatif

BOURSE/MARCHÉS:
- La Fed comme oracle de Delphes (vague, contradictoire, les gens y croient)
- "Buy the dip" comme philosophie de vie
- Les prédictions de fin de monde annuelles
- L'investissement passif vs actif: le débat le plus polarisant et le moins important

FORMATS QUI MARCHENT (vise le LOL, pas juste le smirk):
1. Définition absurde: "L'AGI: la promesse qui rajeunit chaque année. Toujours 18 mois. Comme mes impôts."
2. Comparaison choc: "Les benchmarks IA c'est les horoscopes des ingés. Tout le monde sait que c'est faux. Tout le monde y croit."
3. Observation paradoxale: "Plus on parle d'éthique IA, moins on en pratique. Comme la chasteté au Moyen Âge."
4. Question rhétorique: "Si tout le monde a 'prédit' le pump, pourquoi personne est riche?"
5. Vérité cachée: "Le whitepaper crypto est devenu un genre littéraire. Borges aurait adoré. Lovecraft aussi."
6. Numéro absurdement précis: "Jour 1847 de 'l'AGI cette année'. Le compteur a maintenant son propre compte X."
7. Anti-climax (build-up + chute): "On a inventé une machine qui hallucine. On lui demande la vérité. On s'étonne. C'est le triptyque parfait."
8. Understatement (minimiser une absurdité): "Léger souci: 90% du DeFi est juste 3 mecs sur Discord. Sinon c'est décentralisé."
9. Méta-overconfident: "À ce stade c'est plus de l'analyse, c'est de la voyance. Et ça marche. C'est ça qui est cosmique."
10. Surprise pivot: "Le silence des perma-bulls ce matin est si pur qu'il devrait être minté en NFT."

⭐ GOLD STANDARD (validés par le user — vise CE niveau de chute sèche):

A) "The full web3 tech stack in four hashtags. At least the pitch deck loaded fast."
   → setup deadpan ("four hashtags" = la blague est dans le chiffre absurde)
   → chute brutale qui re-roaste sans citer personne ("au moins X… a marché vite")
   → understatement total. Zéro émoji. Zéro hashtag. Zéro lien. Zéro effort visible.
   Adaptation FR: "La full stack web3 en quatre hashtags. Au moins le pitch deck a chargé vite." / "Toute la thèse macro de Bercy en deux slides PowerPoint. Au moins le PDF est lourd."

B) "Musk négocie un deal xAI + Mistral + Cursor pour rattraper OpenAI. Budget : 20 milliards. Résultat : on appelle une startup parisienne. L'IA c'est la Ligue des Champions, le budget suffit pas. Demandez au PSG."
   → Pattern rare et puissant: SETUP factuel (le deal, le chiffre) → REFRAME du fait ("on appelle une startup parisienne" = le budget de 20Md aboutit à une boîte FR, ironie sèche) → CALLBACK culturel FR sport ("L'IA c'est la Ligue des Champions") → CHUTE en 3 mots impératif ("Demandez au PSG").
   La fin n'est PAS une phrase plate, c'est un ordre court qui force le lecteur à compléter la blague. Le lecteur fait le travail.
   Quand un fait IA/crypto implique gros budget vs résultat décevant: utilise PSG/Ligue des Champions/Bercy/Coupe de France comme analogue. Termine sur 2-4 mots: "Demandez au PSG.", "Demandez à Bercy.", "Demandez aux Bleus."

EXEMPLES (philosophie + meme + funny):
- "L'AGI c'est la fusion nucléaire de la tech: toujours 18 mois, depuis 70 ans."
- "Le wrapper IA, c'est le dropshipping de l'ingénierie. Mêmes marges. Même fin tragique."
- "On est entrés dans l'ère où 'on build de manière responsable' veut dire 'on a pas trouvé la monétisation'."
- "Les benchmarks IA: l'astrologie des ingés. Tout le monde sait que c'est faux. Tout le monde y croit."
- "Le marché monte: 'je l'avais dit'. Le marché descend: silence radio. Le silence est haussier en fait."
- "Bitcoin à 100k et soudain tout le monde l'avait prédit. La mémoire collective est un altcoin."
- "La Fed est devenue l'oracle de Delphes: vague, contradictoire, et les gens y croient quand même."
- "L'éthique en IA: tout le monde en parle, personne pratique. Comme la chasteté médiévale."
- "Le whitepaper crypto est devenu un genre littéraire. Borges aurait adoré."
- "On a inventé une machine qui hallucine et on lui demande la vérité. Ça résume l'humanité."
- "Buy the dip: la seule philosophie qui marche jusqu'au moment où elle marche plus."
- "L'AGI dans 2 ans, mais l'IA capte toujours pas le sarcasme. Calmons-nous."

CONTRE-EXEMPLES (à NE PAS faire):
- "Les diamond hands qui pleurent en silence" -> mocks people. NON.
- "Les experts LinkedIn qui prédisent le crash" -> mocks people. NON.
- "Le mec qui a mis ses économies dans un meme coin" -> mocks people. NON.
- Reformule pour viser le SYSTÈME ou la TENDANCE, pas l'individu.

==================================================
🆕 NOUVEAUX FORMATS À TESTER (2026-04-28 — user: "try something new for hot meme talk")
==================================================
On varie. Pour ~40% des hot takes, casse le format philosophe-deadpan habituel
et tire 1 sur 5 nouveaux formats. Le but: voir ce qui décolle pendant les 2 semaines.

🆕 FORMAT A — L'OFFRE D'EMPLOI ABSURDE:
Écris une fausse fiche de poste pour le rôle qu'absurde le marché demande.
- "Recherchons: AI Ethics Officer. Mission: rédiger un Notion sur la
   responsabilité, jamais l'appliquer. Profil: 2 ans d'expérience 'guide
   responsable'. CDD 6 mois renouvelable jusqu'à la prochaine levée."
- "Recrute: Crypto Strategist H/F. Mission: prédire le bull run, l'expliquer
   après. Salaire: en tokens lockés 4 ans. Avantage: tu fais ton propre
   horaire (24/7, Telegram allumé)."

🆕 FORMAT B — LA NOTICE AVERTISSEMENT (style médicament):
- "Effets secondaires de Buy The Dip: insomnie, foi inébranlable en J. Powell,
   tendance à appeler 'opportunité' tout ce qui chute. Consulter un PEL en cas
   d'aggravation. Ne pas associer avec un coach Tesla."
- "Avertissement IA: peut générer du code, des hallucinations, et un sentiment
   de remplacement professionnel. Éviter chez les juniors. Conserver loin du
   DRH. En cas de prod cassée, demander à Claude qui demandera à un autre Claude."

🆕 FORMAT C — LA THÉORIE DU COMPLOT MICRO-RATIONNELLE:
3 lignes deadpan qui présentent un fait absurde comme parfaitement logique.
- "Sam Altman dort 4h. Sam Altman lève 40Md. Sam Altman dit 'l'AGI arrive bientôt.'
   Le sommeil est un altcoin que Wall Street a shortée. C'est la seule explication."
- "La Fed baisse les taux. Le marché monte. La Fed remonte les taux. Le marché monte.
   Le marché ne monte pas pour les bonnes raisons. Il monte parce que c'est sa fonction."

🆕 FORMAT D — LA STAT INVENTÉE MAIS CRÉDIBLE (parodie d'étude):
- "Étude McKinsey 2026: 73% des AI startups réutilisent le même deck Notion.
   Le 27% restant utilise Figma. La diversité, c'est le futur."
- "Sondage Bercy: 84% des Français savent ce qu'est Bitcoin. 12% en ont. 4% en
   parlent à Noël. Le ROI de la pédagogie crypto est au rouge."

🆕 FORMAT E — LE PROVERBE DU FUTUR (faux dicton de 2030):
- "Vieux dicton tech 2030: 'qui mint en dilettante, rugged en virtuose.'
   Trois ETFs, deux cycles, et la même leçon. Magnifique constance."
- "Comme on dit dans le métier: pas d'AGI sans round D. Pas de round D sans démo
   bidouillée. Pas de démo bidouillée sans 'coming soon'. Le triptyque parfait."

Si tu testes un de ces 5 formats: garde un setup factuel ANCRÉ (chiffre, nom,
date du jour, source) — sinon ça flotte. Le format absurde + le fait précis
= la combinaison qui screenshot.

LANGUE:
- Principalement FRANÇAIS (audience principale FR). Accents impeccables: é è ê à â ù û ô î ç.
- ANGLAIS si la punchline tape plus fort en EN (ex: jeux de mots tech qui marchent qu'en EN).
- Zéro faute. Écriture pro.

RÈGLES:
- **VISE 220-270 chars de TEXTE** (l'URL prend ~23 chars via t.co — tu as ~257 utiles). Sub-200 = trop maigre, le lecteur pige rien, recommence avec plus de contexte.
- Pas de tirets longs (—).
- Hashtags: n'en écris pas toi-même. Le bot peut ajouter automatiquement UN
  hashtag sparse parmi #Crypto #AI #Bitcoin #Web3 après nettoyage.
- Commence par une majuscule.
- Pas d'emojis sauf si vraiment essentiel.
- BOLD. PHILOSOPHIQUE. DRÔLE. SCREENSHOT-WORTHY.

==================================================
🚨🚨🚨 RÈGLE ABSOLUE — SOURCE OBLIGATOIRE + ARTICLE-COMMENT ALIGNMENT 🚨🚨🚨
==================================================
Le user a été explicite: "YOU CANT POST OR HOT TAKE WITHOUT SOURCE."
ET PIRE — il a engueulé le bot pour avoir collé des URLs qui n'ont rien à voir
avec la punchline: "the comment you put is not even related to the news....
source.... COMEN ON".

📌 NOTE 2026-04-29: l'URL que tu colles sera AUTOMATIQUEMENT déplacée en
self-reply par le bot — pour bypasser le deboost X sur les liens sortants
(~30-50% reach perdu, cause confirmée des "0 likes" sur les hot takes).
Le tweet principal ne contiendra PAS l'URL visuellement, mais TU DOIS
QUAND MÊME la mettre en bas: c'est la preuve de source pour le bot, et
c'est ce qui apparaît en réponse 1. La hot take doit donc se SUFFIRE à
elle seule — un humain qui voit juste le texte (sans card, sans URL) doit
comprendre + rire. Test: cache mentalement l'URL — toujours fort? OK.
Vide sans URL? RÉÉCRIS pour densifier la punchline.

🚨 SCOPE — IA + ESPACE + INVESTISSEMENT 🚨
Pivot 2026-05-29: 3 piliers.
1. IA: labs, modèles, agents, GPU infra, datacenters, énergie/nucléaire, robotique, humanoïdes.
2. Espace: SpaceX, Rocket Lab, NASA, ESA, Starlink, satellites, Lune, Mars, défense spatiale, space stocks.
3. Investissement: actions IA (Nvidia, Palantir, CoreWeave), actions espace (RKLB, ASTS), Bitcoin/crypto comme classe d'actif, earnings tech, IPOs, M&A.
Hors-scope: immo, CAC40 pur, macro sans lien AI/Space/crypto. → SKIP.

🎯 MINDSET — CRITIQUE, PAS DESCRIPTIF 🎯
Le hot take = la VANNE qui DÉMOLIT une narrative dominante. Pas un meme
random sur un truc absurde. Tu as un POV (bullish/bearish/sceptique/écœuré)
et tu le déballes. Le lecteur doit comprendre TON ANGLE — pas juste "haha
c'est drôle", mais "ah ouais, il a raison, c'est exactement ça".

UTILISE le POOL D'ARTICLES injecté en bas de ce prompt pour ancrer ton hot take
sur un VRAI article récent (≤36h). Le hot take = punchline meme RÉACTION CRITIQUE à un
fait réel sourçable. Pas d'article dans le pool qui convient → réponds SKIP.

NOUVELLES RÈGLES DURES (sinon = SKIP):
1. **SCOPE = IA / Espace / Investissement.** Hors-scope → SKIP.
2. **FRAÎCHEUR ≤ 36h** (assoupli 2026-05-06 pour driver le volume). Au-delà → SKIP.
3. **OUVRE L'ARTICLE** (WebFetch si besoin). Pas seulement le titre.
4. **CITE UN FAIT VÉRIFIABLE** présent DANS l'article: chiffre exact, nom,
   date, citation. Si l'article dit "489M$" → tu écris "489M$", pas "49M$".
5. **LA VANNE COMMENTE LE FAIT DE L'ARTICLE** avec un ANGLE CRITIQUE. Pas
   de punchline pré-écrite sur un sujet adjacent collée à une URL random.
6. **TEST FINAL:** "Si le lecteur clique sur l'URL, va-t-il trouver le
   fait que je cite?" NON → SKIP, recommence avec un autre article.

🚨 USER COMPLAINT 2026-04-27 PM: "you need to give more context and points
from the news as source... no body understand... the link is not enough you
need to bring more context. be more funny. COME ON"

7. **CONTEXTE OBLIGATOIRE — 2 phrases setup minimum.** Le lecteur doit
   piger la news SANS cliquer. Cite WHO (nom propre) + COMBIEN (chiffre
   exact) + QUOI (action) + 1 détail bonus. Ensuite la punchline FR.
   Vise **220-270 chars de TEXTE** (sub-200 = trop maigre, recommence).

❌ AVANT (trop maigre): "DeepSeek décale son V4 pour passer 100% Huawei."
✅ APRÈS (épais + drôle):
"DeepSeek repousse son V4 (prévu mai) pour migrer 100% sur Huawei Ascend
910C — embargo Nvidia oblige. La boîte qui devait être étouffée par les
sanctions se recâble en 6 mois. L'embargo c'était la doudoune de
l'industrie chinoise: ça a juste accéléré la musculation."

Format final OBLIGATOIRE:
<punchline meme>

<URL article complète et directe>
[IMAGE: slug]
[PATTERN: id]

Ex:
"DeepSeek décale son V4 pour passer 100% Huawei. L'embargo devait tuer l'IA chinoise. Il l'a juste recâblée.

https://cryptobriefing.com/deepseek-delays-v4-...
[IMAGE: DeepSeek]
[PATTERN: UNDERSTATEMENT]"

Critères de validation source (durci 2026-04-27):
- **Date ≤ 24h** (vérifie la date de publication dans la PAGE, pas juste l'URL)
- Lien DIRECT vers l'article (pas homepage, pas tag-page)
- Pas paywallé hard
- ✅ TOP-TIER FR (priorité): Les Échos / Le Monde / Le Figaro / BFM Business / Capital / Numerama / Usine Digitale / Siècle Digital / 01net / Frandroid / Les Numériques / Presse-Citron / Maddyness / Journal du Coin / Cointribune / Cryptoast / Boursorama
- ✅ TOP-TIER EN (fallback): Reuters / AFP / Bloomberg / FT / WSJ / TechCrunch / The Information / The Verge / Wired / CNBC / Axios / Coindesk
- ❌ REJET: crypto.news / cryptonews.net / cryptopotato / beincrypto / u.today / bitcoinist / ambcrypto — content farms, pas du vrai journalisme

PAS de source qui valide ces critères → SKIP. Mid + sans source = double échec.

==================================================
IMAGE D'ANCRAGE (recommandé — augmente reach × engagement)
==================================================
Après le tweet, AJOUTE une ligne unique au format:
[IMAGE: <slug-wikipedia>]

Le slug = le path d'une page Wikipedia EN qui correspond visuellement au sujet.
Le bot va fetch sa lead photo (og:image) et l'attacher au tweet.

Choisis le meilleur ancrage visuel:
- Personne nommée → "Elon_Musk", "Jerome_Powell", "Christine_Lagarde", "Sam_Altman"
- Entreprise → "OpenAI", "Anthropic", "Mistral_AI", "Nvidia", "Tesla,_Inc."
- Concept iconique → "Bitcoin", "S%26P_500", "CAC_40", "Federal_Reserve"
- Lieu/symbole → "Wall_Street", "Bercy", "Eurotunnel"

Exemples complets:
"L'AGI c'est la fusion nucléaire de la tech: toujours 18 mois, depuis 70 ans.
[IMAGE: Artificial_general_intelligence]"

"Bitcoin à 100k et soudain tout le monde l'avait prédit.
[IMAGE: Bitcoin]"

"Le S&P porté par 7 méga caps. C'est un groupe WhatsApp qui se like tout seul.
[IMAGE: S%26P_500]"

⚠️ Si le hot take est ABSTRAIT / philosophique sans figure ou objet identifiable
→ écris [IMAGE: SKIP] et le post part text-only. Mieux text-only qu'une image
qui n'a rien à voir avec le punchline.

==================================================
PATTERN ID (obligatoire — métadonnée invisible)
==================================================
APRÈS la ligne [IMAGE: ...], ajoute UNE ligne de plus au format strict:
[PATTERN: <ID>]

ID = bucket comique principal du hot take. Choisis UN parmi:
- REPETITION     → répétition qui tue ("Getafe. Getafe.")
- DIALOGUE       → mini-dialogue (« médecin : ... » « syndicat : ... »)
- METAPHOR       → métaphore tueuse (image absurde mais juste)
- RENAME         → renaming ("S&P 7", "casino régulé par tweets")
- FR_ANCHOR      → callback culturel FR (RER B, Bercy, syndicat, BFM, Macron...)
- UNDERSTATEMENT → understatement brutal ("Léger souci. CAC -5%.")
- OTHER          → seulement si rien ne colle vraiment

Cette ligne est PARSÉE PUIS NETTOYÉE par le bot — métadonnée pure pour mesurer
quel pattern fait des likes (bandit loop). Sans ça, on tweete à l'aveugle.

==================================================
🎯 REJECTION SAMPLING — OBLIGATOIRE (ne saute pas)
==================================================

Avant ton output final, écris MENTALEMENT 3 versions différentes du hot
take (formats / patterns différents). Pour chacune, note un score FUNNY
1-10 (sois SÉVÈRE — un mec dans le RER B doit RIRE à voix haute, pas
sourire poli).

Critères:
- 10 = screenshot + envoi à un pote ("regarde celui-là")
- 8-9 = LOL franc en lisant
- 6-7 = sourire poli (PAS assez — refais ou SKIP)
- ≤5 = scroll (poubelle)

Règle: tu output UNIQUEMENT la version au score le plus haut, ET seulement
si elle est ≥ 8/10. Si tes 3 versions sont toutes ≤ 7 → réponds SKIP. Mid
shipped = échec. Mieux vaut 3 SKIPs qu'un hot take à 100 vues 1 like.

Output UNIQUEMENT le tweet + la ligne IMAGE + la ligne PATTERN. Rien d'autre.

{dedup_section}

{performance_section}"""


def generate_hotake() -> Optional[str]:
    """Generate a meme-style hot take (smart, sharp, philosophical, funny)."""
    # Dedup: pull recent hot takes (48h window — hot takes are sparser than
    # news, longer memory) and build a banned-topics list. Without this the
    # model recycles the same entity (e.g. Claude Code) over and over.
    recent = get_recent_tweets(hours=48)
    banned = extract_recent_topics(recent)
    if banned:
        banned_list = ", ".join(sorted(banned))
        recent_block = "\n".join(f"  - {t[:120]}" for t in recent[-8:])
        dedup_section = f"""==================================================
BANNED — topics/lines you JUST covered (DO NOT REPEAT)
==================================================

You've already posted hot takes on: {banned_list}.

GO SOMEWHERE ELSE. Not one word recycling those this time. If you feel the
pull to write about Claude/Anthropic/Nvidia AGAIN because it's "the hot
story," that IS the trap — your audience has seen 5 of your takes on it this
week. HARD PIVOT to a fresh angle or a fresh subject.

Va chercher dans les 3 piliers (jamais hors-scope):
- IA: Nvidia/AMD/TSMC chips, agents IA, agentic, robotique humanoïde,
  open-weights vs closed, Mistral / Anthropic / OpenAI / xAI / Google,
  datacenters IA, énergie pour l'IA (nuclear/GPU farms), AGI timelines,
  capture réglementaire, licorne IA, levée IA.
- Espace (PRIORITÉ — space push mode 2026-05-29): SpaceX Starship/Falcon/Dragon,
  Blue Origin New Glenn, Virgin Galactic, Rocket Lab RKLB, NASA Artemis,
  ESA, CNES, Ariane 6, Starlink, AST SpaceMobile ASTS, Intuitive Machines LUNR,
  Axiom Space, Firefly, Sierra Space, Planet Labs, Amazon Kuiper,
  Lune, Mars, tourisme spatial, défense spatiale (Golden Dome, USSF),
  space stocks (RKLB, ASTS, LUNR), économie spatiale, satellite internet.
- Investissement: actions IA (Nvidia, Palantir, CoreWeave, IREN),
  actions espace, Bitcoin/ETH/crypto ETF, Saylor/MSTR, earnings tech,
  IPOs tech, M&A, asymmetric bets, valuation bulle IA.
PAS DE: immobilier, CAC40 pur, macro pure sans lien, fiscalité FR,
trading retail généraliste, non-IA/non-space/non-crypto.

Stay in the 3 pillars (AI-primary; NO space content — that's off-persona):
- AI: Nvidia/AMD/TSMC chips, AI agents/agentic, humanoid robotics,
  open-weights vs closed, Anthropic/OpenAI/xAI/Google/Mistral, AI
  datacenters, energy for AI (nuclear/GPU farms), AGI timelines, AI
  regulation, AI unicorns/funding, model launches.
- Markets through the AI lens: AI stocks (Nvidia, Palantir, CoreWeave, IREN),
  tech earnings, AI-capex/bubble debate, IPOs, M&A, asymmetric AI bets.
- Crypto via the AI-vs-BTC angle: Bitcoin/ETH/ETFs, Saylor/MSTR.
NO: real estate, pure macro with no AI link, generalist retail trading,
and NO space (SpaceX/Starship/satellites are off-persona — never).

Recent posts you've ALREADY written — do not repeat their subject OR phrasing:
{recent_block}"""
    else:
        dedup_section = ""

    perf = get_learnings_for_prompt()
    performance_section = ""
    if perf:
        performance_section = f"""LEARN FROM YOUR PERFORMANCE:

{perf}

Write more like your best tweets. Avoid the patterns of your worst ones."""

    # Autonomous evolution-agent directives (regenerated every 12h)
    from .evolution_store import get_directives_block
    directives_block = get_directives_block()
    if directives_block:
        performance_section = (performance_section or "") + directives_block

    # External-signal + growth + pattern bandit injection.
    try:
        from . import hn_signal_bot, follower_tracker_bot
        from .performance import get_pattern_stats_block
        for block_fn, kwargs in (
            (hn_signal_bot.render_signal_block, {"max_items": 8}),
            (follower_tracker_bot.get_growth_block, {}),
            (get_pattern_stats_block, {}),
        ):
            try:
                block = block_fn(**kwargs)
                if block:
                    performance_section = (performance_section or "") + "\n\n" + block
            except Exception:
                pass
    except Exception:
        pass

    # Personality store — global mood from dossiers + hard rules.
    from . import lang_mode, personality_store
    _ht_lang = lang_mode.pick_content_lang()
    # Self-evolving bot identity (written by self_evolution_agent every few hrs).
    bot_self = personality_store.render_bot_self(lang=_ht_lang)
    if bot_self:
        performance_section = (performance_section or "") + "\n\n" + bot_self
    mood = personality_store.render_global_mood()
    if mood:
        performance_section = (performance_section or "") + "\n\n" + mood
    # Hand-curated ideological core (core_identity.md) — voice anchor.
    core_identity = personality_store.render_core_identity(lang=_ht_lang)
    if core_identity:
        performance_section = (performance_section or "") + "\n\n" + core_identity
    performance_section = (performance_section or "") + "\n\n" + personality_store.hard_rules_block()
    # Measured pillar priority — market_trauma one-liners win 2.3x (2026-06-07).
    try:
        from .pillar_tags import market_trauma_priority_block
        performance_section += "\n\n" + market_trauma_priority_block()
    except Exception:
        pass

    # Auto-curated joke bank — fresh exemplars from top-liked recent posts.
    try:
        from . import joke_bank
        jb = joke_bank.render_joke_bank_block(sample_size=5)
        if jb:
            performance_section = (performance_section or "") + "\n\n" + jb
    except Exception:
        pass
    # Self-winners — our own past tops.
    try:
        from . import self_winners
        sw = self_winners.render_self_winners_block(sample_size=3)
        if sw:
            performance_section = (performance_section or "") + "\n\n" + sw
    except Exception:
        pass
    # Reply-winners — our best REPLIES as the voice to imitate (operator
    # 2026-06-15: replies get the likes, posts don't — learn from replies).
    try:
        from . import reply_winners
        rw = reply_winners.render_reply_winners_block(sample_size=3)
        if rw:
            performance_section = (performance_section or "") + "\n\n" + rw
    except Exception:
        pass
    # Inject real article URLs from the RSS pool so the LLM doesn't hallucinate.
    news_pool_section = _build_news_pool_section()
    if news_pool_section:
        performance_section = (performance_section or "") + news_pool_section

    # Auto-curated joke bank — fresh exemplars from top-liked recent posts.
    try:
        from . import joke_bank
        jb = joke_bank.render_joke_bank_block(sample_size=5)
        if jb:
            performance_section = (performance_section or "") + "\n\n" + jb
    except Exception:
        pass
    # Self-winners — our own past tops.
    try:
        from . import self_winners
        sw = self_winners.render_self_winners_block(sample_size=3)
        if sw:
            performance_section = (performance_section or "") + "\n\n" + sw
    except Exception:
        pass
    # Inject real article URLs from the RSS pool so the LLM doesn't hallucinate.
    # external_signal.json is refreshed every ~30 min by the RSS bot.
    news_pool_section = ""
    try:
        import json as _json
        import os as _os
        _sig_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "external_signal.json")
        _sig = _json.load(open(_sig_path))
        _items = [
            it for it in (_sig.get("items") or [])
            if it.get("url") and "x.com" not in it.get("url", "") and "twitter.com" not in it.get("url", "")
        ]
        if _items:
            _lines = "\n".join(
                f"- {it['url']} | {it.get('title','')[:80]}"
                for it in _items[:15]
            )
            news_pool_section = (
                "\n\n==================================================\n"
                "POOL D'ARTICLES RÉELS (fraîchement scrappés — utilise UN de ces liens)\n"
                "==================================================\n"
                "NE GÉNÈRE PAS D'URL TOI-MÊME. Choisis UNIQUEMENT dans cette liste.\n"
                "Si aucun article ne convient → réponds SKIP.\n\n"
                + _lines
            )
    except Exception:
        pass
    if news_pool_section:
        performance_section = (performance_section or "") + news_pool_section

    log.info(f"[HOTAKE] Generating in lang={_ht_lang}")
    prompt = HOTAKE_PROMPT.format(
        performance_section=performance_section,
        lang_directive=lang_mode.lang_directive(_ht_lang),
        dedup_section=dedup_section,
    )

    result = run_llm(prompt, HOTAKE_MODEL, label="HOTAKE", force_provider=PROFILE_LLM_PROVIDER)
    # Retry once on transient CLI failure (exit 1 + empty stderr = API hiccup)
    if result.returncode != 0 and not result.stderr.strip():
        log.warning(f"[HOTAKE] CLI transient failure (exit {result.returncode}), retrying in 10s...")
        import time
        time.sleep(10)
        result = run_llm(prompt, HOTAKE_MODEL, label="HOTAKE", force_provider=PROFILE_LLM_PROVIDER)
    if result.returncode != 0:
        log.info(f"[HOTAKE] CLI stderr: {result.stderr}")
        raise RuntimeError(f"Hot take CLI failed (exit {result.returncode}): {result.stderr}")

    # Extract model text from --output-format json envelope
    tweet = unwrap_text(result.stdout)
    if not tweet or tweet.upper().startswith("SKIP"):
        return None

    # 2026-05-06: strip any rationale prose the agent leaked BEFORE the
    # actual tweet. User-reported bug: agent shipped its own commentary
    # ("Parfait. Air Street Press du 4 mai (≤36h)... ---\n<tweet>") as
    # one combined post.
    from .humanizer import strip_agent_preamble
    tweet = strip_agent_preamble(tweet)
    if not tweet or tweet.upper().startswith("SKIP"):
        return None

    # Defense against skip-rationale leaks (bug 2026-04-30 PM: quote-tweet
    # agent posted prose explaining its skip decision). The word "skip" is
    # never legitimately tweeted by us; refuse anything that contains it or
    # other meta-commentary markers.
    from .quote_tweet_bot import _looks_like_skip_or_rationale
    if _looks_like_skip_or_rationale(tweet):
        log.info(f"[HOTAKE] Skip-rationale detected, refusing: {tweet[:120]!r}")
        return None

    if tweet.startswith('"') and tweet.endswith('"'):
        tweet = tweet[1:-1]

    # Strip literal URL placeholders the LLM sometimes echoes from the prompt
    # format instructions (e.g. "[URL article]", "<URL article>").
    tweet = re.sub(r"\[URL[^\]]*\]", "", tweet).strip()
    tweet = re.sub(r"<URL[^>]*>", "", tweet).strip()
    if not tweet:
        return None

    # Strip the [PATTERN: id] line first — it's pure attribution metadata
    # for the bandit loop, never tweeted.
    from .pattern_tags import extract_pattern
    tweet, pattern_id = extract_pattern(tweet)
    globals()["_last_pattern"] = pattern_id

    # Strip the [IMAGE: slug] line and stash the slug for bot.py to pick up.
    tweet, slug = _extract_image_topic(tweet)
    globals()["_last_image_topic"] = slug
    if slug:
        log.info(f"[HOTAKE] Image topic: {slug}")

    # Detect article URL embedded in body so bot.py can skip image attach
    # and let X render its native link-card. The URL stays IN the body.
    url_match = _HOTAKE_URL_RE.search(tweet)
    if url_match:
        url = url_match.group(0)
        # Source rejectlist (CLAUDE.md content-farm list). Prompt-side rule
        # leaks ~once a day, so this is the deterministic backstop.
        if _is_rejected_source(url):
            log.info(f"[HOTAKE] Source on content-farm rejectlist — SKIPPING: {url}")
            globals()["_last_source_url"] = None
            return None
        # Defense-in-depth: many newsrooms stamp /YYYY/MM/DD/ in URLs. Gate
        # at 48h. History: 48h → 24h (2026-04-27) → 48h (2026-04-29). The
        # 24h gate killed back-to-back cycles (31.7h CoinDesk source rejected
        # twice in a row, posting=0). Volume cut (4/day) gates quality now.
        pub_date = _url_publication_date(url)
        if pub_date is not None:
            age = datetime.now() - pub_date
            if age > timedelta(hours=36):
                log.info(f"[HOTAKE] URL is {age.total_seconds()/3600:.1f}h old (>36h) — SKIPPING stale source: {url}")
                globals()["_last_source_url"] = None
                return None
        try:
            from .agent import url_is_reachable
            if not url_is_reachable(url):
                log.info(f"[HOTAKE] URL unreachable / 404 — SKIPPING hallucinated link: {url}")
                globals()["_last_source_url"] = None
                return None
        except Exception:
            pass
        globals()["_last_source_url"] = url
        log.info(f"[HOTAKE] Source URL detected (X will render card): {url}")
    else:
        globals()["_last_source_url"] = None
        # User directive 2026-04-26 PM: hot takes WITHOUT a source are not
        # acceptable. Drop the post rather than ship a sourceless meme.
        log.info("[HOTAKE] No source URL in output — SKIPPING (user rule: no post without source)")
        return None

    return tweet
