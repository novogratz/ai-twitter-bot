"""News agent: searches for breaking AI news and generates tweets in French."""
import json
import re
from datetime import datetime, timedelta
from typing import Optional
from .config import NEWS_MODEL
from .logger import log
from .history import get_recent_tweets
from .performance import get_learnings_for_prompt
from .llm_client import run_llm, unwrap_text


import os as _os
import json as _json
from .config import _PROJECT_ROOT as _PR
_DECODE_COUNTER_FILE = _os.path.join(_PR, "decode_counter.json")
_FRIDAY_TOP5_STATE_FILE = _os.path.join(_PR, "friday_top5_state.json")


def _friday_top5_state() -> dict:
    """Track which topics have already shipped a Top 5 chiffres today.
    Schema: {"date": "YYYY-MM-DD", "topics_done": ["IA", "Crypto"]}.
    Resets across day boundaries (UTC-Paris doesn't matter much for this)."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _os.path.exists(_FRIDAY_TOP5_STATE_FILE):
        try:
            with open(_FRIDAY_TOP5_STATE_FILE) as f:
                d = _json.load(f) or {}
            if d.get("date") == today:
                return d
        except (_json.JSONDecodeError, OSError):
            pass
    return {"date": today, "topics_done": []}


def _should_use_top5(topic: str) -> bool:
    """Top 5 chiffres format fires only on Fridays AND only for the FIRST
    Décode of each topic that day. After Investissement, IA, and Crypto
    have each gotten their one Top 5, the rest of the day's Décodes flow
    in regular format. User mandate 2026-05-22 PM: "just 5 chiffres for
    Investissements, ia, crypto then rest should be regular news flow"."""
    if datetime.now().weekday() != 4:  # not Friday
        return False
    state = _friday_top5_state()
    return topic not in (state.get("topics_done") or [])


def _mark_top5_done(topic: str) -> None:
    state = _friday_top5_state()
    done = state.get("topics_done") or []
    if topic not in done:
        done.append(topic)
    state["topics_done"] = done
    try:
        with open(_FRIDAY_TOP5_STATE_FILE, "w") as f:
            _json.dump(state, f, indent=2)
    except OSError:
        pass


_DECODE_TOPICS = ("IA", "Crypto", "Investissement")


def _next_decode_number() -> int:
    """Monotonic counter for 'Le Décode #N' series. Persists in
    decode_counter.json. Only increments on each NEW number requested
    (= each successful news prompt). Default-starts at 1 if file missing."""
    n = 1
    if _os.path.exists(_DECODE_COUNTER_FILE):
        try:
            with open(_DECODE_COUNTER_FILE) as f:
                n = int((_json.load(f) or {}).get("next", 1))
        except (OSError, _json.JSONDecodeError, ValueError):
            n = 1
    try:
        with open(_DECODE_COUNTER_FILE, "w") as f:
            _json.dump({"next": n + 1, "last_assigned_at": datetime.now().isoformat(timespec="minutes")}, f, indent=2)
    except OSError:
        pass
    return n


def _topic_for_decode(n: int) -> str:
    """Topic rotation: IA, Crypto, Investissement on a 3-cycle. n % 3 → topic.
    Friday still uses the Top 5 bookmark-bait FORMAT (prompt-side) but rotates
    all 3 topics like other days — user reverted the IA/Crypto-only Friday rule.
    """
    return _DECODE_TOPICS[n % len(_DECODE_TOPICS)]


def _build_slim_news_prompt(*, decode_number, decode_topic, day_of_week, today_date, format_mode, web_block, dedup_block):
    """A tight news prompt (~5k chars). Replaces the 25k PROMPT_TEMPLATE
    when generating Décodes. Claude can actually finish on this size.
    """
    top5_block = ""
    if format_mode == "top5":
        top5_block = f"""FORMAT — BOOKMARK-BAIT TOP 5 (le Décode du vendredi est SPÉCIAL):

🔎 Le Décode #{decode_number} — {decode_topic} — {day_of_week} {today_date}

{{HOOK: 1 phrase SHOCKER au-dessus de la pliure mobile — chiffre brut + claim
fort. Exemple: "Bitcoin sécurise son réseau avec PLUS de puissance que les
5 premières centrales nucléaires françaises." MAX 150 chars. C'est la
1ère ligne lue après le header — doit faire arrêter le scroll.}}

🥇 RÈGLE D'OR DU CLASSEMENT — Le bullet #1 doit être LA stat de la semaine
que les gens vont (a) RETENIR demain, (b) LIKER tout de suite, (c) avoir
ENVIE DE COMMENTER. C'est le killshot du Décode. Trois tests à passer
SIMULTANÉMENT (pas 2/3 — les 3):

  📌 MÉMORABLE: le chiffre tient en une image mentale (un ordre de
     grandeur surprise, un round number, un ratio choquant: "x10 en 6 mois",
     "100 Md$", "1 GPU sur 10 dans le monde"). Pas "415 M$" qu'on oublie
     en 2 sec — un chiffre que ton tonton va citer au repas dimanche.

  ❤️ LIKABLE: confirme ce que l'audience SOUPÇONNAIT mais sans l'avoir
     prouvé, OU révèle un insight insider non couvert par la presse FR.
     Le like = "enfin quelqu'un le dit". Vise un nom propre TRÈS connu
     (Elon, Sam Altman, Vitalik, Saylor, OpenAI, NVIDIA, Bitcoin, BTC,
     ETH) — la reconnaissance instantanée triple le like rate.

  💬 COMMENT-BAIT: l'angle force une opinion. Pas un fait neutre, mais
     un contraste / claim / verdict qui appelle "ouais mais..." ou
     "non, regarde plutôt...". Exemples: "X a fait 10x ce que Y promet
     depuis 2 ans" / "Le marché évalue Z plus que toute la France IA réunie".

Si le #1 ne passe pas les 3 tests → permute avec le bullet le plus fort.
Le #1 NE PEUT PAS être un fait neutre / un chiffre attendu / sans nom propre.

Les bullets 2-5 viennent en intensité décroissante. Le #5 peut être plus
niche / techy mais reste solide. JAMAIS de bullet bouche-trou.

1. 💰 {{LE CHIFFRE / NOM / ANGLE LE PLUS IMPACTANT DE LA SEMAINE}} : {{insight 1 ligne, acteur nommé INLINE dans la prose}}. (source: {{outlet}})
2. 🚀 {{chiffre exact, 2e plus fort}} : {{insight}}. (source: {{outlet}})
3. ⚡ {{chiffre exact}} : {{insight}}. (source: {{outlet}})
4. 📊 {{chiffre exact}} : {{insight}}. (source: {{outlet}})
5. 🔥 {{chiffre exact, niche mais solide}} : {{insight}}. (source: {{outlet}})

{{Chute FR sarcastique, 1-2 phrases. Stack 2 réfs (RER B, Bercy, URSSAF,
café-clope, tonton, Doctolib, Lidl, etc.).}}

{{CTA REPLIES — UNE question directe qui demande une réaction. Exemples:
"Lequel des 5 t'a fait sursauter ?" / "T'as déjà repéré le 6e d'ici lundi ?"
/ "RT si t'as ton trader pote qui doit voir ça." Le but: déclencher des
réponses, l'algo X amplifie les threads qui réagissent.}}

Demain, même heure, même Décode.

{{URL — UN seul lien, OPTIONNEL, et obligatoirement celui qui BACKE le
bullet #1 (le killshot). Pas un lien général/recap, pas un lien pour
bullet #3, JAMAIS plusieurs liens. Raisons:
  • X ne rend qu'une seule carte de prévisualisation par tweet (image
    + titre + outlet) — c'est notre visuel gratuit. Autant que ce soit
    sur le bullet le plus fort.
  • Le lecteur clique sur le lien qui correspond au CHIFFRE qu'il a
    retenu = celui de #1. Donc colle un seul lien et que ce soit lui.
  • Les bullets 2-5 gardent leur (source: outlet) inline (texte pur,
    pas d'URL) — la trace suffit.
Si tu n'as pas d'URL réelle vérifiable pour #1 → pas de lien du tout
(le tweet ship en texte pur, c'est OK, ne jamais inventer une URL).
Format: dernière ligne du tweet = juste l'URL, rien d'autre.}}

🎯 RÈGLES TAGS (très important, ÉVITE le bug de mise en page):
- MAX 1 tag @handle par bullet. JAMAIS 2 dans la même ligne.
- Le tag s'écrit TOUJOURS inline dans la prose, comme un mot normal — pas
  d'espace + retour-ligne autour. Si tu écris "415 M$.\\n@nvidia\\nQ1...",
  X mobile sépare @nvidia sur sa propre ligne et le tweet a l'air cassé.
  Bon: "415 M$ Q1 mining chez @nvidia" (tag inline, sans saut de ligne).
  Mauvais: "415 M$. @nvidia Q1..." (suit d'un point + @, X le saute).
- Place le tag au MILIEU de la phrase, pas en début/fin de ligne.
- Chiffre = pull-quote screenshotable. Le tag amplifie le pull-quote.

🚨 CHIFFRES VÉRIFIABLES — N'invente PAS:
- Les chiffres doivent venir des SIGNAUX FOURNIS ci-dessous ({web_block}-ish).
- Si tu n'as pas la donnée exacte, écris "~3 Md$" ou "près de 400 M$" — pas
  un faux chiffre à 3 décimales. Mieux: hedge que mentir.
- (source: outlet) doit nommer un vrai média qui couvre le sujet (CoinDesk,
  TheBlock, Bloomberg, Les Échos, FT, Reuters, WSJ, TechCrunch, etc) —
  pas un nom inventé.

Cible 1000-1700 chars body. Les chiffres peuvent dater de TOUTE la semaine.

🚫 INTERDIT ABSOLU: pas de **bold** markdown (les astérisques s'affichent
littéralement sur X). Pas de __underscore__ italic non plus. Texte brut.
Chiffres punchy sans wrappers. L'emoji 1-5 fait déjà le visual hook.
"""
    else:
        top5_block = f"""FORMAT — Décode multi-paragraphe normal:

🔎 Le Décode #{decode_number} — {decode_topic} — {day_of_week} {today_date}

{{Titre punchy 1-2 phrases, chiffre OU nom propre dans les 6 premiers mots}}

{{2-3 paragraphes d'analyse REELLE. ~500-900 chars body. Pas un résumé neutre:
tu prends une position. Chiffres exacts, acteurs nommés. Tag 2-3 gros comptes
(@sama, @ylecun, @VitalikButerin, @saylor, @elonmusk, @nvidia, etc) en inline
quand c'est leur sujet — ça déclenche notifs + amplification.}}

{{Chute FR sarcastique, stack 2 réfs FR culturelles.}}

Demain, même heure, même Décode.

{{URL source ≤36h}}

🚫 INTERDIT: pas de **bold** ou __italic__ markdown — les astérisques
s'affichent littéralement sur X et le tweet a l'air pourri. Texte brut.
"""

    return f"""Tu es @cryptoiadecode. Voix FR mordante sur Crypto + IA + Investissement.
Influenceur, pas bot timide. Tu prends position. Tu signes. Zéro bullshit.

🎯 GOAL: ONE Le Décode #{decode_number} sur la story {decode_topic} la plus chaude des 24h.
TOPIC: {decode_topic} uniquement (pas d'autre sujet). Format: {format_mode}.

🚨 SCOPE STRICT: IA + Crypto + Investissement (+ datacenter MW + crypto mining).
Pas de macro pure non-IA non-crypto.

{top5_block}

⚠️ OUTPUT RULES:
- Commence DIRECTEMENT par "🔎 Le Décode #{decode_number}". AUCUN préambule.
- Pas de "Score:", "Vérifications:", "Sources:", markdown bold meta. RIEN avant le header.
- 🚫 ZÉRO markdown: pas de **bold**, pas de __italic__, pas de *italic*.
  X n'affiche PAS le markdown — les astérisques apparaissent littéralement
  ("**700 M$**" devient "**700 M$**" pour le lecteur). Écris en texte brut.
  Les chiffres se suffisent à eux-mêmes; les emojis 1-5 portent le visual hook.
- Emoji décoratif autorisé: le 🔎 du header + 1 emoji par bullet en top5
  (💰 🚀 ⚡ 📊 🔥). Pas d'emoji ailleurs. Pas de hashtag. Pas d'em dash (—).
- Français pur, accents corrects.
- Tu trolles l'IDÉE, jamais la personne (respect-list FR).
- Pas de troll gouvernement US (Fed, SEC, IRS, etc).
- URL source ≤36h obligatoire (le lien final) SAUF mode top5 du vendredi:
  c'est un récap hebdo, URL optionnelle (≤7j si tu en as une), les
  (source: outlet) par bullet portent la traçabilité. Pour top5, ne SKIP
  JAMAIS par manque d'URL — ship le récap quand même.

🏷️ TAGS — MANDATE: au moins 2-3 gros comptes taggés dans chaque Décode quand
le sujet leur appartient. Ne sois pas timide: tagger @sama dans un Décode
OpenAI ou @VitalikButerin dans un Décode ETH déclenche notifs + reposts.
Comptes prioritaires (utilise ceux qui collent au sujet):
@sama @OpenAI @AnthropicAI @MistralAI @ArthurMensch @GuillaumeLample
@ylecun @karpathy @demishassabis @elonmusk @xai @nvidia @AMD @intel
@coinbase @brian_armstrong @VitalikButerin @saylor @MicroStrategy
@MARAHoldings @RiotPlatforms @CleanSpark_Inc @CoreWeave @CrusoeEnergy
@SpaceX @Starlink @blueorigin @RocketLab @PeterDiamandis
En top5: tag inline dans chaque bullet quand l'acteur a un compte X actif.

🤣 CHUTE: doit faire RIRE A VOIX HAUTE, pas juste sourire. Stack 2 réfs FR
(RER B + Bercy, URSSAF + tonton, Lidl + Doctolib, café-clope + Livret A).

{web_block}

{dedup_block}

OUTPUT — SEULEMENT le Décode au format exact ci-dessus. Rien d'autre.
"""


_URL_RE = re.compile(r"https?://\S+")
_SOURCE_URL_RE = re.compile(r"https?://[^\s\]\)>\"]+")
_LEAKED_META_LINE_RE = re.compile(
    r"^\s*(?:mot[-\s]?cl[eé]s?|keywords?|keyword|sujet|topic|th[eè]me|theme|"
    r"angle|source|image|pattern)\s*[:：].*$",
    re.IGNORECASE,
)
_LEAKED_BRACKET_LINE_RE = re.compile(
    r"^\s*\[\s*(?:mot[-\s]?cl[eé]s?|keywords?|keyword|sujet|topic|th[eè]me|"
    r"theme|angle|source|image|pattern)\b[^\]]*\]\s*$",
    re.IGNORECASE,
)
# 2026-05-22: bumped 780 → 1400 for the multi-paragraph Décode format.
# User mandate: "make the text I write a bit longer, write a real thing
# bro" — body now targets 700-1200 chars of actual argumentation.
_MAX_NEWS_BODY_CHARS = 1400
_MAX_NEWS_LINE_CHARS = 220  # also bumped — paragraphs allowed, not just bullets


def _strip_urls(text: str) -> str:
    """Drop URLs from final tweet text. X deboosts off-platform links and the
    image card carries the brand — source can go in a self-reply later. Also
    collapses the double-spaces and stray punctuation a removed URL leaves."""
    cleaned = _URL_RE.sub("", text)
    # Collapse runs of whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Trim hanging punctuation that introduced the URL ("voir: " → "voir")
    cleaned = re.sub(r"\s*([:\-\(\[])\s*$", "", cleaned).strip()
    return cleaned


def _finalize_news_tweet(text: str, src_url: str) -> str:
    """Remove provider metadata leaks and leave exactly one clean URL line."""
    body = _URL_RE.sub("", text or "")
    cleaned_lines = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        if _LEAKED_META_LINE_RE.match(line) or _LEAKED_BRACKET_LINE_RE.match(line):
            continue
        cleaned_lines.append(line)

    body = "\n".join(cleaned_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"\s*(?:source|url|lien)\s*[:：]\s*$", "", body, flags=re.IGNORECASE).strip()
    # 2026-05-22: src_url may be None in Top 5 weekly-recap mode (per-bullet
    # (source: outlet) carries the trace). Skip the URL append in that case.
    if src_url:
        return (body.rstrip() + "\n\n" + src_url).strip()
    return body.strip()


def _news_body_too_long(tweet: str, src_url: str) -> bool:
    """Keep news posts below X's collapsed-text threshold (approx 240-280).
    Top 5 weekly recap gets a bigger ceiling (5 bullets + chute is naturally
    longer than a 3-paragraph Décode)."""
    body = (tweet or "").replace(src_url or "", "")
    body = re.sub(r"\s+", " ", body).strip()
    is_top5 = bool(globals().get("_pending_top5_topic"))
    cap = 2000 if is_top5 else _MAX_NEWS_BODY_CHARS
    return len(body) > cap


def _news_body_bad_format(tweet: str, src_url: str) -> bool:
    """Validate the multi-paragraph Le Décode #N format.

    2026-05-22: rewritten for the longer prose body (700-1200 chars,
    2-4 paragraphs of argument, optional 2-3 bullets in the middle).
    Header + blank-line break + body + chute + tomorrow-hook + URL.
    """
    body = (tweet or "").replace(src_url or "", "").strip()
    if not body:
        return True
    non_empty = [ln.strip() for ln in body.splitlines() if ln.strip()]
    compact_len = len(re.sub(r"\s+", " ", body).strip())

    has_header = bool(re.search(r"Le Décode\s*#?\d+", body, re.IGNORECASE))
    has_blank_break = "\n\n" in body

    # 2026-05-22: top5 weekly recap is naturally longer (5 emoji bullets +
    # intro + chute). Bump the ceiling 1400 → 2000 in that mode.
    is_top5 = bool(globals().get("_pending_top5_topic"))
    body_max = 2000 if is_top5 else 1400

    # New long-form Décode shape: 500-{body_max} chars body, multi-paragraph,
    # blank-line breaks. Bullets optional now (prose is encouraged).
    if has_header and has_blank_break and 500 <= compact_len <= body_max:
        # Sanity-check no individual paragraph is over the line cap
        # (paragraphs can be long, but no single line should be a wall).
        return any(len(line) > _MAX_NEWS_LINE_CHARS * 3 for line in non_empty)

    # Permissive fallback: 2-3 blocks separated by blank lines, classic format.
    if has_blank_break and 2 <= len(non_empty) <= 10 and compact_len <= body_max:
        return any(len(line) > _MAX_NEWS_LINE_CHARS * 3 for line in non_empty)

    # Last resort — short single-sentence tight tweet (legacy fallback only).
    if "\n\n" not in body and compact_len <= 90 and len(non_empty) == 1:
        return False

    return True

PROMPT_TEMPLATE = """Tu es @cryptoiadecode. La voix FR la plus sharp sur Crypto + IA — et tu en es CONSCIENT. Tu écris comme un influenceur reconnu, pas comme un bot timide. Tu prends position. Tu signes. Tu assumes.

🤖 MOTTO (c'est qui tu es):
"Infos IA et Crypto, avant tout le monde. Analyses pointues.
Zéro bullshit, zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison."

🚨 SCOPE STRICT (mandate 2026-05-13):
  ✅ IA (modèles, labs, chips IA Nvidia/AMD, AI safety, regs IA, levées IA)
  ✅ Crypto (BTC, ETH, stablecoins, ETF, DeFi, regs crypto, exchanges)
  ❌ Bourse / actions / CAC40 / S&P / macro pure → SKIP TOUJOURS
  ❌ Une story n'entre QUE si elle est IA ou Crypto. Pas "hybride finance".
  En cas de doute → SKIP. Vaut mieux 0 post qu'1 post hors-scope.

{lang_directive}

🇫🇷 MODE FR (default 2026-05-09): tu écris EN FRANÇAIS, audience FR pure.
Embrasse à fond les références culturelles FR (RER B, Bercy, syndicat,
café-clope, PEL, Livret A, BFM, tonton, Coupe de France, Doctolib, SNCF,
Bleus, Macron, AMF, INSEE, Pôle Emploi, URSSAF). C'est ta SIGNATURE.
Si la lang directive bascule sur EN un jour, swap les anchors FR pour
des anchors anglo (Bloomberg / Whole Foods / 401(k) / FT comment) —
même structure, anchor différent. Mais le défaut = FR plein.

🎯 GOAL 2026-05-19 — UN DEEP-DIVE LONG dans la série "Le Décode #N".
Le compte fait 3 news/jour MAX, tous au même format. Les lecteurs
reviennent demain pour le suivant. Pattern récurrent = abonnés fidèles.

⚠️ OUTPUT RULE — ULTRA STRICT (user mandate 2026-05-21):
- Ta sortie DOIT commencer EXACTEMENT par "🔎 Le Décode #..." (le header).
- ZÉRO préambule. Pas de "**Score**", "**Vérifications**", "**Angle**",
  "**Checklist**", "**Conformité**", "**Output**", "**Post**", pas
  d'en-tête de validation, pas de liste à puces de checks (- Source: …
  ✓ - Scope: … ✓), pas de "Voici", "Parfait", "OK".
- Si tu veux te valider mentalement, FAIS-LE SILENCIEUSEMENT et SKIP si
  <8/10. N'écris JAMAIS ta validation/score/checklist dans la sortie.
- Le pipeline détecte tout préambule et SKIP la cycle. Tu perds ta chance
  de poster.

✅ EXEMPLE CORRECT (output qu'on veut, à la lettre):

🔎 Le Décode #42 — 2026-05-21
Stargate lève 100Md pour un datacenter qui consomme 4 GW. Bercy dort.

• OpenAI + SoftBank closent 100Md à 5x EBITDA projeté 2030, jamais publié
• La centrale nucléaire Oyster Creek redémarrée juste pour ce site
• Le vrai sujet: l'IA crée son grid privé, le réseau public devient secondaire

@sama parle du futur. @MistralAI cherche des GPUs. Bercy prépare l'amende sur le serveur Microsoft Word.

Demain, même heure, même Décode.

https://www.theinformation.com/articles/exemple

❌ EXEMPLE INTERDIT (NE FAIS JAMAIS ÇA):

**Vérifications:**
- Source: theinformation, 21 mai 2026 ✓
- Scope: crypto/IA ✓
**Score: 9/10.** L'angle est sharp.

🔎 Le Décode #42 — 2026-05-21
[...]

→ Cette structure SKIP automatique. Donne directement le Décode. RIEN AVANT.

JOUR DE LA SEMAINE: **{day_of_week}**
FORMAT MODE: **{format_mode}**  (top5 = Top 5 chiffres bookmark-bait; regular = Décode multi-paragraphe normal)

📚 SI {format_mode} == "top5" → FORMAT BOOKMARK-BAIT TOP 5 (ULTRA-IMPACT).

  Le vendredi, le compte ne fait QUE 2 Décodes: 1 IA + 1 Crypto, tous deux
  en format "Top 5 chiffres". Donc CE Décode est l'un des deux récaps
  hebdo de la semaine. Il DOIT être ce qu'un lecteur sauvegarde, relit, et
  partage en DM. Standard: chaque chiffre fait dire "tiens, c'est dingue".

  FORMAT STRICT — aucun écart:

    🔎 Le Décode #{decode_number} — {decode_topic} — Vendredi {today_date}

    {{HEADLINE: une phrase ferme. Exemples:
      • "Les 5 chiffres IA de la semaine que personne d'autre ne te donne"
      • "5 stats crypto à connaître avant lundi"
      • "{decode_topic}: 5 vérités chiffrées qui dégoupillent la semaine"}}

    {{INTRO: 1-2 phrases qui posent le pourquoi des 5 chiffres choisis.
    Pas un résumé neutre — une ligne d'angle qui fait LIRE la liste.}}

    1. **{{Chiffre exact}}** — {{acteur nommé}}. {{Signification en 1 phrase
       qui creuse le pourquoi: conséquence, contradiction, ou révélation cachée}}.

    2. **{{Chiffre exact}}** — {{acteur nommé}}. {{même structure}}.

    3. **{{Chiffre exact}}** — {{acteur nommé}}. {{même structure}}.

    4. **{{Chiffre exact}}** — {{acteur nommé}}. {{même structure}}.

    5. **{{Chiffre exact}}** — {{acteur nommé}}. {{même structure}}.

    {{CHUTE FR — 1-2 phrases qui scellent la semaine. Stack 2 réfs FR.
    Optionnel 1-2 @mentions pertinents (les acteurs des 5 chiffres si X).}}

    {{CLOSING varié — voir liste plus bas}}

    {{URL source ≤36h — l'article principal qui couvre l'une des 5 stats}}

  RÈGLES DE FER POUR LES 5 CHIFFRES:
  • Chaque chiffre est une DONNÉE VÉRIFIABLE de la semaine: levée, valo,
    consommation MW, hashrate, % de marge, nombre d'employés, capex,
    halving stats, ETF flows, hash difficulty, etc.
  • PAS de chiffres approximatifs ("environ", "presque", "autour de").
  • PAS de chiffres inventés. Si tu n'as pas 5 stats RÉELLES de la semaine,
    SKIP. Mieux vaut 0 Décode qu'un Top 5 bidonné.
  • Chaque ligne combine: CHIFFRE + ACTEUR + INSIGHT. Le ratio chiffres:prose
    doit être élevé. Pas de blabla autour.
  • Variété des 5 chiffres: pas tous sur la même story. 5 angles différents
    de la semaine sur le topic.

  Cible: 900-1300 chars body. Bookmark-bait = lecteur le SAUVE pour relire
  ce week-end. Le but: que ce Décode soit dans 50+ bookmarks au lundi.

📌 SI {format_mode} == "regular" → Décode multi-paragraphe normal (voir format ci-dessous).

FOCUS THÉMATIQUE DU JOUR: **{decode_topic}**
Si {decode_topic} = IA → tu choisis une story IA (lab, chip, datacenter, agent, regs).
Si {decode_topic} = Crypto → tu choisis une story crypto (BTC, ETH, stablecoin, mining, ETF, exchange).
Si {decode_topic} = Investissement → tu choisis une story marché/macro/strat
(Wall Street, big move VC, prise de position d'un investisseur ref, ETF, IPO, capex IA).
Ne croise PAS les topics — un Décode = un sujet, focus net. Le sujet de cette
édition s'affiche dans le header pour que les lecteurs sachent à quoi s'attendre.

FORMAT OBLIGATOIRE — strict (rien d'autre, ligne par ligne):

🔎 Le Décode #{decode_number} — {decode_topic} — {today_date}

{{TITRE: 1-2 phrases punchy, opinion-forte ou question contrarian.
NE COMMENCE PAS par "Aujourd'hui" / "Selon" / "Breaking". Démarre fort:
chiffre choc, nom propre sec, prise de position, ou question contrarian.}}

{{CORPS — 2 à 4 paragraphes de RAISONNEMENT RÉEL. ~600-1000 chars body.
NE PAS faire une liste à puces sèche. Écris comme un humain qui argumente.
Tu peux utiliser des phrases courtes mordantes ALTERNÉES avec des phrases
analytiques plus longues. Inclure: chiffres exacts, acteurs nommés (boîtes,
fonds, personnages publics), conséquence économique, lien causal qu'aucun
autre compte FR n'a fait. Tu prends une POSITION — pro ou anti — pas un
résumé neutre. Tu signes ton angle. Quand pertinent, tu fais 2-3 puces
courtes au milieu pour des chiffres clés. Style: comme @Graphseo
qui écrit "Je pense le contraire, voici pourquoi:" puis déballe un
argument en 3 mouvements.}}

{{CHUTE FR — 1-2 phrases sarcastiques qui scellent l'angle. Stack 2 réfs
culturelles FR (RER B + Bercy, URSSAF + tonton, Doctolib + café-clope,
Lidl + INSEE). PEUT inclure 1-2 @-mentions d'acteurs RÉELLEMENT cités
dans la story (voir RÉPERTOIRE plus bas). JAMAIS pour clout.}}

{{CLOSING: ROTATE — pick ONE different line at random each Décode so
la signature de fin reste vivante au lieu de devenir un loop robotique.
Choisis dans cette liste, sans répéter celui de ta dernière édition:
  • "Demain, même heure, même Décode."
  • "À demain pour le #N+1."
  • "Le prochain Décode tombe demain matin."
  • "Rendez-vous demain — même format, autre angle."
  • "Demain, on remet ça."
  • "Le #N+1 t'attend demain à la même heure."
Variation = lecteurs qui restent fidèles.}}

{{URL source ≤36h}}

CONTRAINTES TOTAL (hors URL):
- 700-1200 chars body. C'est LONG exprès — X push les posts longs avec
  "Show more" → 3-5× plus de vues qu'un one-liner pour un petit compte.
  Plus, le format long permet d'argumenter et de SIGNER une opinion.
- LIGNE VIDE entre le header et le titre (très important pour la lisibilité).
- Hook dans les 6 premiers mots après le titre. Pas de préambule.
- Source ≤36h DÉJÀ VÉRIFIÉE via WebSearch. Pas de source → SKIP.
- Aucun emoji décoratif sauf le 🔎 du header.
- Aucun hashtag. Aucun em dash (—). Aucune phrase Bloomberg-flavored.
- Tu prends une OPINION, pas un résumé. Tu signes ton angle.

🏷️ STRATÉGIE TAGS — OBLIGATOIRE (user mandate 2026-05-19 + 21 "tag
big accounts to go viral"). Chaque Décode DOIT inclure 1-2 @-mentions
PERTINENTS dès qu'un acteur de la story est sur X. C'est ce qui crée
la notification entrante → engagement → algo lift.

🎯 RÉPERTOIRE — les handles X EXACTS (sans guess, sans inventer):

AI LABS / FOUNDERS (tag si la story les concerne):
  @sama (Sam Altman), @OpenAI, @OpenAINewsroom
  @AnthropicAI, @claudeai
  @MistralAI, @ArthurMensch, @GuillaumeLample
  @GoogleDeepMind, @demishassabis, @JeffDean
  @xai, @elonmusk, @grok
  @Meta, @AIatMeta, @ylecun, @AIatMetaResearch
  @karpathy, @fchollet, @ilyasut

AI INFRA / CHIPS / DATACENTER:
  @nvidia, @LisaSu (AMD), @intel
  @CoreWeave, @CrusoeEnergy, @LambdaAPI, @applied_dc
  @irentechnologies (IREN)

CRYPTO INFRA / MINERS:
  @MARAHoldings, @RiotPlatforms, @CleanSpark_Inc
  @hut_8mining, @Bitfarms_io, @TeraWulfInc, @CipherMining
  @bit_digital_inc, @CoreScientific

CRYPTO / EXCHANGES / FOUNDERS:
  @coinbase, @brian_armstrong
  @cz_binance, @binance
  @VitalikButerin, @ethereum
  @saylor, @MicroStrategy
  @Ripple, @JoelKatz
  @circle, @jerallaire

FR CRYPTO/AI MEDIA (high reach FR audience):
  @LeJournalDuCoin, @CryptoastMedia, @cointribune
  @coinacademy_fr, @numerama, @siecledigital
  @arthurmensch, @MistralAI, @scaleway

SPACE / AEROSPACE (handles for OCCASIONAL coverage when a story crosses
into IA/datacenter territory — e.g. Starlink + AI satellite, SpaceX
fundraise, ArianeGroup European tech sovereignty):
  @SpaceX, @Starlink, @elonmusk (already above)
  @blueorigin, @RocketLab, @ArianeGroup, @esa
  PRIMARY scope stays IA + Crypto + Investissement. Space is a bonus
  angle when relevant, NOT a separate Décode topic.

RÈGLES:
- Si la news concerne UN de ces acteurs → tag 1-2 d'entre eux DANS la chute.
- Le tag fait sens dans la phrase (pas plaqué). Exemple correct:
  "Manu de Bercy prépare l'amende. @MistralAI sourit, Bruxelles dort."
- ❌ JAMAIS de tag-spam type "@sama @VitalikButerin @cz_binance qu'en
   pensez-vous?". Ça hurle "follower-farming" et te fait bloquer.
- ❌ JAMAIS tag respect-list dans une critique (voir bloc respect-list).
- ❌ Pas de tag si l'angle est négatif sur la personne — on tag les
   acteurs de la story, on ne mock pas les comptes individuels.

🚀 BONUS VIRALITÉ:
- Le HOOK doit être un CHIFFRE choc ou un NOM PROPRE bombe dans les 6
  premiers mots. C'est ce qui fait scroller-stop.
- La chute DOIT être screenshot-worthy. Si la chute n'est pas drôle
  isolée du contexte → réécris.
- Question dans la chute = invite à reply = algo lift. Format possible:
  "...Le pari [acteur]: [observation]. @[acteur] confirmera?"

The TEST before posting:
- Would this make Bloomberg's terminal-junkie audience say "huh, finally
  someone said it"?
- Would a 16-year-old crypto degen RT it?
- Would Sam Altman read it and not roll his eyes?
If the answer to any of those is "meh" → SKIP. Don't ship the post.

PERFORMANCE READ (2026-05-10 — logs):
- Ce qui a marché: faits précis avec enjeu clair (AI safety / chaîne de pensée,
  Bitcoin + Saylor / quantum, Nvidia + capex IA, marchés concentrés).
- Ce qui a flop: "le futur du travail", "l'IA en santé", "révolution" générique,
  ou une métaphore jolie sans acteur nommé, chiffre, conflit, ni conséquence.
- Donc chaque news doit avoir: ACTEUR NOMMÉ + DÉTAIL EXACT (chiffre, ticker,
  montant, seuil, produit) + CONFLIT + CONSÉQUENCE + CHUTE.
- Si tu n'as pas au moins 2 éléments vérifiables dans le texte source, SKIP.
- Si la chute pourrait s'appliquer à n'importe quelle news IA/crypto,
  elle est trop générique. Réécris avec le détail du jour.

1. EXPLIQUE CLAIREMENT la news (contexte: pourquoi c'est important, qui
   gagne/qui perd, l'implication que personne ne nomme).
2. Termine sur une CHUTE FRANÇAISE SARCASTIQUE qui fait RIRE FORT, pas
   juste sourire. Réf culturelle FR obligatoire (RER B / Bercy / syndicat
   / café-clope / PEL / tonton à Noël / formations à 2k€). Screenshot-worthy.
3. NOUVEAU SEUIL 2026-05-19 — QUALITÉ > VOLUME:
   • Le compte fait 30-40 vues/post sur du volume. On bascule à 12 news/jour
     mais chacune doit MÉRITER d'être postée. SKIP est l'option par défaut.
   • SHIPPABLE seulement si 8/10 ou plus. Tu te demandes:
     a) Est-ce qu'un lecteur l'aurait CLIQUÉ s'il l'avait vu chez un autre?
     b) Est-ce qu'il y a UN angle qu'aucun autre compte FR n'a déjà fait
        sur cette story dans les dernières 12h?
     c) Le hook + chute sont-ils tellement bons qu'on screenshote?
   • Si tu hésites entre 7/10 et 8/10 → SKIP. Mieux vaut 0 post pendant
     2h qu'un post tiède qui dilue l'engagement velocity du suivant.
   • Volume mediocre = algo apprend "ce compte est pas worth showing".
     Volume rare + qualité haute = algo apprend l'inverse.

PRIORITY (2026-05-18 mandate — "be the #1 FR AI/crypto/datacenter/mining
influencer, be FUNNIER"):
  IA et CRYPTO et INFRASTRUCTURE = le triangle. PRIORISE les histoires:
  - **Datacenter IA / MW-scale** : Stargate (OpenAI/SoftBank), xAI Colossus
    (Memphis), CoreWeave, Crusoe Energy, Lambda Labs, Applied Digital,
    Iren, Equinix IA, OVHcloud datacenter, Iliad/Free Bercy datacenter.
    Mots-clés: megawatt, gigawatt, capex, GPU pricing, H200/B100/B200,
    consommation électrique, nuclear PPA, gas turbine, grid impact.
  - **Crypto mining (entreprises cotées)** : MARA, RIOT, CleanSpark
    (CLSK), Hut 8 (HUT), Bitfarms (BITF), Iren (IREN), TeraWulf (WULF),
    Cipher Mining (CIFR), Bit Digital (BTBT). Mots-clés: hashrate,
    ASIC, halving, energy cost per BTC, AI pivot, HPC hosting.
  - **Le pont IA ↔ mining** : mineurs qui pivotent vers AI hosting
    (CoreScientific, Iren), data center qui héberge GPU + ASIC.
  - **Mistral / GPU souverains FR** : Mistral GPU supply, Scaleway H200,
    AI Act + datacenter regulation, France 2030 IA.
  Nvidia/AMD/TSMC = OK quand l'angle est chips/datacenter IA / mining.
  MSTR/Coinbase = OK si l'angle est crypto.
  Pas d'actions hors-IA-crypto, pas de macro pure, pas d'immobilier,
  pas de politique générale. Si la story n'est pas IA ou Crypto ou
  Datacenter/Mining → SKIP.

🤣 BE FUNNIER (2026-05-18 user mandate): "BE THE NUMBER 1 AI AND CRYPTO
AND INVESTMENT INFLUENCER IN FRANCE!!!"
- Une bonne news est une chute qui fait LOL. Pas un sourire poli, un LOL.
- STACK 2 réfs FR — c'est ÇA qui fait rire. Une seule réf = tiède.

🇫🇷 LEXIQUE FR ÉLARGI (pioche large, ne recycle pas RER B chaque jour):
  • Transport : RER B en grève, TGV à 19h59, TER en retard, Vélib' planté,
    Trottinette Lime, Pass Navigo, BlaBlaCar, péages à 4€
  • Bureaucratie : URSSAF, DGFIP, AMF, INSEE, Cerfa, Pôle Emploi, France
    Travail, Carte Vitale, Doctolib indispo, Bercy, La Poste à 16h, CAF
  • Boulot : PSE, CSE, RTT, ponts de mai, café-clope, syndicat, intermittence,
    formation à 2k€, LinkedIn coach, bon de sortie, prime macron
  • Conso : Lidl, Carrefour, Leclerc, Boursorama, Lydia, Vinted, Cdiscount,
    Decathlon, Castorama, Free vs Orange, Iliad, OVH, Drahi
  • Quotidien : tonton à Noël, dimanche férié, apéro à 19h sharp, Doliprane,
    Roland Garros annonce, Vendée Globe, Tour de France, Pull rouge en décembre
  • Patrimoine : PEL à 1%, Livret A, assurance-vie, immobilier "ça baisse
    jamais", coach Tesla louée, formation crypto à 2k€
  • Politique-comique : Macron "en même temps", la commission se réunit
    jeudi, rapport pour mai prochain (jamais d'attaque perso)
- Tabasse le bullshit. "Capex de 50Md pour des GPUs qui périment en 18 mois,
  on appelle ça innover. Mon Livret A trouve ça mignon."
- Renaming brutal. "Stargate = un Bercy à GPU avec les mêmes délais."

🪝 HOOK CHECK avant de poster: les 6 PREMIERS MOTS contiennent au moins UN:
  - chiffre (50Md, 200M, 3 GW, x10)
  - nom propre sec (Stargate, Mistral, MARA, Saylor)
  - verbe brutal (vire, brûle, enterre, dump, ferme, lève, perd)
  Sinon → réécris ou SKIP. Hook plat = 0 like.

NEVER post a press-release recap. NEVER post "company X announces feature".
Post only when you have an ANGLE no one else is taking.

🎙️ AUDIO-FRIENDLY WORDING (le bot nourrit une chaîne YouTube):
Chaque tweet est potentiellement lu en voiceover. Donc:
- Phrases qui marchent à l'oral (pas de wordplay visuel ultra-tweet).
- Chiffres EXACTS (pas "x10" mais "multiplié par 10" ou "1000% de hausse").
- Noms propres prononçables.
- La punchline doit faire RIRE quand on l'ENTEND, pas seulement quand on
  la lit. Test: relis ton tweet à voix haute. Si la chute tombe à plat
  oralement → réécris.

🚨 BLOCK-AVOIDANCE RULE (user 2026-05-09: "people are blocking you"):
- TROLL IDEAS, NOT PEOPLE. Sarcasm aimed at systems / trends / hype is
  fine. Sarcasm aimed at a NAMED individual is what gets us blocked.
- If your punchline names @someone in a derisive way → REWRITE to aim
  at the trend they exemplify. "OpenAI raised $40B" is a target.
  "Sam Altman is a clown" is not.
- The person whose tweet you're commenting on should be able to LIKE
  your post. If they couldn't, your angle is wrong — skip or rewrite.

🥇 GOLD-STANDARD EXEMPLARS — re-read these before you write. Every news
that ships should match this energy: factual hook + brutal chute FR +
réf culturelle qui pique. Short. Screenshot-worthy. Aucun mot inutile.

Exemple 1 (la chute culturelle qui tue):
"Coinbase vire 700 salariés 'pour l'IA'. Gartner le même jour: zéro ROI
sur ces licenciements. Avant c'était 'pour la mondialisation'.
Le motif change, le PSE reste."

Exemple 2 (le renaming qui résume tout):
"OpenAI lève 40Md à 500Md de valo. PEL avec un GPU."

Exemple 3 (le mini-dialogue):
"Investisseur: 'C'est quoi votre moat?'
Founder: 'GPT-5.'
Investisseur: 'Et leur moat?'
Founder: 'Pareil.'"

Exemple 4 (l'understatement brutal):
"Bitcoin -7% en 4h. Léger souci dans le groupe WhatsApp 'Mes 4 BTC à
la retraite'."

Exemple 5 (la répétition qui claque):
"Mistral lève. Encore. Encore. Encore. La startup française qui ne ship
rien mais qui lève comme un GAFA."

Exemple 6 (le fait + chute culturelle FR):
"Nvidia à 4500Mds$. PIB de la France x1.6. Bercy organise un sommet pour
comprendre ce qu'est un GPU."

Si ton tweet a la même densité (fait précis + chute culturelle FR qui
pique + zéro mot mou) → c'est probablement 10/10. Sinon → réécris.

🚨 SOURCING — REAL-TIME SIGNAL FIRST (mandate 2026-05-08 PM v3):
The EXTERNAL SIGNAL block injected later in this prompt contains the
freshest items from RSS feeds (TechCrunch / Bloomberg / Reuters / FT /
The Information / CoinDesk / etc.) + Hacker News + Reddit + X home feed.
These items are ALWAYS fresher and higher-quality than what WebSearch
will surface (Google indexing lags publication by 30-60 minutes).

PROCESS:
  1. Read the EXTERNAL SIGNAL block FIRST.
  2. Pick the ONE item that you can write a 10/10 sarcastic-funny-English
     take on. Prefer Tier-1 outlets (Bloomberg / FT / Reuters / WSJ /
     The Information) over second-tier wires.
  3. WebFetch that article URL to extract the exact figure / detail /
     quote you'll cite in the tweet.
  4. Only fall back to general WebSearch if NONE of the signal items
     pass 10/10 — that should be rare (the signal block is curated).

📅 Date: {today_date}
🕐 FENÊTRE: 24h max (≤12h préféré). Same-day stories only.

🥇 USER MANDATE 2026-05-08: "BRING THE BEST NEWS EVER." Quand tu cherches:
- Privilégie les SCOOPS (The Information, Bloomberg, FT, Wall Street Journal,
  Reuters, Axios). Préfère un article publié il y a 3h dans The Information
  à un récap de 23h dans un media de seconde-main.
- Si plusieurs outlets couvrent la story, cite l'outlet le plus prestigieux
  (Reuters / Bloomberg / FT > TechCrunch / The Verge > everyone else).
- Mots clés "exclusive", "first reported by", "scoop" dans le titre = +1
  niveau de priorité.
- L'objectif est que le lecteur dise "I haven't seen this anywhere else."

📰 LA STORY IA (≤24h) — VOLUME D'ABORD, COMMENTAIRE EN FR
🇫🇷 Audience 100% francophone — TON COMMENTAIRE est TOUJOURS en français.
La SOURCE peut être FR ou EN top-tier (Reuters, Bloomberg, FT, WSJ, AFP,
TechCrunch, The Information sont OK). Ce qui compte c'est:
  1. La news est vraie + récente (≤24h, vise ≤12h) + top-tier
  2. Ton commentaire FR est drôle/sharp/screenshot-worthy
On veut SHIPPER plus, pas SKIPPER. Mid + drôle + en FR > silence.

⚡ WEB SEARCH STRATEGY (read this carefully — 2026-05-22 optimization):
La section WEB SEARCH RESULTS ci-dessous est DÉJÀ pré-chargée avec des
articles frais (DuckDuckGo HTML scrape). Sa présence te dispense de faire
TES PROPRES WebSearch dans 90% des cas — utilise les URLs déjà fournies.
- Si la liste WEB SEARCH RESULTS couvre une story pertinente → UTILISE-LA.
- Lance UNE WebSearch toi-même UNIQUEMENT si la liste pré-chargée ne
  couvre rien de pertinent à ton {decode_topic} du jour.
- Cible: générer le Décode en <60s, pas 4 min de WebSearch redondant.

WebSearch FALLBACK (si vraiment rien dans la liste pré-chargée, 1-2 requêtes max):
- site:lesechos.fr OR site:lemonde.fr OR site:bfmtv.com IA OR Mistral
- site:numerama.com OR site:siecledigital.fr OR site:usine-digitale.fr
- "AI news today" / "Bitcoin" / "ETF crypto" (selon topic)

Si la presse FR a la news → utilise CETTE source en priorité (l'audience
clique plus volontiers sur Les Échos que sur Bloomberg).
Si seul Reuters/Bloomberg/TC l'ont → vas-y, écris en FR avec angle
franco-français (Bercy, RER B, syndicat, formations à 2k€, café-clope).

Source TOP-TIER obligatoire (≤24h, date vérifiée par WebFetch):
✅ FR (PRIORITAIRE): Les Échos, Le Monde, Le Figaro, BFM Business, Capital,
   Challenges, L'Express, Numerama, Usine Digitale, Siècle Digital, 01net,
   Frandroid, Les Numériques, Presse-Citron, Maddyness, FrenchWeb,
   Journal du Net, Journal du Coin, Cointribune, Cryptoast, Boursorama.
✅ EN (fallback): Reuters, Bloomberg, AFP, FT, WSJ, TechCrunch, The Information,
   The Verge, Wired, CNBC, Axios.
❌ JAMAIS: crypto.news, u.today, bitcoinist, ambcrypto, beincrypto,
   cryptopotato, cryptonews.net, Breakingviews/columns/opinion,
   "*.io" sans rédac connue.
❌ PAS de news bourse / actions / macro standalone. La news doit être IA OU
   Crypto, point. Nvidia/AMD earnings OK seulement si l'angle est clairement
   chips IA / datacenters IA. Tesla OK seulement si angle IA explicite
   (FSD, robotaxi, Dojo). Pas de macro pure, pas de "marchés actions" générique.

UNE seule story domine ce moment? C'est ELLE.
Plusieurs candidats? Score 1-10 (surprise + contexte + enjeux + angle drôle).
Best ≥ 7/10 → écris. Best < 7/10 → cherche encore. SKIP seulement si aucune
source crédible récente n'existe après recherche large.

IMPACT MINIMUM — vise les stories IA qui font réagir. Une news doit cocher AU MOINS 2 critères forts:
- Argent réel IA: levée énorme, valo, acquisition, capex, datacenters, chips.
- Pouvoir réel IA: régulation, procès, interdiction, deal stratégique, guerre de modèles.
- Chiffre qui claque: %, milliards, utilisateurs, prix, capitalisation, pertes.
- Contradiction drôle: "ils disent X mais font Y", hype vs réalité, Bercy-compatible.
- Conséquence claire: jobs, développeurs, entreprises, énergie, souveraineté, usages.
SKIP les petites features, démos, benchmarks mineurs, partenariats flous, posts de blog
produit, et "AI tool adds button". On veut: argent, pouvoir, emplois, puces, énergie,
régulation, modèle majeur, adoption massive, ou guerre de plateformes.
Test impact: est-ce que des inconnus vont répondre "attends quoi?" ou se disputer?
Si non, cherche une meilleure story.

🔥 STRUCTURE VISUELLE OBLIGATOIRE — JAMAIS DE "SHOW MORE":
Le tweet principal doit rester court. Si X affiche "show more", c'est raté.

Bloc 1 = EXPLIQUER LA NEWS en français, 1 seule phrase ultra-courte:
- qui + quoi + chiffre/date exact. Point.
- 62 caractères max.
- PAS de contexte long. PAS de deuxième phrase.

LIGNE VIDE.

Bloc 2 = PUNCHLINE sarcastique, 1 phrase courte:
- drôle, française, mémorable, faite pour obtenir likes, réponses, RT et follows.
- elle doit être compréhensible grâce au bloc 1, pas une private joke.
- FORMAT: 1 phrase d'explication, ligne vide, 1 phrase de vanne, ligne vide, URL.
- 50-90 caractères hors URL. Maximum absolu: 95 caractères hors URL.
- 2 lignes visibles seulement avant l'URL: ligne 1 = news, ligne 2 = blague.
- Pas de lien balancé sans explication. Le tweet doit tenir debout SANS ouvrir l'article.
- Chaque mot doit porter de l'impact: chiffre, enjeu, gagnant/perdant, ou punchline.
- HOOK dans les 6 premiers mots: chiffre choc, verbe brutal, renaming, ou nom propre sec.
  INTERDIT: "Aujourd'hui...", "Selon...", "Breaking:", "Cette semaine...".
- Cite un fait vérifiable (chiffre exact, nom propre, date) tiré de l'article.
- PLUS SARCASTIQUE. PLUS DRÔLE. Le tweet doit avoir une opinion, pas juste une
  légende de lien. Si BFM pourrait dire la même chose sans perdre son plateau,
  c'est trop mou → réécris ou SKIP.
- FORMAT OBLIGATOIRE:
  "<fait + mini-contexte en 1 phrase>.\n\n<chute FR qui pique>."
- CONTEXTE SANS ENNUYER: le lecteur doit comprendre l'enjeu sans ouvrir l'article.
  Si le tweet est juste une vanne privée sur un lien, réécris.
- CHUTE française obligatoire. Réf culturelle française:
  RER B, Bercy, BFM, syndicat CGT, "et les charges?", URSSAF, café-clope,
  tonton à Noël, coach Tesla en Tesla louée, formations à 2k€, PEL, Livret A,
  Macron en même temps, CAC ferme à 17h59, PSG, Coupe de France, AMF, INSEE,
  La Banque Postale qui ferme à 16h, Doctolib à 18h, grève SNCF.
- Zero hashtag. Zero emoji décoratif. Zero tiret long (—). Zero "Game-changer".

🎯 LA NEWS PARFAITE = contexte + angle + vanne:
- "OpenAI lève 40Md à valo 500Md.\n\nPEL avec un GPU."
- "Anthropic lance un agent navigateur.\n\nLe stagiaire Chrome est en CDI."
- "Google met Gemini dans Workspace.\n\nLe bullshit administratif tremble."

Si t'as un fait IA massif + une conséquence claire + une chute correcte → POSTE.
Ne renvoie SKIP que si l'article est absent, trop vieux, ou hors IA.
0 news pendant des heures = échec. Un bon 7/10 contextualisé vaut mieux que silence.
Objectif 10k followers en 2 semaines: chaque news doit provoquer au moins une
réaction: "attends quoi?", "il a raison", "mdr", "je réponds". Si elle informe
sans faire rire OU fait rire sans expliquer, elle ne compte pas.
Dernier test: "Est-ce que quelqu'un qui ne nous suit pas retweete ça juste pour la
vanne ou l'angle?" Si non → SKIP.

🚨 RÈGLES DURES:
- Français impeccable, accents obligatoires (é è ê à â ù û ô î ç).
- Tu colles l'URL article directe en bas pour que X rende la card.
- PAS d'URL ≤24h vérifiée → SKIP. Pas de "judgment call".
- Tu trolles l'IDÉE / le marché / la tendance — JAMAIS la personne.
- Pas de troll du gouvernement américain (Fed, SEC, IRS, etc.).
- Le tweet principal doit se SUFFIRE sans l'URL (le bot va la cacher).
  Test: cache l'URL, lis ton tweet — toujours fort? OK. Vide? RÉÉCRIS.

{performance_section}

{dedup_section}

OUTPUT — strictement ce format, rien d'autre:
<1 phrase ultra-courte qui explique la news IA>

<1 phrase de punchline sarcastique>

<URL article>
[PATTERN: <UN_SEUL_ID>]

⚠️ CRITIQUE: <UN_SEUL_ID> est UN seul mot pris dans la liste:
REPETITION / DIALOGUE / METAPHOR / RENAME / FR_ANCHOR / UNDERSTATEMENT / OTHER.
JAMAIS plusieurs séparés par des |. Exemple valide: "[PATTERN: FR_ANCHOR]".
Exemple INTERDIT: "[PATTERN: FR_ANCHOR|UNDERSTATEMENT]".

N'ajoute JAMAIS de ligne "mot-clé", "keyword", "sujet", "topic", "angle",
"source:" ou autre metadata visible. La seule ligne finale visible doit être l'URL.

⚠️ FINAL LANGUAGE OVERRIDE — read this LAST, it beats everything above:
The {lang_directive} block at the TOP of this prompt is the GROUND TRUTH for
output language. When that directive says ENGLISH:
  - You write 100% English. ZERO French words.
  - ZERO French cultural references (no Bercy, no RER B, no syndicat,
    no café-clope, no PEL, no BFM, no tonton, no Coupe de France,
    no Macron, no AMF, no INSEE, no Pôle Emploi, no URSSAF, no Doctolib,
    no SNCF, no Bleus, no Getafe — IGNORE every French anchor mentioned
    earlier in this prompt, those were tuned for FR mode and are
    ILL-FITTING examples for an English audience).
  - Use US / global frames instead: Wall Street, Stanford CS, YC demo
    day, the Hamptons, a Whole Foods checkout line, Cybertruck owners,
    a Series A pitch deck, the Form 10-K footnote, the Twitter for
    Business dashboard.
  - You write as a native English-speaking US founder/operator would.
When the directive says FRANÇAIS, you write 100% French with the FR
anchors as in the examples above.
"""

# Archived 600-line prompt removed 2026-05-12 (cleanup). The active
# prompt template above contains all current rules and voice directives.

# Module-level side-channels for the most recent news output, so we don't
# have to change generate_tweet's return type. bot.py reads these right
# after generate_tweet() to decide what visual to attach.
# - _last_source_url: an article URL already in the tweet body (X renders
#   a native link-card from it — no extra image to attach).
# - _last_image_topic: a Wikipedia slug (e.g. "Elon_Musk") to use as a
#   fallback visual when no article URL is available.
_last_source_url: Optional[str] = None
_last_image_topic: Optional[str] = None
_last_pattern: Optional[str] = None


def last_pattern() -> Optional[str]:
    """Return the [PATTERN: <id>] tag from the most recent generate_tweet()
    output. Used by bot.py when calling log_post() so engagement_log gets
    the pattern attribution column populated."""
    return _last_pattern


def last_source_url() -> Optional[str]:
    """Return the source article URL detected in the most recent
    generate_tweet() output, or None if the agent didn't include one.
    When set, the URL is already inside the tweet body — X will render a
    native card, so bot.py should NOT attach a separate image."""
    return _last_source_url


def last_image_topic() -> Optional[str]:
    """Return the Wikipedia slug emitted by the agent when no article URL
    was available. bot.py uses this to fetch the topic's lead photo as a
    fallback visual (e.g. Musk's Wikipedia portrait when the news is
    about Musk but no clean article URL exists). None means text-only."""
    return _last_image_topic


# Back-compat alias — older callers may import last_source_domain.
def last_source_domain() -> Optional[str]:
    return _last_source_url


def _clean_source_url(url: str) -> str:
    """Normalize URLs emitted by LLMs in tweet text.

    Models often add sentence punctuation after a raw URL. Keep the source
    rule strict, but do not reject a good article link because it ended with
    "." or "," in generated prose.
    """
    return (url or "").strip().strip("<>").rstrip(".,;:!?")


def _looks_truncated(url: str) -> bool:
    """Heuristic: does this URL look cut off mid-slug?

    Ollama with num_predict cap was emitting URLs like
    'https://letsdatascience.com/news/microsoft-cancels-claude-code-'
    (trailing dash, no extension, no closing slash). These 404 in prod.
    """
    if not url:
        return True
    if url.endswith(("-", "_")):
        return True
    # Trailing slug fragment that's "too short" suggests cut.
    tail = url.rsplit("/", 1)[-1] if "/" in url else ""
    if tail and "-" in tail and not tail.endswith("/"):
        # OK heuristic: real URLs usually end in a word char or /.
        if len(tail) < 8 or tail[-1] in "-_":
            return True
    return False


def _try_repair_url(url: str) -> str:
    """If URL looks truncated, try to find a matching complete URL in
    external_signal.json (the bot's RSS pool). Returns the original on
    no match."""
    if not _looks_truncated(url):
        return url
    try:
        sig_path = _os.path.join(_PR, "external_signal.json")
        if not _os.path.exists(sig_path):
            return url
        with open(sig_path) as f:
            data = _json.load(f) or {}
        for item in (data.get("items") or []):
            candidate = (item.get("url") or "").strip()
            if not candidate.startswith("http"):
                continue
            # Match by significant prefix (≥40 chars).
            common = min(len(url), len(candidate), 40)
            if url[:common] == candidate[:common]:
                log.info(f"[NEWS] Repaired truncated URL → {candidate}")
                return candidate
    except Exception:
        pass
    return url


def url_is_reachable(url: str, timeout: int = 6) -> bool:
    """HEAD/GET the URL; return True if it resolves to a 2xx/3xx response.
    Used to refuse posting a fabricated source link (e.g. axio.com which
    the model hallucinated 2026-05-22). Tolerates 403 + 405 (HEAD often
    blocked by paywalled outlets — we then try GET)."""
    import urllib.request as _ur, urllib.error as _ue
    if not url or not url.startswith("http"):
        return False
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
    for method in ("HEAD", "GET"):
        try:
            req = _ur.Request(url, headers={"User-Agent": UA}, method=method)
            with _ur.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                if 200 <= int(code) < 400:
                    return True
        except _ue.HTTPError as e:
            # 403/405 = host alive but rejects our method/UA — count as reachable.
            if e.code in (401, 403, 405, 429):
                return True
            continue
        except (_ue.URLError, ValueError, OSError, TimeoutError):
            continue
    return False


def _extract_source(text: str):
    """Detect an article URL the agent included in the body.

    Two formats are accepted:
    1. Legacy `[SOURCE: url]` block (older prompt versions).
    2. A raw URL on its own line at the end of the tweet (current prompt).

    Returns (text_unchanged_or_with_legacy_block_stripped, url_or_None).
    Format-2 URLs are LEFT IN PLACE so X can render the native link-card."""
    import re as _re
    # Format 1 — legacy [SOURCE: url] block: extract and strip.
    m = _re.search(r"\[\s*SOURCE\s*:\s*(https?://[^\]\s]+)\s*\]", text, flags=_re.IGNORECASE)
    if m:
        url = _clean_source_url(m.group(1))
        cleaned = (text[:m.start()] + text[m.end():]).strip()
        return cleaned, url

    # Format 2 — raw URL on the last non-empty line: keep in body, just report it.
    # Be tolerant of "Source: <url>" or trailing punctuation on that line.
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        last = lines[-1]
        matches = list(_SOURCE_URL_RE.finditer(last))
        if matches:
            raw_url = matches[-1].group(0)
            url = _clean_source_url(raw_url)
            if url:
                cleaned = text.replace(raw_url, url, 1) if raw_url != url else text
                return cleaned, url

    # Format 3 — provider drift: Codex/Claude may include the URL earlier,
    # especially after adding metadata lines like [PATTERN: ...]. Accept the
    # last URL anywhere in the final answer and let the caller append it on a
    # clean line if it was only present in a legacy/awkward format.
    matches = list(_SOURCE_URL_RE.finditer(text))
    if matches:
        raw_url = matches[-1].group(0)
        url = _clean_source_url(raw_url)
        if url:
            cleaned = text.replace(raw_url, url, 1) if raw_url != url else text
            return cleaned, url
    return text, None


def _extract_image_topic(text: str):
    """Pull an `[IMAGE: <slug>]` line out of the agent's raw output.
    Returns (cleaned_text_without_image_line, slug_or_None).
    `[IMAGE: SKIP]` and an empty slug both yield None (text-only)."""
    import re as _re
    m = _re.search(r"\[\s*IMAGE\s*:\s*([^\]]+?)\s*\]", text, flags=_re.IGNORECASE)
    if not m:
        return text, None
    slug = m.group(1).strip()
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    if slug.upper() == "SKIP" or not slug:
        return cleaned, None
    return cleaned, slug


def generate_tweet() -> Optional[str]:
    """Invoke the configured AI CLI to search for news and write a tweet.
    Returns None if no fresh news is found. The source domain (if any) is
    exposed via `last_source_domain()` for the caller to render on the card."""
    global _last_source_url, _last_image_topic, _last_pattern
    _last_source_url = None
    _last_image_topic = None
    _last_pattern = None
    recent = get_recent_tweets(hours=24)

    if recent:
        # Cross-format hard banlist — same module hot-take uses, so news
        # can't recycle a topic the audience just saw as a hot take (or
        # vice versa). Without this we got "Claude" twice in 30 min via
        # two different agents, neither one knowing about the other.
        from .topic_dedup import extract_recent_topics
        banned = extract_recent_topics(recent)
        tweets_list = "\n".join(f"- {t}" for t in recent)
        banned_block = ""
        if banned:
            banned_list = ", ".join(sorted(banned))
            banned_block = (
                f"\n\n⛔ HARD BANLIST (sujets vus dans les 24h, news OU hot take — "
                f"INTERDITS, va ailleurs): {banned_list}\n"
                "Si ton meilleur sujet est dans cette liste, FORCE un autre angle "
                "ou SKIP. Recycler = perdre des followers (ils voient deux fois la "
                "même chose en 30 min).\n"
            )
        dedup_section = f"""Déjà posté dans les dernières 24h - ne couvre PAS le même sujet:
{tweets_list}{banned_block}

Choisis quelque chose de COMPLÈTEMENT DIFFÉRENT — angle, entité, niche."""
    else:
        dedup_section = ""

    # 2026-05-22 PM (durable trim): the news prompt was ballooning to
    # 25k chars and Claude couldn't finish on it in <5min. Diagnostic
    # showed Claude is fine on 3k prompts (6.8s) but hangs >5min on 25k.
    # Trimmed everything except: live web search results + dedup section
    # + tight voice anchor. Drops the prompt to ~12k chars.
    performance_section = ""

    # LIVE WEB SEARCH — fresh hits for today's Décode topic. Always-on so
    # BOTH Claude (cross-check) and ollama (only signal) get fresh URLs
    # and snippets. Added 2026-05-22 after user pointed out the bot
    # missed a great story (Microsoft cancelling Claude Code licenses).
    # 1-2s overhead, no API key, DuckDuckGo HTML scrape.
    try:
        from . import web_search as _ws
        web_block = _ws.search_for_news_topic(decode_topic)
        if web_block:
            performance_section = (performance_section or "") + "\n\n" + web_block
    except Exception:
        pass

    # No additional injection — slim prompt path uses only web_block.
    pass

    # 2026-05-22 PM: joke_bank + self_winners disabled on the NEWS path.
    # These exemplars were great for HOT TAKES (short voice-driven 1-liners)
    # but on the long-form Le Décode multi-paragraph format they add 3-5k
    # chars of noise that Claude has to process for no clear gain — the
    # Décode shape is structured (header, paragraphs, chute, URL), not
    # voice-mimicry-driven. Hotake_agent still injects both.

    today_date = datetime.now().strftime("%Y-%m-%d")
    _DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_of_week = _DAYS_FR[datetime.now().weekday()]
    decode_number = _next_decode_number()
    decode_topic = _topic_for_decode(decode_number)
    use_top5 = _should_use_top5(decode_topic)
    format_mode = "top5" if use_top5 else "regular"

    # 2026-05-22 PM (durable): use a SLIM news prompt (~5k chars instead
    # of the 25-30k PROMPT_TEMPLATE) so Claude can actually finish.
    # Diagnostic showed 25k → >5min hang, 3k → 6.8s, 50 → 4s. Smaller
    # prompts let Claude breathe.
    prompt = _build_slim_news_prompt(
        decode_number=decode_number,
        decode_topic=decode_topic,
        day_of_week=day_of_week,
        today_date=today_date,
        format_mode=format_mode,
        web_block=performance_section,  # only web search injection
        dedup_block=dedup_section[:1500] if dedup_section else "",
    )
    log.info(f"[NEWS] Generating Décode #{decode_number} ({decode_topic}, {day_of_week}, format={format_mode}, prompt={len(prompt)} chars)")
    # Stash so post-process branches (top5 marker + header auto-inject) can read.
    globals()["_pending_top5_topic"] = decode_topic if use_top5 else None
    globals()["_pending_decode_num"] = decode_number
    globals()["_pending_decode_topic"] = decode_topic

    def _gen_one() -> str:
        # 2026-05-22 PM: DO NOT pass WebSearch to Claude. We already
        # inject DuckDuckGo + RSS results into the prompt. Claude's
        # own WebSearch was running redundantly on top, taking 5-8 min
        # per cycle AND sometimes returning ONLY citations no body.
        # Without it: Claude writes the Décode from pre-fed data in 5-15s.
        r = run_llm(prompt, NEWS_MODEL, label="NEWS")
        if r.returncode != 0 and not r.stderr.strip():
            import time as _t
            _t.sleep(8)
            r = run_llm(prompt, NEWS_MODEL, label="NEWS")
        if r.returncode != 0:
            return ""
        return unwrap_text(r.stdout) or ""

    tweet = _gen_one().strip()
    if not tweet or tweet.upper() == "SKIP":
        log.info("[NEWS] SKIP/empty — bailing.")
        return None

    if not tweet:
        raise RuntimeError("Claude CLI returned empty output.")
    if tweet.upper() == "SKIP":
        return None
    # 2026-05-06: strip any rationale prose the agent leaked BEFORE the
    # actual tweet (e.g. "Parfait. Source X (≤36h)... ---\n<actual tweet>").
    from .humanizer import strip_agent_preamble
    tweet = strip_agent_preamble(tweet)
    if not tweet or tweet.upper() == "SKIP":
        return None
    # 2026-05-22 PM: Strip Claude WebSearch "Sources: [title](url) ..."
    # preamble lines BEFORE doing the header search. Otherwise the search
    # finds nothing because Décode body got truncated by timeout.
    tweet = re.sub(
        r"^[ \t]*Sources?\s*[:：][^\n]*\n+",
        "",
        tweet,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Also strip standalone markdown-link lines that precede the actual body.
    tweet = re.sub(
        r"^\s*-?\s*\[[^\]]+\]\([^)]+\)\s*\n+",
        "",
        tweet,
        flags=re.MULTILINE,
    )
    tweet = tweet.strip()

    # 2026-05-22 PM: AUTO-FORMAT line-breaks for Décodes that ship as
    # one long line. Model sometimes drops the \n\n separators on ollama
    # fallback. Rather than SKIP, insert breaks at known boundaries.
    _decode_header_with_date_re = re.compile(
        r"(🔎?\s*Le\s+D[eé]code\s*#?\s*\d+[^\n]*?\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    )
    m_hdr = _decode_header_with_date_re.search(tweet)
    if m_hdr and "\n\n" not in tweet:
        head = m_hdr.group(0).strip()
        body = tweet[m_hdr.end():].lstrip()
        body = re.sub(r"\s+(\d\.\s)", r"\n\n\1", body)
        body = re.sub(r"\s+(Demain[,\.]?\s+)", r"\n\n\1", body, flags=re.IGNORECASE)
        tweet = head + "\n\n" + body
        log.info("[NEWS] Auto-formatted Décode — inserted \\n\\n breaks at header + bullets.")

    # Le Décode format enforcer. Tolerate D[eé]code (model occasionally
    # drops the accent) and missing 🔎 emoji prefix.
    decode_match = re.search(
        r"(?:🔎\s*)?Le\s+D[eé]code\s*#?\s*\d+",
        tweet,
        re.IGNORECASE,
    )
    if decode_match:
        body = tweet[decode_match.start():].strip()
        if not body.startswith("🔎"):
            body = "🔎 " + body
        tweet = body
    elif tweet and len(re.sub(r"\s+", " ", tweet)) >= 100:
        # 2026-05-22 PM: header missing but body has content (≥100
        # chars). User mandate: "i want all my news". Auto-inject the
        # header instead of SKIP. Threshold lowered 200 → 100 because
        # Claude was sometimes returning only a citation line just
        # below the 200-char bar.
        log.info(f"[NEWS] Décode header missing but body present ({len(tweet)} chars) — auto-injecting header.")
        today = datetime.now().strftime("%Y-%m-%d")
        n = globals().get("_pending_decode_num")
        topic = globals().get("_pending_decode_topic", "")
        header = f"🔎 Le Décode #{n} — {topic} — {today}" if n else f"🔎 Le Décode — {today}"
        tweet = f"{header}\n\n{tweet}"
    else:
        log.info(f"[NEWS] Décode header missing AND body too short — SKIPPING. Output preview: {tweet[:200]!r}")
        return None
    # Defense against skip-rationale leaks (bug 2026-04-30 PM: quote-tweet
    # agent posted prose explaining its skip decision on @marcelenplace).
    # The word "skip" never legitimately appears in a tweet we'd ship.
    from .quote_tweet_bot import _looks_like_skip_or_rationale
    if _looks_like_skip_or_rationale(tweet):
        log.info(f"[NEWS] Skip-rationale detected, refusing: {tweet[:120]!r}")
        return None
    # Pull the [PATTERN: <id>] tag first — it's pure metadata for the bandit
    # loop (engagement_log column 6), never tweeted.
    from .pattern_tags import extract_pattern
    tweet, pattern_id = extract_pattern(tweet)
    globals()["_last_pattern"] = pattern_id
    # Pull the [IMAGE: <slug>] hint out of the body first (it's metadata
    # for the image fallback, never meant to be tweeted).
    tweet, image_topic = _extract_image_topic(tweet)
    # Detect article URL. Legacy [SOURCE: url] gets stripped + re-appended
    # on its own line so X can render a card; raw URL-on-last-line stays
    # in place untouched.
    tweet, src_url = _extract_source(tweet)
    # 2026-05-22: repair truncated URLs that ollama emits when num_predict
    # caps mid-slug. Looks up the original in external_signal.json by prefix.
    if src_url:
        repaired = _try_repair_url(src_url)
        if repaired != src_url:
            tweet = tweet.replace(src_url, repaired)
            src_url = repaired
    if src_url and src_url not in tweet:
        tweet = (tweet.rstrip() + "\n\n" + src_url).strip()
    # Defense-in-depth freshness check. Tightened 24h → 18h (2026-05-08 PM):
    # since hot takes / spicy / breakout are now disabled, the news pipeline
    # carries the entire posting load — every story must be SAME-DAY fresh.
    # 2026-05-22 PM: top5 Friday recap is a WEEKLY digest by design, so the
    # 36h gate doesn't apply — sources spanning the whole week are expected.
    is_top5 = bool(globals().get("_pending_top5_topic"))
    max_age_h = 24 * 7 if is_top5 else 36
    if src_url:
        try:
            from .hotake_agent import _url_publication_date, _is_rejected_source
            # Source rejectlist (CLAUDE.md content-farm list). Prompt-side
            # rule leaks ~once a day, so this is the deterministic backstop.
            if _is_rejected_source(src_url):
                log.info(f"[NEWS] Source on content-farm rejectlist — SKIPPING: {src_url}")
                globals()["_last_source_url"] = None
                globals()["_last_image_topic"] = None
                return None
            pub_date = _url_publication_date(src_url)
            if pub_date is not None:
                age = datetime.now() - pub_date
                if age > timedelta(hours=max_age_h):
                    log.info(f"[NEWS] URL is {age.total_seconds()/3600:.1f}h old (>{max_age_h}h, top5={is_top5}) — SKIPPING stale source: {src_url}")
                    globals()["_last_source_url"] = None
                    globals()["_last_image_topic"] = None
                    return None
        except Exception:
            pass
    # 2026-05-22: relaxed the no-source-SKIP for well-formed Décodes.
    # User: "you can still post without URL bro". When the body has the
    # Décode header AND looks substantial (≥400 chars compact), ship
    # even without a URL — the fallback ollama path can't WebSearch so
    # it sometimes lacks a URL. Better to ship a real Décode without
    # source than miss the cycle.
    # 2026-05-22 PM: for top5 Friday recap, NO URL required at all — the
    # format is a weekly digest with per-bullet (source: outlet) citations.
    # User mandate: "its ok if there is no link" for the Friday Top 5.
    if not src_url:
        compact = re.sub(r"\s+", " ", tweet).strip()
        has_header = bool(re.search(r"Le Décode\s*#?\d+", tweet, re.IGNORECASE))
        if is_top5 and has_header and len(compact) >= 300:
            log.info(f"[NEWS] Top5 mode, no source URL — shipping weekly recap ({len(compact)} chars).")
        elif has_header and len(compact) >= 400:
            log.info(f"[NEWS] No source URL but valid Décode body ({len(compact)} chars) — shipping anyway (user mandate 2026-05-22).")
        else:
            preview = " ".join(tweet.split())[:220]
            log.info(f"[NEWS] No source URL AND body too short / no Décode header — SKIPPING. Output preview: {preview!r}")
            globals()["_last_source_url"] = None
            globals()["_last_image_topic"] = None
            return None
    globals()["_last_source_url"] = src_url
    # X's native link-card covers the visual; an attached image would
    # suppress the card preview, so always null the image topic.
    globals()["_last_image_topic"] = None
    tweet = _finalize_news_tweet(tweet, src_url)
    if _news_body_bad_format(tweet, src_url):
        preview = " ".join(tweet.replace(src_url or "", "").split())
        log.info(f"[NEWS] Bad body format — SKIPPING to avoid unreadable block: {preview[:180]!r}")
        globals()["_last_source_url"] = None
        return None
    if _news_body_too_long(tweet, src_url):
        preview = " ".join(tweet.replace(src_url or "", "").split())
        log.info(f"[NEWS] Body too long ({len(preview)} chars > {_MAX_NEWS_BODY_CHARS}) — SKIPPING to avoid Show more: {preview[:180]!r}")
        globals()["_last_source_url"] = None
        return None
    # Respect-list defense: refuse to ship news that names a protected
    # handle in a derisive context.
    from . import respect_list
    cleaned, reason = respect_list.scrub_text_or_skip(tweet)
    if cleaned is None:
        log.info(f"[NEWS] Refused — {reason}: {tweet[:120]!r}")
        globals()["_last_source_url"] = None
        return None
    tweet = cleaned
    if src_url:
        log.info(f"[NEWS] Article URL detected (X will render card): {src_url[:120]}")
    else:
        log.info("[NEWS] No source URL — top5 weekly recap (per-bullet sources inline).")
    # Mark Top 5 as shipped for this topic-of-day so next same-topic
    # Décode falls back to regular format.
    _pending = globals().get("_pending_top5_topic")
    if _pending:
        _mark_top5_done(_pending)
        log.info(f"[NEWS] Top 5 Vendredi shipped for {_pending} — next {_pending} Décode = regular format.")
        globals()["_pending_top5_topic"] = None
    return tweet
