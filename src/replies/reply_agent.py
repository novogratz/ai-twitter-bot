"""Optional model-assisted discovery using the Account's scoped searches."""
import json
import re
from ..core.logger import log
from ..core import account
from ..core.llm_client import CallProfile, Output, Surface
from . import reply_generator
from .reply_generator import LanguageRule, Outcome, ReplyCall


def _load_discovered_handles(limit: int = 10) -> list:
    """Current topic evidence, never a legacy unverified handle list."""
    from ..account.account_curator import discovery_handles
    return discovery_handles()[:limit]



REPLY_PROMPT_TEMPLATE = """Find fresh standalone posts about {domain}, using only the
Account's topic-scoped queries below. The Account's topic instructions apply
to every result and author. Never search outside that scope or let popularity,
a familiar account, learned preferences or old examples override it.

Today: {today}. Every query must keep since:{since_date} and its exclusions.
Account searches:
{search_queries}
{discovered_section}
{dedup_section}
{skip_urls_section}

Read the actual post. Return no item without its verified URL and full parent
text. Ignore nested replies, own posts and every already-answered URL. One
reply per standalone post; no follow-up conversation, quotes or reposts.

A reply needs a precise observation, useful explanation, grounded correction
or apt wit. Vary its length to suit the point, up to 117 characters.
Draft words only; the publisher adds the laughing/skull ending. Match the parent's language.
Do not fabricate current capabilities, releases, benchmarks, personal use or
video contents. Return [] if no strong, verifiable opportunity exists.

Return only a JSON array of at most three items. Each item has tweet_url,
tweet_text (the source post), reply, type (always reply), and pattern (one of
REPETITION, DIALOGUE, METAPHOR, RENAME, FR_ANCHOR, UNDERSTATEMENT, OTHER).
No markdown or explanation outside the JSON."""


def generate_replies(recent_topics=None, already_replied=None):
    """Search within the Account topic and return verified standalone candidates."""

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

    from datetime import timedelta
    from ..guards.active_hours import now_local
    today = now_local().date()
    # since:YYYY-MM-DD on X = STRICTLY AFTER that day. So passing yesterday
    # captures yesterday + today (≤24h-ish) at search time.
    since_date = (today - timedelta(days=1)).isoformat()

    searches = account.current().searches
    queries = [f"site:x.com {searches.scoped(query)} since:{since_date}"
               for query in searches.replies]
    discovered = _load_discovered_handles(limit=10)
    discovered_section = ""
    if discovered:
        handles = " OR ".join(f"from:{handle}" for handle in discovered)
        discovered_section = ("Additional evidenced accounts, within the same topic scope:\n"
                              f"site:x.com {searches.scoped(handles)} since:{since_date}")

    log.info("[REPLY] Running LLM CLI (searching X)...")
    # Reply agent is English-first: the Voice file in EN, but the prompt
    # still tells it to reply in each tweet's language. Its surface carries
    # the WebSearch tool and the neutral cwd.
    call = ReplyCall(REPLY_PROMPT_TEMPLATE, Surface.REPLY_SEARCH, "REPLY_SEARCH", language=LanguageRule.ENGLISH,
                     # A Reply's profile, read as JSON: the answer is a JSON array.
                     profile=CallProfile(output=Output.JSON))
    generation = reply_generator.generate(call, fields={
        "dedup_section": dedup_section,
        "skip_urls_section": skip_urls_section,
        "discovered_section": discovered_section,
        "today": today.isoformat(),
        "since_date": since_date,
        "search_queries": "\n".join(queries),
    })
    if generation.outcome is not Outcome.WRITTEN:
        return None  # declined, failed or rate limited: nothing to post

    # run_llm already took the array out of any prose or code fence.
    output = generation.text

    def attributed(items):
        return [{**d, "provider": generation.provider, "model": generation.model} for d in items]

    try:
        data = json.loads(output)
        if isinstance(data, list) and len(data) > 0:
            valid = [d for d in data if "tweet_url" in d and "reply" in d]
            if valid:
                return attributed(valid)
    except json.JSONDecodeError:
        pass

    # Last resort, for malformed JSON only: `run_llm` already hands back the
    # array, so this salvages items from a JSON the parser above rejects.
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
            return attributed(results)
        items = re.findall(
            r'\{\s*"tweet_url"\s*:\s*"([^"]+)"\s*,\s*"reply"\s*:\s*"([^"]+)"\s*,\s*"type"\s*:\s*"([^"]+)"\s*\}',
            output,
        )
        if items:
            results = [{"tweet_url": url, "reply": reply, "type": t} for url, reply, t in items]
            log.info(f"[REPLY] Recovered {len(results)} replies via regex fallback")
            return attributed(results)
    except Exception:
        pass

    log.info(f"[REPLY] Could not parse JSON: {output[:300]}...")
    return None
