"""News agent: searches for breaking AI news and generates English Decode posts."""
import json
import re
import traceback
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


# Space push mode (2026-05-29): Space appears 3x in a 6-slot cycle
# so every other Décode is a Space story.
_DECODE_TOPICS = ("Space", "AI", "Space", "Robotics", "Space", "Investment")
_MONTHLY_DECODE_TOPICS = ("Space", "AI", "Space", "Investment")


def _peek_next_decode_number() -> int:
    """Return the next decode number without consuming it."""
    n = 1
    if _os.path.exists(_DECODE_COUNTER_FILE):
        try:
            with open(_DECODE_COUNTER_FILE) as f:
                n = int((_json.load(f) or {}).get("next", 1))
        except (OSError, _json.JSONDecodeError, ValueError):
            n = 1
    return n


def _commit_next_decode_number(n: int) -> None:
    """Persist the next decode number after a successful post."""
    try:
        with open(_DECODE_COUNTER_FILE, "w") as f:
            _json.dump({"next": n + 1, "last_assigned_at": datetime.now().isoformat(timespec="minutes")}, f, indent=2)
    except OSError:
        pass


def _topic_for_decode(n: int) -> str:
    """Topic rotation: AI, Space, Robotics, Investment on a 4-cycle."""
    return _DECODE_TOPICS[n % len(_DECODE_TOPICS)]


_DAILY_TOPIC_STATE_FILE = _os.path.join(_PR, "daily_topic_state.json")


def _daily_topic_state() -> dict:
    """Track which (topic, format) combos have shipped today. User mandate
    is EST-anchored ("1 AM EST every night") so "today" is the EST date.
    A Décode shipped Friday 7:50 PM EST counts as Friday's, even though
    Paris already says Saturday."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    if _os.path.exists(_DAILY_TOPIC_STATE_FILE):
        try:
            with open(_DAILY_TOPIC_STATE_FILE) as f:
                d = _json.load(f) or {}
            if d.get("date") == today:
                return d
        except (_json.JSONDecodeError, OSError):
            pass
    return {"date": today, "topics_done": []}


def _format_key(is_weekly: bool = False, format_kind: Optional[str] = None) -> str:
    if format_kind:
        return format_kind
    return "weekly" if is_weekly else "daily"


def _topic_done_key(topic: str, is_weekly: bool = False, format_kind: Optional[str] = None) -> str:
    """Dedup key is (topic, format). Daily, weekly Top 5, and monthly Top 10
    on the same topic count separately."""
    return f"{topic}:{_format_key(is_weekly, format_kind)}"


def _topic_already_done_today(topic: str, is_weekly: bool = False, format_kind: Optional[str] = None) -> bool:
    state = _daily_topic_state()
    return _topic_done_key(topic, is_weekly, format_kind) in (state.get("topics_done") or [])


def _mark_topic_done_today(topic: str, is_weekly: bool = False, format_kind: Optional[str] = None) -> None:
    state = _daily_topic_state()
    done = state.get("topics_done") or []
    key = _topic_done_key(topic, is_weekly, format_kind)
    if key not in done:
        done.append(key)
    state["topics_done"] = done
    try:
        with open(_DAILY_TOPIC_STATE_FILE, "w") as f:
            _json.dump(state, f, indent=2)
    except OSError:
        pass


def _unmark_topic_done_today(topic: str, is_weekly: bool = False, format_kind: Optional[str] = None) -> None:
    """Reverse of _mark_topic_done_today. Used when bot.py-side URL
    validation strips the link and we SKIP rather than ship URL-less —
    the topic should remain eligible for the next cycle."""
    state = _daily_topic_state()
    done = state.get("topics_done") or []
    key = _topic_done_key(topic, is_weekly, format_kind)
    if key in done:
        done.remove(key)
    state["topics_done"] = done
    try:
        with open(_DAILY_TOPIC_STATE_FILE, "w") as f:
            _json.dump(state, f, indent=2)
    except OSError:
        pass


def _clear_topics_done_today_for_format(format_kind: str) -> None:
    """Clear today's done markers for one format only.

    Manual monthly recaps need to be rerunnable without disturbing daily or
    weekly dedup state.
    """
    state = _daily_topic_state()
    suffix = f":{format_kind}"
    done = [key for key in (state.get("topics_done") or []) if not str(key).endswith(suffix)]
    state["topics_done"] = done
    try:
        with open(_DAILY_TOPIC_STATE_FILE, "w") as f:
            _json.dump(state, f, indent=2)
    except OSError:
        pass


def _is_in_daily_window() -> bool:
    """Daily Decodes fire at 7 AM EST (North American morning push, 2026-05-28).
    Window 6-10 AM EST gives the cron + a 3h buffer if startup is delayed.
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    return 6 <= now.hour < 10


def _is_in_weekly_window() -> bool:
    """Weekly Decodes fire Friday mornings EST (cron at 6:30 AM EST, 2026-05-28).
    Full Friday EST window so any delayed startup still catches.
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() == 4 and 7 <= now.hour <= 23


def _next_topic_not_done_today() -> Optional[tuple]:
    """Return the next (topic, is_weekly) pair eligible to ship NOW.

    Force-mode (set by the cron triggers in main.py):
      - globals()["_news_mode"] == "daily"   → only daily combos
      - globals()["_news_mode"] == "weekly"  → only weekly combos
      - globals()["_news_mode"] == "monthly" → only monthly combos
      - otherwise (manual / startup fire)   → use time-of-day windows
    """
    state = _daily_topic_state()
    done = set(state.get("topics_done") or [])
    done.update(globals().get("_temporary_skipped_done_keys") or set())
    mode = globals().get("_news_mode")
    plan = []
    if mode == "daily":
        plan = [(t, "daily") for t in _DECODE_TOPICS]
    elif mode == "weekly":
        plan = [(t, "weekly") for t in _DECODE_TOPICS]
    elif mode == "monthly":
        plan = [(t, "monthly") for t in _MONTHLY_DECODE_TOPICS]
    else:
        if _is_in_weekly_window():
            plan.extend([(t, "weekly") for t in _DECODE_TOPICS])
        if _is_in_daily_window():
            plan.extend([(t, "daily") for t in _DECODE_TOPICS])
    for topic, format_kind in plan:
        if _topic_done_key(topic, format_kind=format_kind) not in done:
            return (topic, format_kind)
    return None


def _build_slim_news_prompt(*, decode_number, decode_topic, day_of_week, today_date, format_mode, web_block, dedup_block):
    series_label = "Monthly" if format_mode == "monthly_top10" else ("Weekly" if format_mode == "top5" else "Daily")
    topic_label = {
        "AI": "AI & Agents",
        "Space": "Space & New Space",
        "Robotics": "Robotics & Frontier Tech",
        "Investment": "Investment & Markets",
        # legacy keys kept for old state files
        "IA": "AI & Agents",
        "Crypto": "Investment & Markets",
        "Investissement": "Investment & Markets",
    }.get(decode_topic, decode_topic)
    # Topic label for title (short form)
    topic_label_title = {
        "AI": "AI",
        "Space": "Space",
        "Robotics": "Robotics",
        "Investment": "Investment",
        "IA": "AI",
        "Crypto": "Investment",
        "Investissement": "Investment",
    }.get(decode_topic, decode_topic)
    from . import lang_mode as _lang_mode
    lang_directive = _lang_mode.lang_directive(_lang_mode.pick_content_lang())
    """A tight news prompt (~5k chars). Replaces the 25k PROMPT_TEMPLATE
    when generating Décodes. Claude can actually finish on this size.
    """
    top5_block = ""
    if format_mode == "monthly_top10":
        top5_block = f"""INSTRUCTIONS (DO NOT OUTPUT — think silently):

  • The Monthly Decode = TOP 10 numbers from the past 30 days for ONE
    category. Synthesize the biggest facts, not micro-news. Each bullet must
    carry an actor, a number, and a business/market consequence. Priority lens:
    "AI infrastructure & asymmetric investing": power demand, MW/GW capacity,
    compute scarcity, grid bottlenecks, robotics, space infrastructure,
    and AI-linked crypto.
  • ⚠️ DATA FRESHNESS — use ONLY the WEB SEARCH RESULTS / RSS POOL below.
    Do NOT use training knowledge — it is stale (e.g. Bitcoin is NOT at 125k,
    it's ~75k today). If search results don't have enough recent data for
    10 credible bullets, write fewer (8-9) with sourced numbers rather than inventing.
  • Ranking is descending: #1 = the month's fact the reader must bookmark.
    #10 must still be useful; no filler.
  • FOLLOWER TEST: if #1 doesn't make you want to follow the account to avoid
    missing the next Decode, change the topic. Information alone = death.
  • BULLET #1 = THE absolute killshot: round/memorable number, well-known actor,
    brutal business stakes. The reader must understand in 2 seconds why
    they need to read/like the rest. If another bullet is more memorable, swap.
  • MONTHLY VIRALITY: rank the 10 numbers by stop-scroll potential:
      1) name everyone recognizes (OpenAI, NVIDIA, BTC, BlackRock,
         Coinbase, Saylor, Elon, CoreWeave, Microsoft, Google, SpaceX,
         IREN, HIVE, TAO, Applied Digital),
      2) number simple enough to repeat in a comment ("$80B", "10x", "820k BTC"),
      3) clear consequence ("this changes pricing, power, or risk"),
      4) tension/opinion that makes you want to reply.
    #1 must beat the other 9 on at least 3 criteria. Otherwise rerank.
  • No chronological ranking. No "nice panorama". This is a Top 10
    built to be saved, shared, and quoted.
  • NUMBERS: come from the SIGNALS PROVIDED. Hedge ("~$3B") if not exact.
    NEVER invent a number absent from the title/snippet.
  • Final URL: MANDATORY. It MUST correspond to bullet #1, not a secondary bullet.
    Bullet #1 first, URL that proves it after.
  • TAGS: max 1 @handle per bullet, inline mid-phrase, never alone at start or end of line.
  • (source: outlet) must name a real media outlet. No invention.
  • ZERO markdown (**bold**, __italic__). Plain text only.
  • Final URL MANDATORY: a URL from the WEB SEARCH RESULTS / RSS POOL section
    that corresponds to bullet #1. Copy-paste the exact URL.
    No generic domain (coindesk.com, bloomberg.com) — only complete article URLs.
    If the pool has no URL for the #1 topic, choose a #1 topic that has a URL in the pool.
  • Target 1800-2600 chars body.

============================================================
EXACT OUTPUT (write ONLY the following, in this order):
============================================================

🔎 The Decode {series_label} #{decode_number} — {topic_label_title}

The 10 {topic_label} numbers that mattered this month.

1. 💰 {{exact #1 number, the killshot}} : {{one-line insight, inline @handle if relevant}}. (source: {{outlet}})
2. 🚀 {{number #2}} : {{insight}}. (source: {{outlet}})
3. ⚡ {{number #3}} : {{insight}}. (source: {{outlet}})
4. 📊 {{number #4}} : {{insight}}. (source: {{outlet}})
5. 🔥 {{number #5}} : {{insight}}. (source: {{outlet}})
6. 🧨 {{number #6}} : {{insight}}. (source: {{outlet}})
7. 🏦 {{number #7}} : {{insight}}. (source: {{outlet}})
8. 🧱 {{number #8}} : {{insight}}. (source: {{outlet}})
9. 🛰️ {{number #9}} : {{insight}}. (source: {{outlet}})
10. 🧾 {{number #10}} : {{insight}}. (source: {{outlet}})

{{Sarcastic punchline, 1-2 sentences, with a global market/tech reference.}}

{{Direct question: "Which one will change everything next month?"}}

Next month, same Decode.

{{Exact URL MANDATORY from WEB SEARCH RESULTS / RSS POOL — LAST line}}
"""
    elif format_mode == "top5":
        top5_block = f"""INSTRUCTIONS (DO NOT OUTPUT — think silently):

  • The Weekly Decode = ONE story from the past 7 days, THREE angles. ONE source URL.
    Not 5 different articles. One article, three levels of depth.
  • STEP 0 (CRITICAL): pick ONE exact URL from WEB SEARCH RESULTS / RSS POOL.
    The actor in its title = the main actor of this Decode. ALL analysis comes
    from that article. URL chosen FIRST then write. Mismatched URL = stripped preview card.
  • BULLET #1 (💰) = THE killshot. Three SIMULTANEOUS tests:
      - MEMORABLE: round number, shocking ratio, mental image
      - LIKABLE: very well-known name (Elon, sama, Saylor, OpenAI, NVIDIA, BTC, SpaceX...)
      - COMMENT-BAIT: claim/contrast that forces an opinion
    FOLLOWER TEST: if #1 can't earn a follow on its own, change the story.
  • BULLET #2 (⚡) = CONTEXT that makes #1 brutal. Comparison, ratio, or historical parallel.
  • BULLET #3 (📊) = CONSEQUENCE. What changes next or the brutal implication.
  • NO (source: outlet) per bullet. ONE URL at the end covers everything.
  • TAGS: max 1 @handle per bullet, ALWAYS inline mid-phrase, never at start/end of line.
  • NUMBERS: must appear in the TITLE or SNIPPET of the chosen article. Hedge with "~" if not exact.
    NEVER invent a number.
  • ZERO markdown. Plain text only.
  • Target 600-1000 chars body. Tight is punchy.
  • ONE URL at the very last line. Exact copy-paste. Must prove bullet #1.

============================================================
EXACT OUTPUT (write ONLY the following, in this order):
============================================================

🔎 The Decode {series_label} #{decode_number} — {topic_label_title}

The most asymmetric move this week:

1. 💰 {{killshot number + main actor — actor from URL title in first 6 words}} : {{insight, inline @handle mid-phrase if relevant}}
2. ⚡ {{context/comparison that makes #1 brutal}} : {{ratio, parallel, or scale reference}}
3. 📊 {{consequence}} : {{what changes or what's at stake}}

{{Sarcastic punchline that signs the take. 1-2 sentences. No question.}}

{{Exact URL — LAST LINE, MANDATORY}}
"""
    else:
        top5_block = f"""INSTRUCTIONS (DO NOT OUTPUT — think silently):

  • The Daily Decode = ONE story, ONE sharp take, ONE source URL.
    No numbered list. No "(source: X)" per line. ONE URL at the end.
  • STEP 0 (CRITICAL): pick ONE exact URL from WEB SEARCH RESULTS / RSS POOL.
    The actor in its title = the main actor of this Decode. ALL analysis comes
    from that article. URL chosen FIRST then write. Mismatched URL = stripped preview card.
  • NARRATIVE STRUCTURE (4 parts — DO NOT label them, just write naturally):
      HOOK: main actor + the ONE number everyone needs to know. 1-2 lines max.
      ANGLE: the brutal insight — what makes this asymmetric, what nobody's saying. 2-3 sentences.
      CONSEQUENCE: what changes, what's at stake, what comes next. 1-2 sentences.
      THESIS: the one line that makes someone want to follow. Under 20 words. NOT a question.
  • FOLLOWER TEST: if someone reads only the THESIS and doesn't feel compelled
    to follow, rewrite it. The voice is "You'll hate me until I'm right."
  • TAGS: 1-2 @handles inline mid-phrase across the whole Decode. Never at start/end of line.
  • NUMBERS: come from the article/snippet only. Hedge with "~" if not exact.
    NEVER invent a number absent from the title or snippet.
  • ZERO markdown. Plain text only.
  • Target 350-750 chars body. Shorter is sharper. No padding.
  • ONE URL at the very last line. Copy-paste exact. This is the source for everything above.

============================================================
EXACT OUTPUT (write ONLY the following, in this order):
============================================================

🔎 The Decode {series_label} #{decode_number} — {topic_label_title}

{{HOOK: main actor + the one number. 1-2 lines.}}

{{ANGLE: the asymmetric insight nobody's saying. 2-3 sentences.}}

{{CONSEQUENCE: 1-2 sentences.}}

{{THESIS: the take that earns a follow. Under 20 words. No question mark.}}

{{Exact URL — LAST LINE, MANDATORY}}
"""


    return f"""{lang_directive}

You are @CryptoAIDecode — 🚀 The AI & Space Decoder ⚡.
Sharp quant-analyst voice. Zero hype, zero filter. You'll hate me until I'm right.
Influencer, not a timid bot. Take positions. Sign your analysis. Zero bullshit.
Every Decode needs a THESIS that can be quoted in the comments.
Not an article summary: a sharp, funny, memorable take.
Default thesis style:
- "The market underestimates power demand for AI."
- "SpaceX is building a private central bank for space infrastructure."
- "Robotics is the next GPU war. Nobody's watching yet."
- "Compute is becoming an energy trade with a software multiple."

🎯 OBJECTIVE: ONE The Decode #{decode_number} on the hottest {topic_label} story.
TOPIC: {topic_label} only. Format: {format_mode}.

📈 2026 CONTENT STRATEGY:
- The Decode = 40%: quant analysis with thesis, exact numbers, named actors, consequences.
- Quick news = 30%: AI power demand, space launches, robotics milestones, investment signals.
- Threads = 15%: AI Power Wars, Space Economy, Robot vs Human, Asymmetric Bets.
- Visuals/link cards = 10%: charts, before/after, source cards.
- Engagement bait = 5%: one sharp question, never soft.

RECURRING FORMATS when the topic allows:
- AI Infra Radar
- Space Launch Tracker
- Robotics Breakout
- Asymmetric Bet of the Week
- The Numbers That Matter
- "The chart nobody is looking at..."

🚨 STRICT SCOPE — 4 PILLARS:
  • AI & Agents — labs (OpenAI/Anthropic/xAI/Google/Mistral), models, agents,
    agentic AI, GPUs, datacenters, MW/GW capacity, grid, nuclear, AI stocks.
  • Space & New Space — SpaceX (Starship/Falcon/Starlink), Rocket Lab, NASA Artemis,
    ESA, CNES, satellites, AST SpaceMobile, launch vehicles, lunar, Mars,
    space defense (Golden Dome, USSF), space stocks (RKLB, ASTS, LUNR).
  • Robotics & Frontier Tech — humanoid robots (Tesla Optimus, Figure, Boston Dynamics,
    1X, Agility), industrial automation, drone swarms, AI-powered hardware, exoskeletons,
    autonomous vehicles, frontier tech investments.
  • Investment & Markets — AI stocks (Nvidia, Palantir, CoreWeave, IREN, Microsoft,
    Google, Meta, Apple, Amazon, Tesla), space stocks (RKLB, ASTS), Bitcoin/crypto
    as asset class (BTC ETF, Saylor, Ethereum, stablecoins, DeFi infra),
    tech earnings, IPOs, M&A, asymmetric valuations, capex cycles.

{top5_block}

⚠️ OUTPUT RULES:
- Start DIRECTLY with "🔎 The Decode". No preamble and NO date on the first line.
- No "Score:", "Checks:", "Sources:", bold markdown meta. NOTHING before the header.
- 🚫 ZERO markdown: no **bold**, no __italic__, no *italic*.
  X does NOT render markdown — asterisks appear literally
  ("**$700M**" becomes "**$700M**" for the reader). Write in plain text.
  Numbers speak for themselves; emojis 1-5 carry the visual hook.
- Decorative emoji allowed: the 🔎 in the header + 1 emoji per bullet in top5
  (💰 🚀 ⚡ 📊 🔥). No emoji elsewhere. Hashtags: the bot may automatically add
  ONE tag among #Crypto #AI #Bitcoin #Web3 on some posts.
  Don't write them yourself. No em dash (—).
- English only. Native English-speaking AI / crypto / markets audience.
- Troll the IDEA, never the person.
- No trolling US government (Fed, SEC, IRS, etc).
- Source URL = LAST LINE of the tweet, MANDATORY as soon as the
  WEB SEARCH RESULTS section below contains at least 1 URL. Copy-paste an
  exact URL from that section — NEVER invent a domain. Whether it's a
  regular Decode (#36h) or top5 (#7j), same rule. The URL backs the main topic:
  point #1 / bullet #1, always the most impactful. Never a generic link
  that only illustrates the sector.
  No URL → no preview card → 50% fewer likes.

🏷️ TAGS — MANDATE: tag 2-3 major accounts in each Decode when the story
belongs to them. Don't be shy: tagging @sama in an OpenAI Decode or
@VitalikButerin in an ETH Decode creates notifications and reposts.
Priority accounts:
AI: @sama @OpenAI @AnthropicAI @MistralAI @ylecun @karpathy @demishassabis @elonmusk @xai @nvidia @AMD @intel @GoogleDeepMind @cursor_ai
Space: @SpaceX @Starlink @RocketLab @NASA @NASAArtemis @ESA @CNES @ArianeGroup @PeterDiamandis @ASTSpaceMobile @IntuitiveMach @BlueOrigin
Robotics: @Tesla @BostonDynamics @Figure_robot @1xtech @AgilityRobotics
Investment: @saylor @MicroStrategy @CoreWeave @IREN_Ltd @unusual_whales @KobeissiLetter @Palantir
In top5/monthly: tag inline in each bullet when the actor has an active X account.

🤣 PUNCHLINE: make them laugh, not just think. Use a global market/tech reference
when it reinforces the point: Bloomberg terminal, 401(k),
Series A deck, CNBC chyron, Wall Street, S-1, Fed dot plot, Slack all-hands.
FINAL QUESTION: not soft. It must force a position
("bubble or rerating?", "do you buy the stock or short the narrative?").

{web_block}

{dedup_block}

OUTPUT — ONLY the Decode in the exact format above. Nothing else.
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
_DECODE_HEADER_LINE_RE = re.compile(
    r"^\s*🔎?\s*(?:Le\s+D[eé]code|The\s+Decode)(?:\s+(?:Daily|Weekly|Monthly|Mensuel|Hebdo|Quotidien))?\s*#?\s*\d+\b",
    re.IGNORECASE,
)
# 2026-05-22: bumped 780 → 1400 for the multi-paragraph Décode format.
# User mandate: "make the text I write a bit longer, write a real thing
# bro" — body now targets 700-1200 chars of actual argumentation.
_MAX_NEWS_BODY_CHARS = 1400
_MAX_NEWS_LINE_CHARS = 220  # also bumped — paragraphs allowed, not just bullets


def _source_display_name(value: str) -> str:
    """Readable source label for inline citations. Never returns a URL."""
    from urllib.parse import urlparse

    raw = (value or "").strip().strip(".,);]")
    parsed = urlparse(raw if re.match(r"https?://", raw, re.IGNORECASE) else f"https://{raw}")
    host = (parsed.netloc or parsed.path or "").lower().replace("www.", "")
    host = host.split("/")[0]
    outlets = {
        "bloomberg.com": "Bloomberg",
        "reuters.com": "Reuters",
        "ft.com": "FT",
        "wsj.com": "WSJ",
        "investing.com": "Investing",
        "yahoo.com": "Yahoo Finance",
        "finance.yahoo.com": "Yahoo Finance",
        "coindesk.com": "CoinDesk",
        "cointelegraph.com": "Cointelegraph",
        "theblock.co": "The Block",
        "decrypt.co": "Decrypt",
        "cnbc.com": "CNBC",
        "techcrunch.com": "TechCrunch",
        "theverge.com": "The Verge",
        "axios.com": "Axios",
        "u.today": "U.Today",
        "lesechos.fr": "Les Échos",
        "lemonde.fr": "Le Monde",
        "lefigaro.fr": "Le Figaro",
        "bfmtv.com": "BFM",
        "businessinsider.com": "Business Insider",
        "forbes.com": "Forbes",
        "barrons.com": "Barron's",
        "economist.com": "The Economist",
        "nytimes.com": "NYT",
        "theinformation.com": "The Information",
        "gncrypto.news": "GN Crypto",
        "cryptorank.io": "CryptoRank",
        "cryptoseyes.com": "CryptoSEyes",
        "livebitcoinnews.com": "Live Bitcoin News",
        "cryptonews.com": "CryptoNews",
    }
    if host in outlets:
        return outlets[host]
    first = host.split(".")[0] if host else raw
    return first.replace("-", " ").replace("_", " ").title() if first else "source"


_BODY_DOMAIN_RE = re.compile(
    r"(?<!@)\b((?:[A-Za-z0-9-]+\.)+(?:com|fr|io|news|co|ai|org|net|finance|app|dev|xyz|me|tv|gg|co\.uk)(?:/[^\s)\]]*)?)",
    re.IGNORECASE,
)


def _rewrite_inline_source_urls(text: str) -> str:
    """Replace inline source URLs with source names.

    Applies before source extraction so URLs inside "(source: http...)" cannot
    be mistaken for the final link-card URL.
    """
    if not text:
        return text
    lines = text.splitlines()
    last_non_empty = None
    for i, line in enumerate(lines):
        if line.strip():
            last_non_empty = i

    def repl_wrapped(match):
        return f"(source: {_source_display_name(match.group(1))})"

    def repl_unwrapped(match):
        return f"source: {_source_display_name(match.group(1))}"

    def repl_domain(match):
        return _source_display_name(match.group(1) if match.lastindex else match.group(0))

    cleaned_lines = []
    final_url_line = re.compile(r"^\s*(?:source\s*[:：]\s*)?https?://\S+\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        if i == last_non_empty and final_url_line.match(line):
            cleaned_lines.append(line)
            continue
        line = re.sub(
            r"\(\s*source\s*[:：]\s*(https?://[^)\s]+)\s*\)",
            repl_wrapped,
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"\bsource\s*[:：]\s*(https?://[^\s)\]]+)",
            repl_unwrapped,
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"\(\s*source\s*[:：]\s*((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s)]*)?)\s*\)",
            repl_wrapped,
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"\bsource\s*[:：]\s*((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s)\]]*)?)",
            repl_unwrapped,
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(r"https?://[^\s)\]]+", repl_domain, line, flags=re.IGNORECASE)
        line = _BODY_DOMAIN_RE.sub(repl_domain, line)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _enforce_single_trailing_url(text: str, src_url: Optional[str]) -> str:
    """Allow only the final source URL; strip every other raw URL."""
    text = _rewrite_inline_source_urls(text or "")
    if not src_url:
        return re.sub(r"https?://\S+", "", text).strip()

    urls = list(_SOURCE_URL_RE.finditer(text))
    if not urls:
        return (text.rstrip() + "\n\n" + src_url).strip()

    parts = []
    last_end = 0
    for match in urls:
        raw = match.group(0)
        cleaned = _clean_source_url(raw)
        is_final = cleaned == src_url and match == urls[-1]
        parts.append(text[last_end:match.start()])
        if is_final:
            parts.append(src_url)
        last_end = match.end()
    parts.append(text[last_end:])
    cleaned_text = "".join(parts)
    if src_url not in cleaned_text:
        cleaned_text = cleaned_text.rstrip() + "\n\n" + src_url
    return re.sub(r"[ \t]{2,}", " ", cleaned_text).strip()


def _dedupe_decode_headers(text: str) -> str:
    """Keep one Décode header if the model and fallback both emitted one."""
    lines = (text or "").splitlines()
    header_indexes = [i for i, line in enumerate(lines) if _DECODE_HEADER_LINE_RE.match(line.strip())]
    if len(header_indexes) <= 1:
        return text

    # Duplicate-header leaks happen at the top. Keep the last leading header,
    # usually the richer one with weekday + date, and drop earlier headers.
    first_content_seen = False
    leading_headers = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _DECODE_HEADER_LINE_RE.match(stripped) and not first_content_seen:
            leading_headers.append(i)
            continue
        first_content_seen = True
    if len(leading_headers) <= 1:
        return text
    keep = leading_headers[-1]
    drop = set(leading_headers[:-1])
    cleaned = [line for i, line in enumerate(lines) if i not in drop]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def _compact_inline_mentions(text: str) -> str:
    """Prevent X from rendering standalone @handle lines inside bullets."""
    if not text:
        return text
    text = re.sub(
        r"[ \t]*\n[ \t]*(@[A-Za-z0-9_]{1,15})[ \t]*\n[ \t]*",
        r" \1 ",
        text,
    )
    text = re.sub(
        r"([^\n])\s*\n\s*(@[A-Za-z0-9_]{1,15})(?=[\s.,;:])",
        r"\1 \2",
        text,
    )
    return re.sub(r"[ \t]{2,}", " ", text)


def _news_quality_issue(text: str) -> Optional[str]:
    """Catch obvious hallucinated/news-broken output before posting."""
    body = _URL_RE.sub("", text or "")
    if len(_DECODE_HEADER_LINE_RE.findall(body)) > 1:
        return "duplicate Décode header"

    self_deal_pairs = {
        "spacex": ("spacex", "@spacex"),
        "openai": ("openai", "@openai"),
        "anthropic": ("anthropic", "@anthropicai"),
        "google": ("google", "@google"),
        "nvidia": ("nvidia", "@nvidia"),
        "mistral": ("mistral", "@mistralai"),
        "microsoft": ("microsoft", "@microsoft"),
        "meta": ("meta", "@meta"),
        "coinbase": ("coinbase", "@coinbase"),
        "riot": ("riot", "@riotplatforms"),
        "mara": ("mara", "@maraholdings"),
    }
    deal_verbs = r"(signe|sign[eé]?|deal|contrat|partenariat|acquiert|rach[eè]te|ach[eè]te|vend|paye|paie)"
    compact = re.sub(r"\s+", " ", body.lower())
    for label, aliases in self_deal_pairs.items():
        alias_rx = "|".join(re.escape(a) for a in aliases)
        if re.search(rf"\b(?:{alias_rx})\b[^.?!\n]{{0,120}}\b{deal_verbs}\b[^.?!\n]{{0,120}}\b(?:{alias_rx})\b", compact):
            return f"self-deal hallucination involving {label}"

    # Broken numbered bullets like "8. 🧱 2. 60.24." are usually model debris.
    if re.search(r"^\s*\d+\.\s*[^\n]{0,12}\b\d+\.\s+\d+(?:[.,]\d+)?\b", body, re.MULTILINE):
        return "malformed numeric bullet"

    bogus_sources = {"the man", "unknown", "source", "entrepreneur loop"}
    for source_name in re.findall(r"\(\s*source\s*[:：]\s*([^)]+?)\s*\)", body, flags=re.IGNORECASE):
        if source_name.strip().lower() in bogus_sources:
            return f"bogus source label: {source_name.strip()}"
    return None


def _dedup_terms(text: str) -> set[str]:
    """Entity/number terms used for recent-story duplicate detection."""
    body = _URL_RE.sub("", text or "").lower()
    body = re.sub(r"\(\s*source\s*[:：][^)]+\)", " ", body, flags=re.IGNORECASE)
    stop = {
        "decode", "daily", "weekly", "monthly", "samedi", "dimanche", "lundi",
        "mardi", "mercredi", "jeudi", "vendredi", "source", "chiffres",
        "jour", "mois", "semaine", "demain", "prochain", "meme", "même",
        "pour", "avec", "dans", "plus", "tout", "fait", "sont", "leur",
        "comme", "mais", "cette", "entre", "sans", "chez", "sur", "les",
        "des", "une", "est", "pas", "qui", "que", "quoi", "dont",
    }
    terms = {
        w
        for w in re.findall(r"@?[a-z0-9_]{3,}", body)
        if w not in stop and not re.fullmatch(r"20\d{2}|2026|2025", w)
    }
    # Keep memorable numbers; they are useful duplicate signatures.
    terms.update(re.findall(r"\b\d+(?:[,.]\d+)?\s*(?:md|m|k|btc|eh/s|mw|%)\b", body))
    return terms


def _candidate_terms(text: str) -> set[str]:
    body = (text or "").lower()
    return {
        w
        for w in re.findall(r"@?[a-z0-9_]{3,}", body)
        if not re.fullmatch(r"20\d{2}|2026|2025", w)
    }


def _recent_duplicate_issue(tweet: str, recent_tweets: list[str], format_kind: str = "daily") -> Optional[str]:
    """Refuse repeats of yesterday/recent posts, even if today's slot reset.

    Format-scoped dedup: monthly recaps only dedup against other monthly recaps,
    weekly against weekly, so a monthly Crypto recap isn't falsely killed by a
    daily Crypto decode that shares entities/numbers. Also skips same-date tweets
    for recaps — intra-session re-runs should not self-dedup."""
    # User directive 2026-05-24: do not block Daily Decodes on recent
    # entity+number overlap. This gate was too aggressive and killed the
    # IA / Investissement / Space burst after one Crypto post.
    return None
    current = _dedup_terms(tweet)
    if not current:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    for old in recent_tweets:
        # Skip tweets from other formats — monthly vs daily on same topic
        # is not a duplicate.
        if format_kind == "monthly" and "Le Décode Monthly" not in old:
            continue
        if format_kind == "weekly" and "Le Décode Weekly" not in old:
            continue
        if format_kind == "daily" and "Le Décode Daily" not in old and "Le Décode Weekly" not in old and "Le Décode Monthly" not in old:
            continue
        # Skip same-date recaps — intra-session re-runs should not dedup.
        if format_kind in ("monthly", "weekly") and today in old:
            continue
        old_terms = _dedup_terms(old)
        if not old_terms:
            continue
        overlap = current & old_terms
        if len(overlap) >= 6 and len(overlap) / max(1, min(len(current), len(old_terms))) >= 0.45:
            return f"recent duplicate story ({', '.join(sorted(overlap)[:8])})"
        handles = {t for t in current if t.startswith("@")} & {t for t in old_terms if t.startswith("@")}
        numbers = {t for t in current if re.search(r"\d", t)} & {t for t in old_terms if re.search(r"\d", t)}
        if handles and numbers:
            return f"recent duplicate entity+number ({', '.join(sorted(handles | numbers)[:8])})"
    return None


def _mark_generation_retryable(reason: str, text: str = "") -> None:
    """Tell bot.py to retry the same topic with a different candidate."""
    rejected_terms = set(globals().get("_temporary_rejected_terms") or set())
    rejected_terms.update(_dedup_terms(text))
    globals()["_temporary_rejected_terms"] = rejected_terms
    globals()["_last_generation_skip_retryable"] = True
    globals()["_last_generation_skip_reason"] = reason


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
    body = _compact_inline_mentions(_dedupe_decode_headers(body))
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
    format_kind = globals().get("_pending_decode_format", "daily")
    cap = 3200 if format_kind == "monthly" else (2000 if format_kind == "weekly" else _MAX_NEWS_BODY_CHARS)
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

    has_header = bool(re.search(r"(?:Le Décode|The Decode)(?:\s+(?:Daily|Weekly|Monthly|Mensuel|Hebdo|Quotidien))?\s*#?\d+", body, re.IGNORECASE))
    has_blank_break = "\n\n" in body

    # 2026-05-22: top5 weekly recap is naturally longer (5 emoji bullets +
    # intro + chute). Bump the ceiling 1400 → 2000 in that mode.
    format_kind = globals().get("_pending_decode_format", "daily")
    body_max = 3200 if format_kind == "monthly" else (2000 if format_kind == "weekly" else 1400)

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

PROMPT_TEMPLATE = """Tu es @CryptoAIDecode — 🚀 The AI & Space Decoder ⚡.
La voix la plus sharp sur AI + Space + Robotics + Investment. Analyste quant. Zéro bullshit.
Tu écris comme un influenceur reconnu, pas comme un bot timide. Tu prends position. Tu signes. Tu assumes.

🚀 MOTTO:
"AI · Space · Investment. Zero hype, zero filter. You'll hate me until I'm right. ⚡"

🚨 SCOPE — 4 PILLARS (mandate 2026-05-29):
  ✅ AI (labs, modèles, agents, GPU infra, datacenters, énergie IA, actions IA)
  ✅ Space (SpaceX, Rocket Lab, NASA, ESA, satellites, space stocks RKLB/ASTS/LUNR)
  ✅ Robotics (humanoïdes Tesla/Figure/Boston Dynamics, IA hardware, drones, automation)
  ✅ Investment (actions IA/Space, Bitcoin/crypto comme actif, earnings tech, IPOs, M&A)
  ❌ Immo, CAC40 banques, macro pure, fiscal FR → SKIP TOUJOURS.

{lang_directive}

🇬🇧 EN MODE (default since 2026-05-27 pivot): the language directive above
is GROUND TRUTH — write in ENGLISH for a global AI / crypto / markets
audience. Use fresh GLOBAL cultural anchors as deadpan flavor (NOT a forced
punchline): a Form 10-K footnote, an S-1 risk factor, an a16z term sheet, the
Fed dot plot, a CNBC chyron, a 401(k), a LinkedIn "thrilled to announce" post,
a Notion doc with 47 nested toggles, a Whole Foods checkout line, "number go
up technology". NO French anchors (Bercy, RER B, URSSAF, tonton, Doctolib) —
they read as gibberish to a global reader. If the language directive ever
flips back to FR, swap to fresh FR anchors — same structure, different anchor.

🎯 GOAL 2026-05-19 — UN DEEP-DIVE LONG dans la série "Le Décode #N".
Le compte fait 3 news/jour MAX, tous au même format. Les lecteurs
reviennent demain pour le suivant. Pattern récurrent = abonnés fidèles.

⚠️ OUTPUT RULE — ULTRA STRICT (user mandate 2026-05-21):
- Ta sortie DOIT commencer EXACTEMENT par "🔎 The Decode #..." (le header).
- ZÉRO préambule. Pas de "**Score**", "**Vérifications**", "**Angle**",
  "**Checklist**", "**Conformité**", "**Output**", "**Post**", pas
  d'en-tête de validation, pas de liste à puces de checks (- Source: …
  ✓ - Scope: … ✓), pas de "Voici", "Parfait", "OK".
- Si tu veux te valider mentalement, FAIS-LE SILENCIEUSEMENT et SKIP si
  <8/10. N'écris JAMAIS ta validation/score/checklist dans la sortie.
- Le pipeline détecte tout préambule et SKIP la cycle. Tu perds ta chance
  de poster.

✅ EXEMPLE CORRECT (output qu'on veut, à la lettre):

🔎 The Decode #42 — 2026-05-21
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

🔎 The Decode #42 — 2026-05-21
[...]

→ Cette structure SKIP automatique. Donne directement le Décode. RIEN AVANT.

JOUR DE LA SEMAINE: **{day_of_week}**
FORMAT MODE: **{format_mode}**  (top5 = Top 5 chiffres bookmark-bait; regular = Décode multi-paragraphe normal)

📚 SI {format_mode} == "top5" → FORMAT BOOKMARK-BAIT TOP 5 (ULTRA-IMPACT).

  Le vendredi, le compte fait 2-4 Décodes en format "Top 5 chiffres"
  couvrant les 4 piliers: AI, Space, Robotics, Investment.
  CE Décode est le récap hebdo du sujet {decode_topic}.
  Il DOIT être ce qu'un lecteur sauvegarde, relit, et
  partage en DM. Standard: chaque chiffre fait dire "tiens, c'est dingue".

  FORMAT STRICT — aucun écart:

    🔎 The Decode #{decode_number} — {decode_topic} — Vendredi {today_date}

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
Si {decode_topic} = AI → story IA (lab, modèle, agent, GPU, datacenter, énergie, actions IA).
Si {decode_topic} = Space → story spatiale (SpaceX/Starship/Starlink, Rocket Lab, NASA Artemis,
ESA, CNES, satellites, AST SpaceMobile, Golden Dome, space stocks RKLB/ASTS/LUNR).
Si {decode_topic} = Robotics → story robotique (humanoïdes Tesla/Figure/Boston Dynamics/1X,
drones, automation industrielle, AI hardware, frontier tech).
Si {decode_topic} = Investment → story investissement (actions IA/Space, Bitcoin/crypto comme
actif, Saylor/BTC ETF, earnings tech Nvidia/Palantir, IPO, M&A, valuations asymétriques).
Pas de Crypto standalone — crypto uniquement sous l'angle investissement/actif.
Ne croise PAS les topics — un Décode = un sujet, focus net. Le sujet de cette
édition s'affiche dans le header pour que les lecteurs sachent à quoi s'attendre.

FORMAT OBLIGATOIRE — strict (rien d'autre, ligne par ligne):

🔎 The Decode #{decode_number} — {decode_topic} — {today_date}

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
FR fraîches (pas RER B, pas Bercy — essaye: Apple Pay caisse en carton,
livraison J+3, LinkedIn coaching, crypto-bro Starbucks, QR code pour tout,
tuto Defisko, volet roulant, abonnement à tout). PEUT inclure 1-2 @-mentions d'acteurs RÉELLEMENT cités
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
  @MistralAI
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

SPACE / AEROSPACE (now a standalone Décode topic — SpaceX, Starship,
Starlink, Blue Origin, New Glenn, Rocket Lab, ArianeGroup, ESA, NASA):
  @SpaceX, @Starlink, @elonmusk (already above)
  @blueorigin, @RocketLab, @ArianeGroup, @esa, @NASA

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
   juste sourire. Réf culturelle FR fraîche (LinkedIn coaching, Apple Pay
   caisse en carton, livraison Amazon J+3, tuto Defisko, volet roulant,
   QR code pour tout, abonnement à tout). Pas de RER B, pas de Bercy.
   Screenshot-worthy.
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

PRIORITY (2026-05-29 pivot — 4 PILLARS):
  AI + SPACE + ROBOTICS + INVESTMENT. PRIORISE les histoires:
  - **AI & Agents** : OpenAI/Anthropic/xAI/Mistral, modèles, agents,
    GPU infra, datacenters MW/GW, énergie nucléaire, actions IA.
  - **Space** : SpaceX Starship/Falcon, Rocket Lab, NASA Artemis, ESA,
    CNES, Starlink, AST SpaceMobile, space stocks RKLB/ASTS/LUNR,
    Golden Dome, défense spatiale.
  - **Robotics** : Tesla Optimus, Figure, Boston Dynamics, 1X, Agility,
    drones, automation industrielle, AI hardware, frontier tech.
  - **Investment** : Nvidia/Palantir/CoreWeave/IREN actions, space stocks,
    Bitcoin/BTC ETF/Saylor comme actif macro, earnings tech, IPO, M&A.
  Crypto OK uniquement sous l'angle investissement/actif. Pas standalone.
  Pas d'immo, pas de CAC40 banques, pas de macro pure. Hors-scope → SKIP.

🤣 BE FUNNIER (mandate): "BE THE NUMBER 1 AI + SPACE + INVESTMENT
INFLUENCER. MAKE FRENCH PEOPLE LAUGH HARD."
- Une bonne news est une chute qui fait LOL. Pas un sourire poli, un LOL.
- STACK 2 réfs FR — c'est ÇA qui fait rire. Une seule réf = tiède.

🇫🇷 LEXIQUE FR ÉLARGI (pioche large, ne recycle pas les mêmes refs):
  • Transport : RER B, TGV à 19h59, TER en retard, Vélib' planté,
    Trottinette Lime, Pass Navigo, BlaBlaCar, péages à 4€
  • Bureaucratie : URSSAF, DGFIP, AMF, INSEE, Cerfa, Pôle Emploi, France
    Travail, Carte Vitale, Doctolib indispo, La Poste à 16h, CAF
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
  - nom propre sec (CoreWeave, Mistral, MARA, Saylor, OpenAI, NVIDIA)
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

📈 LEARNINGS RÉELS (performance_log 2026-05-11):
Les posts qui ont le mieux marché étaient factuels, nommaient un acteur connu,
et donnaient un chiffre exact dès le début: Capital B + 17,8 M$ + 182 BTC,
@saylor/@Strategy + 535 BTC + 43 M$, startup ex-OpenAI + valo 4 Md$.
Les pires étaient des one-liners abstraits sans fait vérifiable ni acteur.
Donc: privilégie "acteur + chiffre + conséquence".
Évite les punchlines seules type "À ce stade..." si elles ne portent pas
un fait concret. Impact = nom propre + montant/%/date + gagnant/perdant.

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
- CHUTE française obligatoire. Réf culturelle française fraîche (pas RER B,
  pas Bercy — LinkedIn coaching, Apple Pay caisse en carton, livraison Amazon
  J+3, tuto Defisko, volet roulant, QR code pour tout, abonnement à tout,
  crypto-bro Starbucks, "merci de patienter votre appel est important").
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
  - Use US / global frames instead: SEC filing, IRS audit, 401k loan,
    HOA violation letter, Craigslist scam, Venmo request from your ex,
    a Chipotle bowl that costs $18, Walgreens receipt longer than your arm,
    WeWork pitch deck, "this is fine" meme, LinkedIn influencer, "trust me
    bro", "number go up technology", "thoughts and prayers", default alive.
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


_FRAGILE_HOSTS = {
    "bloomberg.com", "reuters.com", "wsj.com", "ft.com", "nytimes.com",
    "theinformation.com", "businessinsider.com", "forbes.com",
    "barrons.com", "economist.com",
}


def _url_slug_looks_real(url: str) -> bool:
    """Heuristic check on the URL's last path segment. Real article URLs
    from major outlets have long, hyphen-rich slugs (often ≥30 chars,
    ≥3 hyphens). Hallucinated URLs from LLMs tend to be short/clean like
    'marathon-digital-refinancing' (29 chars, 2 hyphens). For fragile
    outlets where HTTP probing returns 403 (bot-block) — we can't tell
    real from fake via the network, so we use slug shape as the gate."""
    from urllib.parse import urlparse
    p = urlparse(url)
    if not p.netloc:
        return False
    host = p.netloc.lower().lstrip("www.")
    if host not in _FRAGILE_HOSTS:
        return True
    segs = [s for s in p.path.split("/") if s]
    if not segs:
        return False
    last_seg = segs[-1]
    # Real Bloomberg/Reuters/WSJ slugs: 40+ chars, 5+ hyphens, words
    # describing the headline. Loose threshold: ≥35 chars AND ≥3 hyphens.
    return len(last_seg) >= 35 and last_seg.count("-") >= 3


def url_is_reachable(url: str, timeout: int = 6) -> bool:
    """HEAD/GET the URL; return True if it resolves to a 2xx/3xx response.
    Used to refuse posting a fabricated source link.

    For fragile outlets (Bloomberg, Reuters, etc.) HTTP probes return 403
    against any bot UA — so we layer in a slug-shape heuristic to detect
    hallucinated URLs that look like real ones but have the wrong slug
    shape.
    """
    import urllib.request as _ur, urllib.error as _ue
    if not url or not url.startswith("http"):
        return False
    # Slug-shape pre-check for fragile outlets where HTTP can't tell
    # real from fake. Reject obvious hallucinations before network.
    if not _url_slug_looks_real(url):
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
            # 403/405 = host alive but rejects our method/UA — count as
            # reachable. Slug-shape gate above already filtered hallucinated
            # short slugs from fragile outlets.
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
    globals()["_last_generation_skip_retryable"] = False
    globals()["_last_generation_skip_reason"] = None
    recent = get_recent_tweets(hours=72)

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
                f"\n\n⛔ HARD BANLIST (sujets vus dans les 72h, news OU hot take — "
                f"INTERDITS, va ailleurs): {banned_list}\n"
                "Si ton meilleur sujet est dans cette liste, FORCE un autre angle "
                "ou SKIP. Recycler = perdre des followers (ils voient deux fois la "
                "même chose en 30 min).\n"
            )
        dedup_section = f"""Déjà posté dans les dernières 72h - ne couvre PAS le même sujet:
{tweets_list}{banned_block}

Choisis quelque chose de COMPLÈTEMENT DIFFÉRENT — angle, entité, niche."""
    else:
        dedup_section = ""

    # 2026-05-22 PM (durable trim): the news prompt was ballooning to
    # 25k chars and Claude couldn't finish on it in <5min. Diagnostic
    # showed Claude is fine on 3k prompts (6.8s) but hangs >5min on 25k.
    # Trimmed everything except: live web search results + dedup section
    # + tight voice anchor. Drops the prompt to ~12k chars.
    # Inject performance insights from the analyzer bot (if available).
    _insights_path = _os.path.join(_os.path.dirname(__file__), "..", "performance_insights.json")
    try:
        import json as _json
        if _os.path.exists(_insights_path):
            _ins = _json.load(open(_insights_path))
            _parts = []
            if _ins.get("top_patterns"):
                _parts.append("Top patterns 7j: " + ", ".join(
                    f"{p['pattern']}({p['count']})" for p in _ins["top_patterns"][:3]
                ))
            if _ins.get("rising_topics_24h"):
                _parts.append("Topics en hausse 24h: " + ", ".join(
                    r["topic"] for r in _ins["rising_topics_24h"]
                ))
            if _ins.get("best_topics_7d"):
                _parts.append("Best topics 7j: " + ", ".join(
                    f"{t['topic']}({t['count']})" for t in _ins["best_topics_7d"][:3]
                ))
            if _parts:
                performance_section = "=== INSIGHTS ANALYZER ===\n" + "\n".join(_parts) + "\n=== FIN INSIGHTS ===\n\n"
    except Exception:
        pass

    # Pool injection moved BELOW topic selection — needs decode_topic.
    injected_urls = set()
    injected_url_titles: dict[str, str] = {}

    # 2026-05-22 PM: joke_bank + self_winners disabled on the NEWS path.
    # These exemplars were great for HOT TAKES (short voice-driven 1-liners)
    # but on the long-form Le Décode multi-paragraph format they add 3-5k
    # chars of noise that Claude has to process for no clear gain — the
    # Décode shape is structured (header, paragraphs, chute, URL), not
    # voice-mimicry-driven. Hotake_agent still injects both.

    today_date = datetime.now().strftime("%Y-%m-%d")
    _DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_of_week = _DAYS_FR[datetime.now().weekday()]

    # 2026-05-22 PM hard rule (per-topic-per-day-per-format): 1 Daily +
    # 1 Weekly per topic per day max. Non-Friday: 3 Dailies max.
    # Friday: 3 Dailies + 3 Weeklies = 6 posts max. Independent of
    # MAX_NEWS_PER_DAY so meta_strategy_agent can't accidentally flood.
    next_combo = _next_topic_not_done_today()
    if next_combo is None:
        log.info("[NEWS] All eligible topic/format combos shipped today — no Décode this cycle.")
        return None
    decode_topic, format_kind = next_combo
    use_top5 = format_kind == "weekly"
    use_monthly = format_kind == "monthly"
    decode_number = _peek_next_decode_number()
    format_mode = "monthly_top10" if use_monthly else ("top5" if use_top5 else "regular")

    # POOL INJECTION (multi-query DDG + RSS + reachability pre-filter).
    # Lives here so it sees the resolved decode_topic.
    try:
        from . import web_search as _ws
        _tf = 'this month' if use_monthly else ('this week' if use_top5 else 'today')
        sub_queries = {
            "AI": [
                f"OpenAI Anthropic xAI Google DeepMind AI model agent news {_tf}",
                f"NVIDIA AMD GPU compute cluster datacenter AI infrastructure news {_tf}",
                f"AI datacenter power demand megawatt gigawatt nuclear grid news {_tf}",
                f"CoreWeave IREN applied digital AI cloud compute stocks news {_tf}",
            ],
            "Space": [
                f"SpaceX Starship launch test flight news {_tf}",
                f"SpaceX Falcon 9 Starlink launch manifest news {_tf}",
                f"Blue Origin New Glenn launch news {_tf}",
                f"Virgin Galactic space tourism flight news {_tf}",
                f"Rocket Lab RKLB launch mission news {_tf}",
                f"NASA Artemis moon lunar mission news {_tf}",
                f"AST SpaceMobile ASTS satellite broadband news {_tf}",
                f"Intuitive Machines LUNR lunar lander news {_tf}",
                f"SpaceX Starlink revenue business model news {_tf}",
                f"space defense Golden Dome USSF hypersonic missile news {_tf}",
                f"ESA CNES Ariane 6 launch commercial space news {_tf}",
                f"RKLB LUNR ASTS MNTS SIDU ASTC space stocks news {_tf}",
                f"SPCE Virgin Galactic space tourism stock news {_tf}",
                f"Momentus Sidus Space Astrotech Redwire space stock news {_tf}",
                f"Axiom Space station commercial orbital news {_tf}",
                f"Firefly Aerospace Relativity Space launch news {_tf}",
                f"satellite internet OneWeb Amazon Kuiper Starlink competition news {_tf}",
                f"Mars colonization SpaceX Starship human mission news {_tf}",
                f"space economy commercial space investment billion news {_tf}",
                f"ULA Vulcan Centaur launch Boeing Lockheed space news {_tf}",
                f"Planet Labs BlackSky satellite imagery Earth observation news {_tf}",
            ],
            "Robotics": [
                f"humanoid robot Tesla Optimus Figure Boston Dynamics news {_tf}",
                f"AI robotics automation industrial drone swarm news {_tf}",
                f"1X Agility Robotics Figure AI funding valuation news {_tf}",
                f"autonomous vehicles AI hardware frontier tech news {_tf}",
            ],
            "Investment": [
                f"Nvidia Palantir Microsoft Google Meta earnings AI stocks news {_tf}",
                f"RKLB ASTS LUNR MNTS SIDU ASTC SPCE space stocks valuation news {_tf}",
                f"Bitcoin BTC ETF institutional Saylor crypto investment news {_tf}",
                f"tech IPO M&A acquisition AI valuation funding news {_tf}",
                f"Ethereum stablecoin DeFi crypto asset class news {_tf}",
            ],
            # Legacy keys — keep so old state files don't crash
            "IA": [
                f"OpenAI Anthropic xAI AI infrastructure news {_tf}",
                f"NVIDIA GPU datacenter AI news {_tf}",
            ],
            "Crypto": [
                f"Bitcoin BTC ETF crypto investment news {_tf}",
                f"Ethereum DeFi stablecoin crypto news {_tf}",
            ],
            "Investissement": [
                f"AI stocks Nvidia Palantir CoreWeave investment news {_tf}",
                f"tech earnings M&A valuation news {_tf}",
            ],
        }.get(decode_topic, [f"AI Space Robotics Investment news {_tf}"])
        ddg_hits = []
        for q in sub_queries:
            try:
                ddg_hits.extend(_ws.search_news(q, max_results=8 if use_monthly else 5, date_filter="m" if use_monthly else ("w" if use_top5 else "d")))
            except Exception:
                continue
        try:
            signals = _ws.load_recent_signals(max_age_days=30 if use_monthly else (7 if use_top5 else 2), limit=20 if use_monthly else 10)
        except Exception:
            signals = []
        # Filter out content farms / low-trust outlets BEFORE reachability
        # check. via.news, cryptoslate, etc publish AI-generated clickbait
        # with factually wrong claims (saw "Nvidia +20%" when it crashed).
        from .hotake_agent import _is_rejected_source
        raw_candidates = {}
        rejected_terms = set(globals().get("_temporary_rejected_terms") or set())
        for h in ddg_hits:
            u = (h.get("url") or "").rstrip(".,);")
            title = (h.get("title") or "") + " " + (h.get("snippet") or "")
            if rejected_terms and len(_candidate_terms(title) & rejected_terms) >= 3:
                continue
            if u and u not in raw_candidates and not _is_rejected_source(u):
                raw_candidates[u] = title
        for s in signals:
            u = s.get("url") or ""
            title = s.get("title") or ""
            if rejected_terms and len(_candidate_terms(title) & rejected_terms) >= 3:
                continue
            if u and u not in raw_candidates and not _is_rejected_source(u):
                raw_candidates[u] = title
        reachable_pool = {}
        if raw_candidates:
            import concurrent.futures as _cf
            urls_list = list(raw_candidates.keys())
            log.info(f"[NEWS] Pre-validating {len(urls_list)} pool URLs for reachability...")
            with _cf.ThreadPoolExecutor(max_workers=8) as _pool:
                results = list(_pool.map(lambda u: (u, url_is_reachable(u, timeout=4)), urls_list))
            for u, ok in results:
                if ok:
                    reachable_pool[u] = raw_candidates[u]
            log.info(f"[NEWS] Pool: {len(reachable_pool)}/{len(urls_list)} URLs reachable after filter.")
        if reachable_pool:
            # Extract unique named entities from URL titles to guide ÉTAPE 0
            stop_entities = {"the", "and", "for", "are", "not", "but",
                             "this", "that", "with", "from", "into", "about",
                             "have", "been", "more", "what", "when", "where",
                             "their", "there", "which", "while", "your", "could",
                             "would", "should", "will", "well", "than", "some",
                             "such", "just", "after", "before", "still", "every",
                             "another", "between", "les", "des", "est", "pas",
                             "une", "dans", "sur", "tout", "mais", "pour",
                             "avec", "sont", "fait", "cette", "plus",
                              "aussi", "être", "avoir", "faire", "bien", "donc",
                              "dont", "alors", "tous", "peut", "leur", "très",
                              "même", "sans", "non", "ces", "elle",
                              "été", "etc", "via", "comme"}
            all_entities = set()
            for title in reachable_pool.values():
                for w in re.findall(r"\w{5,}", title.lower()):
                    if w not in stop_entities:
                        all_entities.add(w)
            entity_hint = ""
            if all_entities:
                sorted_ents = sorted(all_entities, key=lambda x: -len(x))[:12]
                entity_hint = (
                    "KEY ENTITIES ACROSS THESE URLS (mention at least one in bullet #1):\n"
                    + ", ".join(sorted_ents)
                    + "\n\n"
                )
            lines = [
                "==================================================",
                f"WEB SEARCH RESULTS — {len(reachable_pool)} reachable URLs ({'past month' if use_monthly else 'past week'}, topic={decode_topic})",
                "⚠️ ONLY use these URLs and their snippets. Do NOT use your training data — it is OLD.",
                "Pick the URL whose title best matches bullet #1 — copy EXACTLY.",
                "==================================================",
                "",
            ]
            if entity_hint:
                lines.insert(0, entity_hint.rstrip())
            for u, title in list(reachable_pool.items())[:24 if use_monthly else 12]:
                lines.append(f"- {u}")
                lines.append(f"  {title}")
                lines.append("")
            performance_section = (performance_section or "") + "\n\n" + "\n".join(lines)
        injected_urls = set(reachable_pool.keys())
        injected_url_titles = dict(reachable_pool)
    except Exception:
        log.info(f"[NEWS] Pool injection failed (proceeding without): {traceback.format_exc()[:400]}")
    globals()["_last_injected_urls"] = injected_urls
    globals()["_last_injected_url_titles"] = injected_url_titles
    log.info(f"[NEWS] Final injected pool: {len(injected_urls)} URLs (topic={decode_topic}).")

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
    globals()["_pending_decode_format"] = format_kind

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
            globals()["_last_generation_skip_retryable"] = True
            globals()["_last_generation_skip_reason"] = (r.stderr or "LLM failed").strip()[:240]
            log.info(f"[NEWS] LLM failed before usable text: {globals()['_last_generation_skip_reason']}")
            return ""
        text = unwrap_text(r.stdout) or ""
        if not text.strip():
            globals()["_last_generation_skip_retryable"] = True
            globals()["_last_generation_skip_reason"] = "LLM returned empty usable text"
            log.info("[NEWS] LLM returned empty usable text after unwrap.")
        return text

    tweet = _gen_one().strip()
    if not tweet or tweet.upper() == "SKIP":
        reason = globals().get("_last_generation_skip_reason") or "SKIP/empty"
        log.info(f"[NEWS] SKIP/empty — bailing ({reason}).")
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
        r"(🔎?\s*(?:Le\s+D[eé]code|The\s+Decode)\s*#?\s*\d+[^\n]*?\d{4}-\d{2}-\d{2})",
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
    # drops the accent), Daily/Weekly label optional, missing 🔎 prefix.
    decode_match = re.search(
        r"(?:🔎\s*)?(?:Le\s+D[eé]code|The\s+Decode)(?:\s+(?:Daily|Weekly|Monthly|Mensuel|Hebdo|Quotidien))?\s*#?\s*\d+",
        tweet,
        re.IGNORECASE,
    )
    if decode_match:
        body = tweet[decode_match.start():].strip()
        if not body.startswith("🔎"):
            body = "🔎 " + body
        tweet = body
    elif tweet and len(re.sub(r"\s+", " ", tweet)) >= 100:
        log.info(f"[NEWS] Décode header missing but body present ({len(tweet)} chars) — auto-injecting header.")
        today = datetime.now().strftime("%Y-%m-%d")
        n = globals().get("_pending_decode_num")
        topic = globals().get("_pending_decode_topic", "")
        format_kind = globals().get("_pending_decode_format", "daily")
        label = "Monthly" if format_kind == "monthly" else ("Weekly" if format_kind == "weekly" else "Daily")
        topic_label = {"IA": "AI Infra", "Investissement": "Asym. Markets"}.get(topic, topic)
        header = f"🔎 The Decode {label} #{n} — {topic_label} — {today}" if n else f"🔎 The Decode {label} — {today}"
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
    # Inline citations must never contain raw URLs. Do this before source
    # extraction so "(source: http://...)" cannot be mistaken for the final
    # link-card URL.
    tweet = _rewrite_inline_source_urls(tweet)
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
    # Monthly Top 10 spans roughly the last month.
    format_kind = globals().get("_pending_decode_format", "daily")
    is_top5 = format_kind == "weekly"
    is_monthly = format_kind == "monthly"
    # User mandate 2026-05-23: daily = 48h max, weekly = 7 days, monthly = 30 days.
    max_age_h = 720 if is_monthly else (168 if is_top5 else 48)
    if src_url:
        try:
            from .hotake_agent import _url_publication_date, _is_rejected_source
            # Source rejectlist (CLAUDE.md content-farm list). Prompt-side
            # rule leaks ~once a day, so this is the deterministic backstop.
            if _is_rejected_source(src_url):
                log.info(f"[NEWS] Source on content-farm rejectlist — SKIPPING: {src_url}")
                _mark_generation_retryable(f"rejected source: {src_url}", tweet)
                globals()["_last_source_url"] = None
                globals()["_last_image_topic"] = None
                return None
            pub_date = _url_publication_date(src_url)
            if pub_date is not None:
                age = datetime.now() - pub_date
                if age > timedelta(hours=max_age_h):
                    log.info(f"[NEWS] URL is {age.total_seconds()/3600:.1f}h old (>{max_age_h}h, top5={is_top5}) — SKIPPING stale source: {src_url}")
                    _mark_generation_retryable(f"stale source: {src_url}", tweet)
                    globals()["_last_source_url"] = None
                    globals()["_last_image_topic"] = None
                    return None
        except Exception:
            pass
    # User mandate 2026-05-24: every Daily, Weekly, and Monthly Décode must
    # end with an article URL that proves point #1. No URL-less recap escape
    # hatch: the link card is part of the format.
    if not src_url:
        preview = " ".join(tweet.split())[:220]
        log.info(
            f"[NEWS] Décode without trailing URL → SKIPPING (user mandate: "
            f"point #1 link card required for daily/weekly/monthly). Preview: {preview!r}"
        )
        globals()["_last_source_url"] = None
        globals()["_last_image_topic"] = None
        _mark_generation_retryable("missing point #1 source URL", tweet)
        return None
    globals()["_last_source_url"] = src_url
    # X's native link-card covers the visual; an attached image would
    # suppress the card preview, so always null the image topic.
    globals()["_last_image_topic"] = None
    # Final hard invariant for every Décode format: no raw URLs in the body,
    # exactly one optional URL at the end for the X link card.
    tweet = _enforce_single_trailing_url(tweet, src_url)
    tweet = _finalize_news_tweet(tweet, src_url)
    duplicate_issue = _recent_duplicate_issue(tweet, recent, format_kind)
    if duplicate_issue:
        preview = " ".join(tweet.replace(src_url or "", "").split())[:220]
        log.info(f"[NEWS] Dedup refused — {duplicate_issue}: {preview!r}")
        _mark_generation_retryable(duplicate_issue, tweet)
        globals()["_last_source_url"] = None
        globals()["_last_image_topic"] = None
        return None
    quality_issue = _news_quality_issue(tweet)
    if quality_issue:
        preview = " ".join(tweet.replace(src_url or "", "").split())[:220]
        log.info(f"[NEWS] Quality gate refused — {quality_issue}: {preview!r}")
        _mark_generation_retryable(quality_issue, tweet)
        globals()["_last_source_url"] = None
        globals()["_last_image_topic"] = None
        return None
    if _news_body_bad_format(tweet, src_url):
        preview = " ".join(tweet.replace(src_url or "", "").split())
        log.info(f"[NEWS] Bad body format — SKIPPING to avoid unreadable block: {preview[:180]!r}")
        _mark_generation_retryable("bad body format", tweet)
        globals()["_last_source_url"] = None
        return None
    if _news_body_too_long(tweet, src_url):
        preview = " ".join(tweet.replace(src_url or "", "").split())
        log.info(f"[NEWS] Body too long ({len(preview)} chars > {_MAX_NEWS_BODY_CHARS}) — SKIPPING to avoid Show more: {preview[:180]!r}")
        _mark_generation_retryable("body too long", tweet)
        globals()["_last_source_url"] = None
        return None
    # Respect-list defense: refuse to ship news that names a protected
    # handle in a derisive context.
    from . import respect_list
    cleaned, reason = respect_list.scrub_text_or_skip(tweet)
    if cleaned is None:
        log.info(f"[NEWS] Refused — {reason}: {tweet[:120]!r}")
        _mark_generation_retryable(f"respect list: {reason}", tweet)
        globals()["_last_source_url"] = None
        return None
    tweet = cleaned
    if src_url:
        log.info(f"[NEWS] Article URL detected (X will render card): {src_url[:120]}")
    else:
        log.info("[NEWS] No source URL — top5 weekly recap (per-bullet sources inline).")
    # IMPORTANT: capture is_weekly BEFORE clearing _pending_top5_topic.
    # Bug 2026-05-22: was reading the global AFTER it was set to None,
    # so all Weekly Top 5s got marked as Daily in daily_topic_state.
    _pending = globals().get("_pending_top5_topic")
    _format_kind_this_post = globals().get("_pending_decode_format", "daily")
    is_weekly_this_post = _format_kind_this_post == "weekly"
    if _pending:
        _mark_top5_done(_pending)
        log.info(f"[NEWS] Top 5 Vendredi shipped for {_pending} — next {_pending} Décode = regular format.")
        globals()["_pending_top5_topic"] = None
    # Hard daily-per-topic-per-format dedup: mark this (topic, format) done
    # so no further same-topic-same-format Décode ships today. On Friday a
    # topic still gets BOTH a Daily and a Weekly (separate keys).
    _decoded_topic = globals().get("_pending_decode_topic")
    if _decoded_topic:
        _mark_topic_done_today(_decoded_topic, format_kind=_format_kind_this_post)
        label = "Monthly" if _format_kind_this_post == "monthly" else ("Weekly" if is_weekly_this_post else "Daily")
        log.info(f"[NEWS] Marked '{_decoded_topic}' {label} done for today.")
    _commit_next_decode_number(decode_number)
    return tweet
