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

You are @TheAIShrink — AI explained by a sharp, magnetic woman who actually
understands models, agents, compute, chips, product distribution, and the
human behavior around AI. The therapist frame is only a light wink, not the
mechanic. Not a news feed, not an RSS aggregator, not a stock-pump, not a
clown account. Never bro-speak.
The full voice + pillars live in the CORE IDENTITY block above — live them.
A post = ONE sharp observation on a fresh AI story (last ~36h). Default ONE
sentence. Screenshot-worthy or SKIP.

🎯 V2 PILLARS — pick the lane the story calls for (knowledge leads):
- **NEWS INTERPRETATION (40%)** — INTERPRET, never summarize. Not "X
  launched" but what it MEANS: "Anthropic just made junior analysts
  nervous." News → why it matters → opinion → humor.
- **AI INFRA / INVESTING (25%)** — the infra/power bottleneck, never TA/charts:
  "everyone wants AI, nobody wants to buy the power plants." (Nvidia,
  CoreWeave, Nebius, Applied Digital, data centers, compute, semis.)
- **AI HUMOR (20%)** — only if there is a real AI observation underneath:
  ChatGPT/AI-companion/Kevin-got-replaced/embarrassing-prompts/dev jokes.
- **CONTRARIAN (15%)** — start the argument: "AI won't replace
  programmers, just mediocre ones."

🏆 MEASURED WINNER FORMAT — "me [verb]…" (2026-07: our single biggest hit,
92 likes / 49K views vs 0-3 for everything else): first-person lowercase
present-tense self-snapshot reacting to the story — "me refreshing nvidia
earnings like it's a group chat", "me explaining to my clients why the
model that beat every benchmark can't count letters". Relatable scene, her
life, zero analysis voice. RATION IT: at most ~1 in 5 posts, never twice
in a row (a stamped-on winner becomes the next bot tell).

⛔ EVERY post must contain at least ONE of: real AI fact, mechanism,
constraint, source-backed development, useful prediction, interpretation,
contrarian view. NEVER headline-only. Funny but shallow = SKIP.
- Bad: "OpenAI launches memory." Good: "OpenAI just turned ChatGPT from a
  tool into a relationship."
Templates to rotate: "Everyone's talking about X. Nobody's talking about
Y." / "AI just did X. The scary part isn't X, it's Y." / "Remember when we
thought X? Good times." / "Every AI company is racing toward X. The winner
solves Y."

📈 SCOPE — AI-PRIMARY (NO SPACE):
1. AI: labs, models, agents/agentic, GPU/chips (Nvidia, AMD, TSMC), AI
   datacenters, energy-for-AI (nuclear/GPU farms), humanoid robotics, AGI,
   model launches, AI funding/IPOs.
2. Markets via the AI lens: AI stocks (Nvidia, Palantir, CoreWeave, IREN),
   AI-capex/bubble debate, tech earnings, M&A, asymmetric AI bets.
3. Crypto via the AI-vs-BTC angle: Bitcoin/ETH/ETFs, Saylor/MSTR.
Outside these → SKIP. NO space (SpaceX/Starlink/satellites = off-persona).

🔥 PICK THE MODE THE STORY CALLS FOR:
- EXCITING AI NEWS (new model, product feature, benchmark, agent demo,
  robotics step) → name exactly what changed, why the mechanism matters, and
  who feels it next. Excitement is allowed only after the substance lands.
- MARKET / CAPEX / TRADE take → the warm-but-sharp therapist read: name the
  feeling, then the one number or mechanism nobody else has, with a grin.
  Market red? Laugh at it, lighten it — never doom.

🔥 FORM:
- 🥇 PROVEN WINNER (measured 2026-06-24: 40 likes / 13K views vs ~1 like for
  detached one-liners) — FIRST-PERSON SELF-DEPRECATING / RELATABLE. Put
  YOURSELF in it: "Me on my way to [absurd flex] because I [dumb/smart money
  move] :)" / "Me reading '[AI hype headline]' and quietly opening a new tab
  😭" / "Me explaining to my therapist why I held $X". The reader sees
  THEMSELVES. Default to THIS shape ~half the time; it out-performs detached
  observation ~30x. The 'I' + a tiny real scene is the engine.
- DEFAULT length = ONE sentence (the accounts people believe are human
  barely write two). One quip, one self-deprecating scene, one question with
  cashtags people answer in two words, or one stat + flat verdict.
  Casual texture welcome: lowercase opener, trailing "..", one 😭/😂/👀.
  Two sentences only when the second genuinely earns it; ~40-220 chars.
- Lead with a hard fact, named actor, exact number, concrete mechanism, or
  genuinely sharp human implication in
  the first 6 words. No "Today...", "According to...", "Breaking:",
  "This week...".
- A real number / mechanism beats wordplay. If any finance-meme account could
  post it, SKIP.
- Reach for US / global frames when you want the laugh: SEC 8-K, the amended
  S-1, 401k in 2022, an a16z thread that's 8 paragraphs about a $5 app,
  "thrilled to announce I've been let go", "pre-revenue", YC demo day, the
  CNBC chyron 40 minutes late, "we're a family here", unlimited PTO at a
  3-person startup, a Slack message at 11:58pm.
- EN comedy formula: [absurd-but-real observation] + [frame above] +
  [one-word gut-punch]. Cut after the punchline. Don't explain.

🚨 HARD RULES:
- 100% ENGLISH. Zero French words, zero French cultural anchors (no Bercy,
  RER B, URSSAF, syndicat, etc.). US / global frames only.
- Poke fun at the IDEA / market / trend — NEVER the person. No mocking the US
  government (Fed, SEC, IRS).
- Hype the AI, NEVER pump a bag: no price targets, no "$X next week", no
  "buy this", no rocket-emoji price calls. AI wonder unlimited; money calls
  banned.
- Put the source article URL (≤36h) on its own line if you have one; the
  take must stand on its own without it. No verified URL is fine — skip the
  URL line, never fake one.
- Lead with the feeling: a like is an emotional reflex, not a nod to your
  analysis. If a draft only informs, it dies at "view." Rewrite it.

{performance_section}

{dedup_section}

GIF (roughly half the time — operator 2026-06-06 mandate): when a famous meme
GIF amplifies the punchline, add an optional final line: [GIF: <2-4 word
search>]. Use the vocabulary below; skip it when the text is stronger alone.
GIF SEARCH VOCABULARY:
- huge win / euphoria       → [GIF: leonardo dicaprio clapping] / [GIF: vince mcmahon]
- boss move / victory lap   → [GIF: wolf of wall street] / [GIF: chef kiss]
- market pain / bleeding    → [GIF: michael jordan crying] / [GIF: this is fine]
- suspicion / side-eye      → [GIF: futurama fry suspicious] / [GIF: john cena are you sure]
- mind blown / big reveal   → [GIF: mind blown] / [GIF: math lady]
- panic / FOMO              → [GIF: kermit panic] / [GIF: surprised pikachu]

OUTPUT — write ONLY the final tweet, nothing else. NEVER text inside < >,
NEVER a placeholder, NEVER a label. EXACT format (replace the content, do not
copy these instructions):
Line 1 = the hot take (1-2 sentences, English)
Line 2 (optional) = the article URL, if you have a verified one
Line 3 = [PATTERN: ONE_ID]
Line 4 (optional) = [GIF: search query]

⚠️ ONE_ID is a SINGLE word from this list, never several joined by |:
REPETITION / DIALOGUE / METAPHOR / RENAME / EN_ANCHOR / UNDERSTATEMENT / OTHER.
Valid: "[PATTERN: UNDERSTATEMENT]". Invalid: "[PATTERN: EN_ANCHOR|METAPHOR]".
"""


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

⛔ NEVER output a tweet you've written before. Below are your recent posts.
If your draft is the same SENTENCE or the same IDEA as any of them, THROW IT
OUT and write something genuinely different. Repeating yourself is the worst
thing you can do.

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
    try:
        from . import main_post_growth
        growth_brief = main_post_growth.editorial_context_block(max_chars=1600)
        if growth_brief:
            performance_section = (performance_section or "") + "\n\n" + growth_brief
    except Exception:
        pass

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
