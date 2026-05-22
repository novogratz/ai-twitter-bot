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
    return (body.rstrip() + "\n\n" + src_url).strip()


def _news_body_too_long(tweet: str, src_url: str) -> bool:
    """Keep news posts below X's collapsed-text threshold (approx 240-280)."""
    body = (tweet or "").replace(src_url or "", "")
    body = re.sub(r"\s+", " ", body).strip()
    return len(body) > _MAX_NEWS_BODY_CHARS


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

    # New long-form Décode shape: 500-1400 chars body, multi-paragraph,
    # blank-line breaks. Bullets optional now (prose is encouraged).
    if has_header and has_blank_break and 500 <= compact_len <= 1400:
        # Sanity-check no individual paragraph is over the line cap
        # (paragraphs can be long, but no single line should be a wall).
        return any(len(line) > _MAX_NEWS_LINE_CHARS * 3 for line in non_empty)

    # Permissive fallback: 2-3 blocks separated by blank lines, classic format.
    if has_blank_break and 2 <= len(non_empty) <= 10 and compact_len <= 1400:
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

    perf = get_learnings_for_prompt()
    performance_section = ""
    if perf:
        performance_section = f"""==================================================
APPRENDS DE TES PERFORMANCES
==================================================

{perf}

UTILISE CES DONNÉES. Écris plus comme tes meilleurs tweets. Évite les patterns de tes pires."""

    # Autonomous evolution agent's directives (regenerated every 12h from
    # actual engagement data). Loaded at runtime — empty on first run.
    from .evolution_store import get_directives_block
    directives_block = get_directives_block()
    if directives_block:
        performance_section = (performance_section or "") + directives_block

    # External-signal injection — RSS + HN + Reddit + X home merged into
    # external_signal.json. Leads Google/WebSearch by 20-50 min so this
    # is often the first place we see what tomorrow's wire will cover.
    try:
        from . import hn_signal_bot
        ext = hn_signal_bot.render_signal_block(max_items=10)
        if ext:
            performance_section = (performance_section or "") + "\n\n" + ext
    except Exception:
        pass

    # CANDIDATE ARTICLE URLS — for the fallback case when ollama runs
    # (it can't WebSearch). Extract real article URLs from external_signal.json
    # (filter out X status URLs which aren't acceptable sources) and surface
    # them as a pickable list. Added 2026-05-22 after Décode #60 SKIP'd
    # because ollama fallback had no URL to attach.
    try:
        sig_path = _os.path.join(_PR, "external_signal.json")
        if _os.path.exists(sig_path):
            with open(sig_path) as f:
                sig = _json.load(f) or {}
            items = sig.get("items") or []
            article_urls = []
            for it in items:
                u = it.get("url") or ""
                if not u.startswith("http"):
                    continue
                # Skip X status URLs and reddit/news.ycombinator (not articles)
                if any(d in u for d in ("x.com/", "twitter.com/", "reddit.com/", "news.ycombinator.com")):
                    continue
                title = (it.get("title") or "")[:120]
                article_urls.append(f"  - {u}  ({title})")
                if len(article_urls) >= 10:
                    break
            if article_urls:
                block = (
                    "==================================================\n"
                    "CANDIDATE ARTICLE URLS — picks de RSS récent (≤6h en général)\n"
                    "==================================================\n"
                    "Si tu ne peux pas WebSearch (modèle local), PIOCHE une URL\n"
                    "dans cette liste qui colle à ton angle. Préfère ces URLs aux\n"
                    "X status URLs (qui ne sont pas des sources d'article valides).\n\n"
                    + "\n".join(article_urls)
                )
                performance_section = (performance_section or "") + "\n\n" + block
    except Exception:
        pass

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

    # Follower growth scoreboard — concrete number the agent sees so it
    # can self-evaluate "is what I'm doing actually working".
    try:
        from . import follower_tracker_bot
        growth = follower_tracker_bot.get_growth_block()
        if growth:
            performance_section = (performance_section or "") + "\n\n" + growth
    except Exception:
        pass

    # Closed-loop pattern bandit — last 7 days of pattern winners/losers.
    try:
        from .performance import get_pattern_stats_block
        bandit = get_pattern_stats_block()
        if bandit:
            performance_section = (performance_section or "") + "\n\n" + bandit
    except Exception:
        pass

    # Personality store — global mood from accumulated dossiers + hard rules.
    from . import personality_store
    # Self-evolving bot identity (written by self_evolution_agent every few hrs).
    # This is the bot's ACTUAL state-of-mind, not a static voice anchor — it
    # drifts daily based on what the bot lived + what's happening in the world.
    bot_self = personality_store.render_bot_self()
    if bot_self:
        performance_section = (performance_section or "") + "\n\n" + bot_self
    mood = personality_store.render_global_mood()
    if mood:
        performance_section = (performance_section or "") + "\n\n" + mood
    # Hand-curated ideological core (core_identity.md) — voice anchor.
    core_identity = personality_store.render_core_identity()
    if core_identity:
        performance_section = (performance_section or "") + "\n\n" + core_identity
    performance_section = (performance_section or "") + "\n\n" + personality_store.hard_rules_block()

    # Auto-curated joke bank — top-liked recent posts injected as fresh
    # exemplars. Replaces hardcoded gold-standards with what's empirically
    # working RIGHT NOW. Added 2026-05-18 to fight prompt-staleness.
    try:
        from . import joke_bank
        jb = joke_bank.render_joke_bank_block(sample_size=5)
        if jb:
            performance_section = (performance_section or "") + "\n\n" + jb
    except Exception:
        pass
    # Self-winners — OUR own past posts that hit ≥10 likes. The model
    # learns what works for THIS specific account at THIS follower count.
    try:
        from . import self_winners
        sw = self_winners.render_self_winners_block(sample_size=3)
        if sw:
            performance_section = (performance_section or "") + "\n\n" + sw
    except Exception:
        pass

    today_date = datetime.now().strftime("%Y-%m-%d")
    _DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_of_week = _DAYS_FR[datetime.now().weekday()]
    decode_number = _next_decode_number()
    decode_topic = _topic_for_decode(decode_number)
    # Friday: only the FIRST Décode of each topic gets Top 5 format.
    # After IA + Crypto + Investissement each have their Top 5, rest go regular.
    use_top5 = _should_use_top5(decode_topic)
    format_mode = "top5" if use_top5 else "regular"
    from . import lang_mode
    lang = lang_mode.pick_content_lang()
    prompt = PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        today_date=today_date,
        day_of_week=day_of_week,
        decode_number=decode_number,
        decode_topic=decode_topic,
        format_mode=format_mode,
        performance_section=performance_section,
        lang_directive=lang_mode.lang_directive(lang),
    )
    log.info(f"[NEWS] Generating Décode #{decode_number} ({decode_topic}, {day_of_week}, format={format_mode}) in lang={lang}")
    # Stash so post-process branches (top5 marker + header auto-inject) can read.
    globals()["_pending_top5_topic"] = decode_topic if use_top5 else None
    globals()["_pending_decode_num"] = decode_number
    globals()["_pending_decode_topic"] = decode_topic

    def _gen_one() -> str:
        r = run_llm(
            prompt,
            NEWS_MODEL,
            label="NEWS",
            allowed_tools=["WebSearch"],
        )
        if r.returncode != 0 and not r.stderr.strip():
            import time as _t
            _t.sleep(8)
            r = run_llm(
                prompt,
                NEWS_MODEL,
                label="NEWS",
                allowed_tools=["WebSearch"],
            )
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
                if age > timedelta(hours=36):
                    log.info(f"[NEWS] URL is {age.total_seconds()/3600:.1f}h old (>36h) — SKIPPING stale source: {src_url}")
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
    if not src_url:
        compact = re.sub(r"\s+", " ", tweet).strip()
        has_header = bool(re.search(r"Le Décode\s*#?\d+", tweet, re.IGNORECASE))
        if has_header and len(compact) >= 400:
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
        preview = " ".join(tweet.replace(src_url, "").split())
        log.info(f"[NEWS] Bad body format — SKIPPING to avoid unreadable block: {preview[:180]!r}")
        globals()["_last_source_url"] = None
        return None
    if _news_body_too_long(tweet, src_url):
        preview = " ".join(tweet.replace(src_url, "").split())
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
    log.info(f"[NEWS] Article URL detected (X will render card): {src_url[:120]}")
    # Mark Top 5 as shipped for this topic-of-day so next same-topic
    # Décode falls back to regular format.
    _pending = globals().get("_pending_top5_topic")
    if _pending:
        _mark_top5_done(_pending)
        log.info(f"[NEWS] Top 5 Vendredi shipped for {_pending} — next {_pending} Décode = regular format.")
        globals()["_pending_top5_topic"] = None
    return tweet
