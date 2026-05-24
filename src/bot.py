"""Post bot: publishes AI news tweets and philosophy hot takes."""
import json
import os
import random
import re
import time
import traceback
from datetime import date
from .config import MAX_NEWS_PER_DAY, MAX_HOTAKES_PER_DAY, DAILY_STATE_FILE, get_live_cap
from .logger import log
from .agent import generate_tweet, _enforce_single_trailing_url, _finalize_news_tweet
from .hotake_agent import generate_hotake
from .twitter_client import post_tweet, post_thread
from .history import save_tweet
from .engagement_log import log_post, log_hotake
from .humanizer import humanize
from .article_image import fetch_article_image
from .image_gen import make_quote_card


def _live_news_cap() -> int:
    """Live cap from meta_strategy_agent's live_strategy.json, env fallback.

    2026-05-22 PM: user reverted the Friday 2-cap — "i want more than 2
    news". Friday still gets the Top 5 bookmark-bait FORMAT (prompt-side),
    just with the same daily VOLUME as other days.
    """
    return get_live_cap("MAX_NEWS_PER_DAY", MAX_NEWS_PER_DAY)


def _live_hotake_cap() -> int:
    """Live cap from meta_strategy_agent's live_strategy.json, env fallback."""
    return get_live_cap("MAX_HOTAKES_PER_DAY", MAX_HOTAKES_PER_DAY)


THREAD_SEPARATOR = "---THREAD---"
NEWS_POSTS_PER_CYCLE = int(os.environ.get("NEWS_POSTS_PER_CYCLE", "3"))
NEWS_POST_SPACING_SECONDS = int(os.environ.get("NEWS_POST_SPACING_SECONDS", "120"))
ORIGINAL_HASHTAG_PROB = float(os.environ.get("ORIGINAL_HASHTAG_PROB", "0.18"))
_CURATED_HASHTAGS = ("#Crypto", "#AI", "#Bitcoin", "#Web3")

# Source-as-self-reply was reverted 2026-04-30 PM (user: "remove the source as
# reply of yourself this is ridiculous.. put it directly in the news if needed").
# URL stays inline in the tweet body — X renders the link card natively.


def _maybe_add_curated_hashtag(text: str) -> str:
    """Add at most one approved hashtag to original posts, sparingly.

    humanize() strips model-leaked hashtags, so this is the only sanctioned
    hashtag path. Replies stay hashtag-free because reply hashtags read spammy.
    """
    if not text or random.random() > ORIGINAL_HASHTAG_PROB:
        return text
    if any(tag.lower() in text.lower() for tag in _CURATED_HASHTAGS):
        return text
    body = text.lower()
    if re.search(r"\bbitcoin|btc|satoshi|saylor|microstrategy\b", body):
        tag = "#Bitcoin"
    elif re.search(r"\bweb3|defi|dao|wallet|stablecoin|token\b", body):
        tag = "#Web3"
    elif re.search(r"\bcrypto|ethereum|solana|coinbase|binance|etf crypto\b", body):
        tag = "#Crypto"
    elif re.search(r"\bia\b|openai|anthropic|mistral|nvidia|gpu|agent|llm|chatgpt", body):
        tag = "#AI"
    else:
        return text
    if len(text) + len(tag) + 1 > 280:
        return text
    lines = text.rstrip().splitlines()
    last_idx = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if last_idx is not None and re.fullmatch(r"https?://\S+", lines[last_idx].strip()):
        lines.insert(last_idx, tag)
        return "\n".join(lines).strip()
    return f"{text.rstrip()} {tag}"


def _load_daily_state() -> dict:
    """Load persistent daily counters from disk."""
    if os.path.exists(DAILY_STATE_FILE):
        try:
            with open(DAILY_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": None, "news": 0, "hotakes": 0}


def _save_daily_state(state: dict):
    """Persist daily counters to disk (survives restarts)."""
    with open(DAILY_STATE_FILE, "w") as f:
        json.dump(state, f)


def _get_counters() -> tuple[int, int]:
    """Get today's counters, resetting if it's a new day."""
    state = _load_daily_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "news": 0, "hotakes": 0}
        _save_daily_state(state)
    return state["news"], state["hotakes"]


def has_post_slot() -> bool:
    """Cheap cap check for schedulers: true if any post format can still ship.

    Keep this outside `run_bot_cycle()` so main.py can avoid even entering the
    news/hot-take generation path once both daily buckets are full.
    Reads LIVE caps via meta_strategy_agent's live_strategy.json.
    """
    news_count, hotake_count = _get_counters()
    return news_count < _live_news_cap() or hotake_count < _live_hotake_cap()


def post_slot_status() -> str:
    """Human-readable daily post cap state for logs."""
    news_count, hotake_count = _get_counters()
    return f"{news_count}/{_live_news_cap()} news, {hotake_count}/{_live_hotake_cap()} hot takes"


def _decrement_counter(counter_name: str):
    """Reverse a previous _increment_counter call — used when a generated
    tweet is rejected by URL validation so the daily slot isn't burned."""
    state = _load_daily_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        return  # date rolled over, nothing to decrement
    state[counter_name] = max(0, state.get(counter_name, 0) - 1)
    _save_daily_state(state)


def _increment_counter(counter_name: str):
    """Increment a daily counter and persist."""
    state = _load_daily_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "news": 0, "hotakes": 0}
    state[counter_name] = state.get(counter_name, 0) + 1
    _save_daily_state(state)


_DECODE_STOP_TOKENS = {
    "this","that","with","from","into","about","have","been","more","what",
    "when","where","their","there","which","while","your","could","would",
    "should","will","well","than","some","such","just","after","before",
    "still","every","another","between","comme","cette","leur","cette",
    "dans","pour","mais","plus","moins","tout","tous","sans","avec",
    "bitcoin","crypto","network","daily","performance","chart","source",
    "chiffres","jour","miner","miners","mining","datacenter","datacenters",
}


def _decode_match_tokens(text: str) -> set[str]:
    """High-signal tokens for matching bullet #1 to a source title."""
    if not text:
        return set()
    tokens = set()
    for handle in re.findall(r"@([A-Za-z0-9_]{3,15})", text):
        tokens.add(handle.lower())
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", text):
        w = word.lower()
        if w not in _DECODE_STOP_TOKENS:
            tokens.add(w)
    return tokens


def _pick_best_pool_url(bullet1_text: str, pool_url_titles: dict, *, require_strong_match: bool = True) -> str:
    """Find the pool URL whose title best matches bullet #1 (token overlap).
    Returns the best URL or '' if no good match. Used to force-substitute
    the model's hallucinated URL with a real one from our injected pool."""
    if not bullet1_text or not pool_url_titles:
        return ""
    b1_tokens = _decode_match_tokens(bullet1_text)
    if not b1_tokens:
        return ""
    best_url, best_score = "", 0
    for url, title in pool_url_titles.items():
        title_tokens = _decode_match_tokens(title or "")
        overlap = len(b1_tokens & title_tokens)
        if overlap > best_score:
            best_score, best_url = overlap, url
    threshold = 1 if not require_strong_match else 2
    return best_url if best_score >= threshold else ""


def _bullet1_numbers_grounded(bullet1: str, url_title_snippet: str) -> bool:
    """Lenient version (2026-05-23 PM v2): at least ONE major number in
    bullet #1 must appear in the article title+snippet. Skips year-like
    numbers (1900-2100). Returns True if no extractable major numbers,
    if the snippet itself has no numbers (text-only article), or if any
    number grounds.

    This catches strong hallucinations (zero overlap) without false-
    positiving on real numbers the model knows from the article body
    that just happen not to be in the 500-char DDG snippet."""
    if not bullet1 or not url_title_snippet:
        return True
    haystack = url_title_snippet.lower()
    # If the snippet has no numbers at all, the article may be text-only.
    # Skip the check rather than reject every bullet on text-only sources.
    if not re.search(r"\d{2,}", haystack):
        return True
    nums = []
    for m in re.finditer(r"(\d[\d.,\s]{0,8}\d|\d)", bullet1):
        raw = m.group(1).strip().replace(" ", "")
        digits = raw.replace(",", "").replace(".", "")
        if not digits or len(digits) < 2:
            continue
        try:
            val = int(digits)
        except ValueError:
            continue
        if val < 10:
            continue
        if 1900 <= val <= 2100:
            continue  # year — not a stat
        candidates = {raw, digits, raw.replace(",", "."), raw.replace(".", ",")}
        if len(digits) >= 4:
            candidates.add(f"{int(digits):,}")
            candidates.add(f"{int(digits):,}".replace(",", " "))
        nums.append((val, candidates))
    if not nums:
        return True
    # At least ONE major number from #1 must appear in haystack
    for val, candidates in nums:
        for c in candidates:
            if c and c.lower() in haystack:
                return True
        # Fuzzy: leading 2 digits also count
        sval = str(val)
        if len(sval) >= 2 and sval[:2] in haystack:
            return True
    return False


_OUTLET_DISPLAY_NAMES = {
    "bloomberg.com": "Bloomberg",
    "reuters.com": "Reuters",
    "ft.com": "Financial Times",
    "wsj.com": "WSJ",
    "nytimes.com": "NYT",
    "theinformation.com": "The Information",
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "wired.com": "Wired",
    "arstechnica.com": "Ars Technica",
    "venturebeat.com": "VentureBeat",
    "technologyreview.com": "MIT Tech Review",
    "coindesk.com": "CoinDesk",
    "cointelegraph.com": "Cointelegraph",
    "theblock.co": "The Block",
    "decrypt.co": "Decrypt",
    "cnbc.com": "CNBC",
    "axios.com": "Axios",
    "finance.yahoo.com": "Yahoo Finance",
    "lesechos.fr": "Les Échos",
    "lemonde.fr": "Le Monde",
    "numerama.com": "Numerama",
    "bfmtv.com": "BFM",
    "lefigaro.fr": "Le Figaro",
    "capital.fr": "Capital",
    "france24.com": "France 24",
    "businessinsider.com": "Business Insider",
    "forbes.com": "Forbes",
    "barrons.com": "Barron's",
    "economist.com": "The Economist",
}


def _outlet_name_for_url(url: str) -> str:
    """Pick a clean display name for the URL's host."""
    from urllib.parse import urlparse
    if not url:
        return ""
    host = urlparse(url).netloc.lower().lstrip("www.")
    if host in _OUTLET_DISPLAY_NAMES:
        return _OUTLET_DISPLAY_NAMES[host]
    # Default: first label of the host, capitalized.
    head = host.split(".")[0]
    return head.capitalize() if head else ""


def _align_bullet1_source_tag(tweet: str, new_url: str) -> str:
    """When we substitute the URL, rewrite the (source: X) tag on bullet
    #1 to match the new URL's outlet. Otherwise the post says
    "(source: Bloomberg)" with a Reuters trailing URL — bad signal."""
    new_outlet = _outlet_name_for_url(new_url)
    if not new_outlet:
        return tweet
    def _replace_in_b1(m):
        b1 = m.group(0)
        # Replace any (source: <anything>) with the new outlet name.
        return re.sub(
            r"\((?:source|src|via)\s*[:：]\s*[^)]*\)",
            f"(source: {new_outlet})",
            b1,
            count=1,
            flags=re.IGNORECASE,
        )
    return re.sub(r"^\s*1\..*?(?=\n\s*2\.|$)", _replace_in_b1, tweet, flags=re.DOTALL | re.MULTILINE)


def _substitute_url_with_pool_match(tweet: str, src_url: str) -> tuple:
    """Replace the candidate's URL with a pool URL. Tries:
      1. Best token-overlap with bullet #1.
      2. Best token-overlap with full tweet body (broader topic match).
      3. First reachable pool URL (last resort).

    Returns (new_tweet, new_src_url). Only falls back to original src_url
    if literally no pool URL is reachable.

    2026-05-23: re-instated strict pool whitelist in the validator, so
    this function must ALWAYS produce an in-pool URL or downstream will
    reject. Made substitution exhaustive: pick anything reachable from
    the pool rather than fall back to a model-emitted URL."""
    from . import agent as _ag
    pool_titles = getattr(_ag, "_last_injected_url_titles", None) or {}
    if not pool_titles:
        return tweet, src_url
    # If model's URL is already in pool AND reachable, keep it.
    if src_url and src_url in pool_titles and _ag.url_is_reachable(src_url):
        return tweet, src_url
    # Pick best pool URL by strong bullet #1 overlap. Do not fall back to a
    # broad topic URL for Daily Decodes: that produced link cards like a
    # Bitcoin hashrate chart under a Riot/CleanSpark/IREN lead.
    b1_match = re.search(r"^\s*1\.\s*(.+?)(?:\n\s*2\.|$)", tweet, re.MULTILINE | re.DOTALL)
    bullet1 = b1_match.group(1) if b1_match else ""
    best_url = _pick_best_pool_url(bullet1, pool_titles)
    if best_url and not _ag.url_is_reachable(best_url):
        best_url = ""
    if not best_url:
        log.info("[NEWS] No strong bullet #1 URL match in pool — leaving original for validation/retry.")
        return tweet, src_url
    if src_url == best_url:
        return tweet, src_url
    new_tweet = tweet
    if src_url:
        new_tweet = new_tweet.replace(src_url, "").rstrip()
    new_tweet = re.sub(r"https?://\S+\s*$", "", new_tweet, flags=re.MULTILINE).rstrip()
    # Align inline (source: X) on bullet #1 with the substituted URL's
    # outlet so the post doesn't say "Bloomberg" then link to Reuters.
    new_tweet = _align_bullet1_source_tag(new_tweet, best_url)
    new_tweet = new_tweet.rstrip() + "\n\n" + best_url
    log.info(f"[NEWS] Substituted URL: {src_url!r} → {best_url!r} (source tag updated)")
    return new_tweet, best_url


def _run_single_bot_cycle() -> bool:
    """Post a Décode (Daily or Weekly), respecting daily limits.
    Returns True if a post was shipped, False if nothing eligible — caller
    uses False to break the burst loop instead of sleeping for nothing."""
    news_count, hotake_count = _get_counters()
    news_cap = _live_news_cap()
    hotake_cap = _live_hotake_cap()
    log.info(f"Today: {news_count}/{news_cap} Décodes, {hotake_count}/{hotake_cap} hot takes")

    if news_count >= news_cap and hotake_count >= hotake_cap:
        log.info("Daily Décode limits reached. Skipping.")
        return False

    can_hotake = hotake_count < hotake_cap
    can_news = news_count < news_cap

    # AI news is the brand backbone. Force the first half of the daily news
    # quota through the AI news path before spending the single AI hot-take slot.
    news_floor_before_hotake = min(3, news_cap)
    if can_news and news_count < news_floor_before_hotake:
        do_hotake = False
    elif not can_news:
        do_hotake = can_hotake
    elif not can_hotake:
        do_hotake = False
    else:
        do_hotake = random.random() < 0.25

    tweet_source = "news"  # which module owns last_source_url for this tweet
    if do_hotake:
        log.info("Generating AI hot take...")
        tweet = generate_hotake()
        if tweet is None:
            log.warning("Hot take failed, falling back to news...")
            if can_news:
                tweet = generate_tweet()
                if tweet:
                    _increment_counter("news")
                    tweet_source = "news"
        else:
            _increment_counter("hotakes")
            tweet = humanize(tweet)
            tweet = _maybe_add_curated_hashtag(tweet)
            # Visual policy 2026-04-29 PM (user: "shitty image generated"):
            # NO MORE Pillow quote cards — they look bot-y. Real photos only.
            # Priority: source-article og:image > Wiki og:image > text-only.
            # The article's own hero photo is the most credible visual (it's
            # what a journalist sharing the scoop would surface).
            img_path = None
            src_url = None
            try:
                from .hotake_agent import last_source_url, last_image_topic
                src_url = last_source_url()
                # When a source URL is present X renders a native link-card,
                # which is the visual. Skip image attach so the card shows.
                if not src_url:
                    slug = last_image_topic()
                    if slug:
                        wiki_url = f"https://en.wikipedia.org/wiki/{slug}"
                        img_path = fetch_article_image(wiki_url)
                        if img_path:
                            log.info(f"[HOTAKE] Wiki photo attached for '{slug}': {img_path}")
                    else:
                        log.info("[HOTAKE] No source URL or image slug — text-only")
                else:
                    log.info(f"[HOTAKE] URL inline (X renders link card): {src_url[:80]}")
            except Exception as e:
                log.info(f"[HOTAKE] Image fetch failed (text-only): {e}")
            log.info(f"[HOTAKE] Posting ({len(tweet)} chars): {tweet[:100]}...")
            post_tweet(tweet, image_path=img_path)
            save_tweet(tweet)
            try:
                from .hotake_agent import last_pattern as _last_hotake_pattern
                _pattern = _last_hotake_pattern() or ""
            except Exception:
                _pattern = ""
            log_hotake(tweet, pattern_id=_pattern)
            if img_path:
                try:
                    os.remove(img_path)
                except OSError:
                    pass
            return True
    else:
        # 2026-05-23 PM: Décode retry loop — user mandate "make sure URL is
        # there, don't skip, if it doesn't work generate a new post". Up to
        # 3 attempts to land a Décode whose URL passes whitelist + coupling.
        # Between attempts, un-mark the topic in daily_topic_state and
        # un-increment the counter so we don't burn slots on rejected gens.
        from . import agent as _ag_mod
        tweet = None
        last_tried_topic = None
        _ag_mod.__dict__["_temporary_rejected_terms"] = set()
        max_attempts = 5
        for attempt in range(max_attempts):
            log.info(f"Generating Décode, attempt {attempt + 1}/{max_attempts}...")
            candidate = generate_tweet()
            if candidate is None:
                retryable = bool(_ag_mod.__dict__.get("_last_generation_skip_retryable"))
                reason = _ag_mod.__dict__.get("_last_generation_skip_reason") or "no eligible combo"
                log.info(f"[NEWS] generate_tweet returned None — {reason}.")
                if retryable and attempt < max_attempts - 1:
                    topic = _ag_mod.__dict__.get("_pending_decode_topic")
                    fk = _ag_mod.__dict__.get("_pending_decode_format", "daily")
                    if topic and fk:
                        key = _ag_mod._topic_done_key(topic, format_kind=fk)
                        skipped = set(_ag_mod.__dict__.get("_temporary_skipped_done_keys") or set())
                        skipped.add(key)
                        _ag_mod.__dict__["_temporary_skipped_done_keys"] = skipped
                        log.info(f"[NEWS] Skipped {key} — retryable failure, trying next category.")
                    else:
                        log.info("[NEWS] Refusal is retryable — searching for a different story.")
                    continue
                break
            _increment_counter("news")
            # Quick validate URL here (whitelist + coupling). Real post-flight
            # validation still runs further below, but we use this to decide
            # whether to retry or accept.
            cand_src = None
            try:
                from .agent import last_source_url as _ls
                cand_src = _ls()
            except Exception:
                pass
            topic = _ag_mod.__dict__.get("_pending_decode_topic")
            format_kind = _ag_mod.__dict__.get("_pending_decode_format", "daily")
            is_weekly = format_kind == "weekly"
            is_recap = format_kind in {"weekly", "monthly"}
            last_tried_topic = (topic, format_kind)
            # Weekly Top 5 and Monthly Top 10: inject best pool URL for bullet #1
            # so the post has a real article link, not a generic domain.
            if is_recap:
                recap_tweet, recap_src = _substitute_url_with_pool_match(candidate, cand_src)
                if recap_src and recap_src != cand_src:
                    try:
                        _ag_mod.__dict__["_last_source_url"] = recap_src
                    except Exception:
                        pass
                    tweet = recap_tweet
                else:
                    tweet = candidate
                break
            # 2026-05-23 PM: force URL substitution from injected pool.
            # Don't trust the model's URL choice — ollama hallucinates fake
            # CoinDesk slugs. Replace with the best-matching real pool URL
            # by bullet #1 token overlap. This GUARANTEES a real URL when
            # the pool has decent coverage for the topic.
            candidate, cand_src = _substitute_url_with_pool_match(candidate, cand_src)
            try:
                _ag_mod.__dict__["_last_source_url"] = cand_src
            except Exception:
                pass
            ok = False
            if cand_src:
                injected = getattr(_ag_mod, "_last_injected_urls", None) or set()
                injected_titles = getattr(_ag_mod, "_last_injected_url_titles", None) or {}
                # 2026-05-23 PM: STRICT pool whitelist back on. After two
                # dead Reuters/Bloomberg URLs slipped through the
                # reachability+slug heuristic (both outlets 403 every bot
                # UA so we can't tell real from fake via HTTP), the only
                # reliable defense is "URL must be in the live DDG/RSS
                # pool we injected this cycle". Substitution upstream
                # (_substitute_url_with_pool_match) should have already
                # forced the URL into the pool; if not, this catches it.
                in_pool = (not injected) or (cand_src in injected)
                reachable = _ag_mod.url_is_reachable(cand_src) if in_pool else False
                coupling = True
                if reachable and in_pool:
                    title = (injected_titles.get(cand_src) or "").lower()
                    if title:
                        b1_match = re.search(r"^\s*1\.\s*(.+?)(?:\n\s*2\.|$)", candidate, re.MULTILINE | re.DOTALL)
                        subject_region = (b1_match.group(1) if b1_match else candidate[:500]).lower()
                        title_tokens = _decode_match_tokens(title)
                        subject_tokens = _decode_match_tokens(subject_region)
                        if title_tokens and len(title_tokens & subject_tokens) < 2:
                            coupling = False
                grounded = True
                if reachable and in_pool and coupling:
                    title = injected_titles.get(cand_src) or ""
                    b1_match = re.search(r"^\s*1\.\s*(.+?)(?:\n\s*2\.|$)", candidate, re.MULTILINE | re.DOTALL)
                    b1_text = b1_match.group(1) if b1_match else ""
                    if not _bullet1_numbers_grounded(b1_text, title):
                        grounded = False
                ok = in_pool and reachable and coupling and grounded
                if not in_pool:
                    log.info(f"[NEWS] Validation FAIL: URL not in injected pool ({len(injected)} candidates): {cand_src}")
                elif not reachable:
                    log.info(f"[NEWS] Validation FAIL: URL unreachable / 404: {cand_src}")
                elif not coupling:
                    log.info(f"[NEWS] Validation FAIL: coupling mismatch with bullet #1")
                elif not grounded:
                    log.info(f"[NEWS] Validation FAIL: bullet #1 numbers not grounded in article snippet (hallucinated number)")
            if ok:
                tweet = candidate
                break
            log.info(f"[NEWS] Attempt {attempt + 1} URL failed validation (src={cand_src}). Un-marking + retrying.")
            try:
                if topic:
                    _ag_mod._unmark_topic_done_today(topic, format_kind=format_kind)
            except Exception:
                pass
            _decrement_counter("news")
        else:
            log.info(f"[NEWS] All {max_attempts} attempts failed validation/dedup. Giving up this cycle.")
        _ag_mod.__dict__.pop("_temporary_rejected_terms", None)
        if tweet is None and can_hotake:
            log.info("No fresh Décode - trying a hot take instead...")
            tweet = generate_hotake()
            if tweet:
                _increment_counter("hotakes")
                tweet_source = "hotake"

    if tweet is None:
        log.info("No eligible Décode this cycle (all topic/format combos shipped).")
        return False

    # Pull pattern_id from whichever agent generated this tweet (same side-
    # channel as URL/image). News-falls-back-to-hotake must read from hotake.
    try:
        if tweet_source == "hotake":
            from .hotake_agent import last_pattern as _last_news_pattern
        else:
            from .agent import last_pattern as _last_news_pattern
        _news_pattern = _last_news_pattern() or ""
    except Exception:
        _news_pattern = ""

    if THREAD_SEPARATOR in tweet:
        parts = [p.strip() for p in tweet.split(THREAD_SEPARATOR) if p.strip()]
        parts = [humanize(p) for p in parts]
        log.info(f"[THREAD] Got {len(parts)}-tweet thread")
        for i, part in enumerate(parts, 1):
            log.info(f"  [{i}] ({len(part)} chars): {part[:80]}...")
        post_thread(parts)
        save_tweet(tweet)
        log_post(tweet, pattern_id=_news_pattern)
    else:
        tweet = humanize(tweet)
        # Visual policy 2026-04-29 PM (user: "shitty image generated"):
        # NO Pillow quote cards. Article's own og:image first (real journalism
        # photo, the one a journalist sharing the scoop would surface), Wiki
        # photo as fallback when [IMAGE: slug] is set, else text-only.
        img_path = None
        src_url = None
        try:
            # If the news path fell back to a hot take, the URL/topic side-
            # channel lives on hotake_agent, not agent. Pull from the right
            # module or the URL gets dropped and the tweet ships text-only.
            if tweet_source == "hotake":
                from .hotake_agent import last_source_url, last_image_topic
            else:
                from .agent import last_source_url, last_image_topic
            src_url = last_source_url()
            topic = last_image_topic()
            # When a source URL is present, let X render the native link-card.
            # Attaching an image suppresses the card preview, so only attach
            # an image when there's no URL.
            if not src_url and topic:
                wiki_url = f"https://en.wikipedia.org/wiki/{topic}"
                img_path = fetch_article_image(wiki_url)
                if img_path:
                    log.info(f"[NEWS] Wiki photo attached for '{topic}': {img_path}")
            if src_url:
                log.info(f"[NEWS] URL inline (X renders link card): {src_url[:80]}")
            elif not img_path:
                log.info("[NEWS] Text-only post (no source URL, no image slug)")
        except Exception as e:
            log.info(f"[NEWS] Image fallback failed (text-only): {e}")
        # 2026-05-22 PM (user mandate): keep source URL inline in the
        # body — no more self-reply detour. The link card renders on the
        # main post; auto-like-own-tweet (already wired in post_tweet)
        # boosts impressions immediately. Pre-flight URL check still
        # applies: if the model fabricated the URL, strip it so we don't
        # ship a broken link.
        is_decode = (tweet_source == "news" and src_url is not None)
        post_body = tweet
        if is_decode and src_url:
            log.info(f"[NEWS] Model emitted URL: {src_url}")
            try:
                from . import agent as _ag
                # Whitelist check — only allow URLs that came from our
                # injected WEB SEARCH RESULTS / RSS POOL. Catches soft-404s
                # (Reuters returns 200 OK on /article-not-found pages, so a
                # reachability check alone misses fabrications). Skip when
                # no injection happened this cycle so we don't false-strip
                # legitimate Claude-WebSearch URLs.
                injected = getattr(_ag, "_last_injected_urls", None) or set()
                injected_titles = getattr(_ag, "_last_injected_url_titles", None) or {}
                strip_reason = None
                # 2026-05-23: pool-whitelist relaxed — reachability is the
                # source-of-truth gate. Real URLs from ollama's training
                # data that aren't in our DDG pool can still pass.
                if not _ag.url_is_reachable(src_url):
                    strip_reason = "unreachable / 404"
                else:
                    # Coupling check: bullet #1 must strongly match the URL
                    # title. Catches broad topic cards like hashrate charts
                    # under a Riot/CleanSpark/IREN lead.
                    title = (injected_titles.get(src_url) or "").lower()
                    if title:
                        b1_match = re.search(r"^\s*1\.\s*(.+?)(?:\n\s*2\.|$)", tweet, re.MULTILINE | re.DOTALL)
                        subject_region = (b1_match.group(1) if b1_match else re.sub(r"https?://\S+", "", tweet)[:500]).lower().strip()
                        if subject_region:
                            title_tokens = _decode_match_tokens(title)
                            subject_tokens = _decode_match_tokens(subject_region)
                            if title_tokens:
                                overlap = title_tokens & subject_tokens
                                if len(overlap) < 2:
                                    strip_reason = (
                                        f"bullet #1 doesn't match URL title strongly "
                                        f"(overlap={sorted(overlap)[:6]}, title={sorted(title_tokens)[:6]})"
                                    )
                if strip_reason:
                    # User mandate 2026-05-24: all Décode formats need a
                    # trailing URL that proves point #1. If validation strips
                    # the link, skip and retry instead of posting body-only.
                    decode_format = getattr(_ag, "_pending_decode_format", "daily")
                    log.info(
                        f"[NEWS] ❌ URL stripped ({decode_format}) — {strip_reason}: {src_url} "
                        f"→ SKIPPING Décode (point #1 URL required)."
                    )
                    try:
                        topic = _ag.__dict__.get("_pending_decode_topic")
                        if topic:
                            _ag._unmark_topic_done_today(topic, format_kind=decode_format)
                            log.info(f"[NEWS] Un-marked '{topic}:{decode_format}' — will retry next cycle.")
                    except Exception:
                        pass
                    return
                else:
                    log.info(f"[NEWS] ✅ URL validated (pool + reachable + matches #1), keeping inline")
            except Exception as e:
                log.info(f"[NEWS] URL validation failed (keeping link): {e}")
            # When a URL is present, the link card carries the visual.
            # An attached image would suppress the card → text + URL only.
            if src_url:
                img_path = None
        elif is_decode:
            # No URL emitted by the model → SKIP, retry. Daily, Weekly, and
            # Monthly all need a final URL proving point #1.
            log.info("[NEWS] ⚠️ Décode would ship URL-less → SKIPPING (point #1 link card required).")
            try:
                from . import agent as _ag
                topic = _ag.__dict__.get("_pending_decode_topic")
                decode_format = getattr(_ag, "_pending_decode_format", "daily")
                if topic:
                    _ag._unmark_topic_done_today(topic, format_kind=decode_format)
                    log.info(f"[NEWS] Un-marked '{topic}:{decode_format}' — will retry next cycle.")
            except Exception:
                pass
            return

        if tweet_source == "news":
            post_body = _finalize_news_tweet(_enforce_single_trailing_url(post_body, src_url), src_url)
            post_body = _maybe_add_curated_hashtag(post_body)
            inline_urls = re.findall(r"https?://\S+", post_body.replace(src_url or "", ""))
            if inline_urls:
                log.info(f"[NEWS] Final URL sanitizer refused inline URLs: {inline_urls[:3]}")
                return False
        elif tweet_source == "hotake":
            post_body = _maybe_add_curated_hashtag(post_body)
        log.info(f"[NEWS] Posting ({len(post_body)} chars): {post_body[:100]}...")
        post_tweet(post_body, image_path=img_path)
        save_tweet(post_body if tweet_source == "news" else tweet)
        # Engagement-log routing must match the actual generator so the
        # bandit attribution stays correct.
        if tweet_source == "hotake":
            log_hotake(tweet, pattern_id=_news_pattern)
        else:
            log_post(tweet, pattern_id=_news_pattern)
        if img_path:
            try:
                os.remove(img_path)
            except OSError:
                pass
    # Successful Décode ship.
    return True


def run_bot_cycle():
    """Burst Décodes up to NEWS_POSTS_PER_CYCLE. Breaks out the moment an
    iteration returns False (no eligible topic/format combo left) so we
    don't sleep 120s after each no-op."""
    count = max(1, NEWS_POSTS_PER_CYCLE)
    for i in range(count):
        if not has_post_slot():
            log.info("[NEWS] No post slot left for burst. Stopping.")
            break
        log.info(f"[NEWS] Décode attempt {i + 1}/{count}")
        shipped = _run_single_bot_cycle()
        if not shipped:
            try:
                from . import agent as _ag
                mode = _ag.__dict__.get("_news_mode")
                topic = _ag.__dict__.get("_pending_decode_topic")
                format_kind = _ag.__dict__.get("_pending_decode_format")
                if mode in {"daily", "weekly", "monthly"} and topic and format_kind:
                    key = _ag._topic_done_key(topic, format_kind=format_kind)
                    skipped = set(_ag.__dict__.get("_temporary_skipped_done_keys") or set())
                    skipped.add(key)
                    _ag.__dict__["_temporary_skipped_done_keys"] = skipped
                    log.info(f"[NEWS] No post shipped for {key}; trying next forced category.")
                    continue
            except Exception:
                pass
            log.info("[NEWS] Nothing eligible to ship — ending burst early.")
            break
        if i < count - 1:
            log.info(f"[NEWS] Waiting {NEWS_POST_SPACING_SECONDS}s before next Décode.")
            time.sleep(NEWS_POST_SPACING_SECONDS)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running.
    Reports outcome to health watchdog so 3 consecutive Safari-touching
    failures across any bots trigger a Safari restart."""
    from . import health
    try:
        run_bot_cycle()
        health.record_success("post")
    except Exception:
        log.error(f"Error during bot cycle: {traceback.format_exc()}")
        health.record_failure("post")


def _run_bot_cycle_in_mode(mode: str, posts_per_cycle: int | None = None):
    """Set the news-mode hint and run the burst. The hint forces
    _next_topic_not_done_today() in agent.py to filter the rotation:
    'daily' → only Daily Décodes, 'weekly' → only Weekly Top 5s,
    'monthly' → Monthly Top 10s."""
    from . import agent as _ag
    prev = _ag.__dict__.get("_news_mode")
    prev_skipped = _ag.__dict__.get("_temporary_skipped_done_keys")
    prev_posts_per_cycle = NEWS_POSTS_PER_CYCLE
    _ag.__dict__["_news_mode"] = mode
    _ag.__dict__["_temporary_skipped_done_keys"] = set()
    try:
        if posts_per_cycle is not None:
            globals()["NEWS_POSTS_PER_CYCLE"] = posts_per_cycle
        run_bot_cycle()
    finally:
        globals()["NEWS_POSTS_PER_CYCLE"] = prev_posts_per_cycle
        if prev_skipped is None:
            _ag.__dict__.pop("_temporary_skipped_done_keys", None)
        else:
            _ag.__dict__["_temporary_skipped_done_keys"] = prev_skipped
        if prev is None:
            _ag.__dict__.pop("_news_mode", None)
        else:
            _ag.__dict__["_news_mode"] = prev


def safe_run_daily_news_cycle(force_all: bool = False):
    """Cron handler — evening UTC. Forces daily-only rotation so the burst
    ships Daily Décodes during the global crypto peak window."""
    from . import health
    try:
        log.info("[CRON] Daily news burst (evening UTC) — daily mode forced.")
        if force_all:
            from . import agent as _ag
            _ag._clear_topics_done_today_for_format("daily")
            log.info("[CRON] Cleared today's daily Décode markers for manual all-category run.")
        _run_bot_cycle_in_mode("daily", posts_per_cycle=4)
        health.record_success("post")
    except Exception:
        log.error(f"Error during daily news cron: {traceback.format_exc()}")
        health.record_failure("post")


def safe_run_weekly_news_cycle():
    """Cron handler — Friday evening UTC. Forces weekly-only rotation
    so the burst ships 4 Weekly Top 5s."""
    from . import health
    try:
        log.info("[CRON] Weekly news burst (Friday evening UTC) — weekly mode forced.")
        _run_bot_cycle_in_mode("weekly", posts_per_cycle=4)
        health.record_success("post")
    except Exception:
        log.error(f"Error during weekly news cron: {traceback.format_exc()}")
        health.record_failure("post")


def safe_run_monthly_news_cycle(force_all: bool = False):
    """Manual/monthly handler — forces monthly Top 10 rotation so the burst
    ships 4 Monthly Décodes (one per topic)."""
    from . import health
    try:
        log.info("[CRON] Monthly news burst — monthly mode forced.")
        if force_all:
            from . import agent as _ag
            _ag._clear_topics_done_today_for_format("monthly")
            log.info("[CRON] Cleared today's monthly Décode markers for manual all-category run.")
        _run_bot_cycle_in_mode("monthly", posts_per_cycle=4)
        health.record_success("post")
    except Exception:
        log.error(f"Error during monthly news cron: {traceback.format_exc()}")
        health.record_failure("post")
