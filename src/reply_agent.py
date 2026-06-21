"""Reply agent: finds tweets from target influencers and generates witty replies.

Language strategy: prioritize French tweets, but reply in the tweet's own language
(English replies for English tweets, French for French). Tone: troll the IDEA, never
the person. Make influencers laugh with us, not feel attacked.
"""
import json
import os
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL, BLOCKLIST, DISCOVERED_ACCOUNTS_FILE
from .llm_client import run_llm, unwrap_text, _provider, _fallback_provider

# Logged once-per-process when the active LLM chain can't do real WebSearch
# (ollama/opencode hallucinate plausible-looking tweet URLs). Reset by tests.
_websearch_skip_logged = False


def _llm_has_websearch() -> bool:
    """True iff the active LLM chain can perform real WebSearch.

    ollama / opencode hit /api/generate with no tool API, so a prompt asking
    for "tweet URLs to reply to" comes back as plausible hallucinations
    (~94% TOO-OLD-filtered, ~50-100 min/day of ollama burned). claude /
    codex / gemini all have a real search path.
    Read at call time so a live AI_CLI change takes effect without restart.
    """
    if os.environ.get("REPLY_SEARCH_FORCE", "0") == "1":
        return True
    primary = _provider()
    if primary in {"claude", "codex", "gemini"}:
        return True
    fallback = _fallback_provider(primary)
    return fallback in {"claude", "codex", "gemini"}


# Core accounts to monitor — CEOs/execs + career/tech writers + companies.
# The AI Boss lane: careers, management, layoffs, comp, hiring, AI at work.
TARGET_ACCOUNTS = [
    # The named AI leaders to monitor (spec) — reply fast with value
    "sama", "DarioAmodei", "elonmusk", "karpathy", "JensenHuang",
    "satyanadella", "zuck", "demishassabis",
    # Major AI company / product accounts
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "xai", "AIatMeta", "mustafasuleyman",
    "nvidia", "GoogleAI", "MistralAI", "perplexity_ai", "cursor_ai",
    "OpenAIDevs", "huggingface",
    # Big AI news / commentators
    "rowancheung", "TheRundownAI", "emollick", "swyx", "_akhaliq",
]


def _load_discovered_handles(limit: int = 10) -> list:
    """Read the autonomously-discovered handles, latest first, capped at `limit`."""
    if not os.path.exists(DISCOVERED_ACCOUNTS_FILE):
        return []
    try:
        with open(DISCOVERED_ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
        handles = [d.get("handle") for d in data if d.get("handle")]
        return handles[-limit:]
    except (json.JSONDecodeError, IOError):
        return []


REPLY_PROMPT_TEMPLATE = """You are AI Big Boss (@TheAIShrink) — the account people follow to understand
what actually matters in AI. You reply to AI posts with insight, analysis,
prediction, or context. Replies are the growth engine: be everywhere AI is
discussed, fast, with the comment that adds real value.

PERSONALITY: confident, curious, analytical, fast, optimistic about AI,
occasionally funny, never cringe, never corporate. Short sentences. Strong
opinions. Easy language. No jargon. No buzzwords unless explained.

LANE (only): artificial intelligence — labs & models, AI agents & tools, AI
research/benchmarks, AGI, AI startups & funding, AI compute (Nvidia/GPUs),
embodied AI. NOT hiring/firing/careers, NOT coding-as-a-topic, NOT crypto,
NOT generic tech, NO politics/religion. Anything not about AI -> SKIP.

REPLY RULES:
- Every reply ADDS insight, analysis, a prediction, or context.
- NEVER reply "Wow", "Interesting", "Great", "So true", or just agree.
- Make AI make sense: explain what the post means, or what everyone's missing.
- 80-220 characters. Short punchy lines. Start with a capital letter.
- When it fits, invite discussion: "Am I missing something?", "What happens
  next?", "Agree or disagree?".
- NO hashtags. NO emojis. No em dashes. No links.
- Anchor on a SPECIFIC detail of the parent tweet. If the reply could sit
  under 20 different tweets, it's too generic -> rewrite or skip.

{discovered_section}

{dedup_section}

{skip_urls_section}

SEARCHES — AI ONLY. Run in order, ENGLISH FIRST.
MANDATORY: add `since:{since_date}` to EVERY query.
1. "site:x.com OpenAI OR Anthropic OR xAI OR \"GPT-5\" OR DeepSeek since:{since_date}"
2. "site:x.com ChatGPT OR Claude OR Gemini OR Grok OR Llama since:{since_date}"
3. "site:x.com \"AI agent\" OR agentic OR Cursor OR Devin OR MCP since:{since_date}"
4. "site:x.com AGI OR superintelligence OR \"AI safety\" OR reasoning model since:{since_date}"
5. "site:x.com Nvidia OR GPU OR \"AI datacenter\" OR \"AI bubble\" since:{since_date}"
6. "site:x.com from:sama OR from:OpenAI OR from:AnthropicAI OR from:karpathy since:{since_date}"
7. "site:x.com from:elonmusk OR from:ylecun OR from:demishassabis OR from:JensenHuang since:{since_date}"
8. "site:x.com Sora OR \"AI video\" OR \"humanoid robot\" OR robotics since:{since_date}"
9. "site:x.com IA OR \"intelligence artificielle\" OR Mistral lang:fr since:{since_date}"

Reply in the tweet's language. EVERYTHING must be about AI.

TYPE: all "reply". No quote tweets. Reply directly.

DO NOT REPLY TO REPLIES: target original tweets / visible posts only. If the
tweet starts with "@handle ...", shows "Replying to" / "En réponse à", or
looks like a thread reply -> SKIP. One reply per tweet, ever. Reply to the
main author only.

DEDUP: if a URL is in the SKIP list above, do NOT include it.

Find 6-10 candidates, return the 3 where your reply adds the most. Return at
most 3. If everything is flat, return [].

Output ONLY the raw JSON. No markdown, no explanation.

FIELD `pattern` (required) — tag each reply with ONE id from:
REPETITION / DIALOGUE / METAPHOR / RENAME / EN_ANCHOR / UNDERSTATEMENT / OTHER.

[{{"tweet_url": "https://x.com/user/status/123", "reply": "Sharp AI take that adds value", "type": "reply", "pattern": "OTHER"}}]"""


def generate_replies(recent_topics=None, already_replied=None):
    """Search for tweets and generate witty replies (FR priority, bilingual)."""

    dedup_section = ""
    if recent_topics:
        short_topics = recent_topics[-3:]
        topics_list = "\n".join(f"- {t[:80]}" for t in short_topics)
        dedup_section = f"ÉVITE ces sujets (déjà postés):\n{topics_list}"

    skip_urls_section = ""
    if already_replied:
        # Pass the last 100 URLs (up from 20) so the model has historical dedup context
        recent_urls = list(already_replied)[-100:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"SKIP ceux-là (déjà répondu — NE PAS RE-RÉPONDRE):\n{urls_list}"

    discovered = _load_discovered_handles(limit=10)
    discovered_section = ""
    if discovered:
        handles = " OR ".join(f"from:{h}" for h in discovered)
        discovered_section = (
            f"COMPTES DÉCOUVERTS RÉCEMMENT (à monitorer aussi):\n"
            f"@{', @'.join(discovered)}\n"
            f"Ajoute une recherche: \"site:x.com {handles}\""
        )

    # Autonomous evolution-agent directives — appended to discovered_section
    # so they don't disturb the prompt template's required keys.
    from .evolution_store import get_directives_block
    directives_block = get_directives_block()
    if directives_block:
        discovered_section = (discovered_section or "") + directives_block

    # Personality store — global mood + hard rules. Per-author dossiers are
    # injected by direct_reply.py (which knows the author). This path searches
    # broadly so we attach the global state of mind only.
    from . import personality_store
    mood = personality_store.render_global_mood()
    if mood:
        discovered_section = (discovered_section or "") + "\n\n" + mood
    # Hand-curated ideological core (core_identity.md) — voice anchor.
    # Reply agent is English-first (AI Boss rebrand); identity in EN, but the
    # prompt still tells it to reply in each tweet's own language.
    core_identity = personality_store.render_core_identity(lang="en")
    if core_identity:
        discovered_section = (discovered_section or "") + "\n\n" + core_identity
    discovered_section = (discovered_section or "") + "\n\n" + personality_store.hard_rules_block()

    from datetime import date, timedelta
    today = date.today()
    # since:YYYY-MM-DD on X = STRICTLY AFTER that day. So passing yesterday
    # captures yesterday + today (≤24h-ish) at search time.
    since_date = (today - timedelta(days=1)).isoformat()
    prompt = REPLY_PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
        discovered_section=discovered_section,
        today=today.isoformat(),
        since_date=since_date,
    )

    if not _llm_has_websearch():
        global _websearch_skip_logged
        if not _websearch_skip_logged:
            log.info(
                "[REPLY] REPLY_SEARCH skipped — primary LLM has no WebSearch "
                "tool (ollama/opencode); other reply paths (direct_reply, "
                "feed_sweeper, replyback) handle discovery via Safari scraping."
            )
            _websearch_skip_logged = True
        return None

    log.info("[REPLY] Running LLM CLI (searching X)...")
    # cwd=/tmp: when Claude CLI is invoked from inside a project dir with
    # CLAUDE.md and git context, parallel REPLY-search threads occasionally
    # hallucinate prose responses ("1 reply postée:") instead of returning
    # the requested JSON envelope — likely the project context cross-bleeds
    # between concurrent CLI sessions. Running from /tmp gives each call a
    # neutral CWD with no CLAUDE.md / git repo to leak in. Hit 7
    # hallucinations between 16:00-19:34 (2026-04-27) → escalation threshold.
    result = run_llm(
        prompt,
        REPLY_MODEL,
        label="REPLY_SEARCH",
        allowed_tools=["WebSearch"],
        cwd="/tmp",
        structured_output=True,
    )
    if result.returncode != 0:
        log.info(f"[REPLY] CLI error: {result.stderr[:200]}")
        return None

    # Extract the model's text from the --output-format json envelope
    output = unwrap_text(result.stdout)

    if not output or output.upper().startswith("SKIP"):
        return None

    cleaned = output

    # Try markdown code block first
    if "```" in cleaned:
        code_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if code_match:
            cleaned = code_match.group(1).strip()

    # Find JSON array anywhere in text
    if not cleaned.startswith("["):
        bracket_start = cleaned.find("[")
        if bracket_start != -1:
            bracket_end = cleaned.rfind("]")
            if bracket_end > bracket_start:
                cleaned = cleaned[bracket_start:bracket_end + 1]

    # Try parsing as-is first
    for attempt_text in [cleaned, output]:
        try:
            data = json.loads(attempt_text)
            if isinstance(data, list) and len(data) > 0:
                valid = [d for d in data if "tweet_url" in d and "reply" in d]
                if valid:
                    return valid
        except json.JSONDecodeError:
            pass

    # Last resort: find all JSON objects individually with regex.
    # Two passes — with and without `pattern` field — so we still recover if
    # the model dropped the bandit tag (it's important but not load-bearing).
    try:
        items = re.findall(
            r'\{\s*"tweet_url"\s*:\s*"([^"]+)"\s*,\s*"reply"\s*:\s*"([^"]+)"\s*,\s*"type"\s*:\s*"([^"]+)"\s*,\s*"pattern"\s*:\s*"([^"]+)"\s*\}',
            output,
        )
        if items:
            results = [
                {"tweet_url": url, "reply": reply, "type": t, "pattern": p}
                for url, reply, t, p in items
            ]
            log.info(f"[REPLY] Recovered {len(results)} replies via regex fallback (with pattern)")
            return results
        items = re.findall(
            r'\{\s*"tweet_url"\s*:\s*"([^"]+)"\s*,\s*"reply"\s*:\s*"([^"]+)"\s*,\s*"type"\s*:\s*"([^"]+)"\s*\}',
            output,
        )
        if items:
            results = [{"tweet_url": url, "reply": reply, "type": t} for url, reply, t in items]
            log.info(f"[REPLY] Recovered {len(results)} replies via regex fallback")
            return results
    except Exception:
        pass

    log.info(f"[REPLY] Could not parse JSON: {output[:300]}...")
    return None
