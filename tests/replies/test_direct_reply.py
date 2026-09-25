"""src/replies/direct_reply: reply lane, candidate order, query rotation and
the VIP ReplyCalls."""


def _url_with_age(minutes: int) -> str:
    from datetime import datetime, timezone
    from src.x.x_urls import _TWITTER_EPOCH_MS
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    tweet_id = (now_ms - minutes * 60_000 - _TWITTER_EPOCH_MS) << 22
    return f"https://x.com/someone/status/{tweet_id}"


def test_reply_candidates_sorted_fresh_and_rising_first():
    """2026-06-07 spec: front-load fresh fast-rising posts. A 20-min riser
    must beat a 60-hour-old tweet; unknown-age URLs go last; within the
    same freshness bucket, higher likes-per-hour wins."""
    from src.replies.direct_reply import freshness_sort_key
    fresh_hot = {"url": _url_with_age(20), "likes": 400}
    fresh_cold = {"url": _url_with_age(25), "likes": 2}
    old = {"url": _url_with_age(60 * 60), "likes": 90000}
    unknown = {"url": "https://x.com/someone", "likes": 50}
    ordered = sorted([unknown, old, fresh_cold, fresh_hot], key=freshness_sort_key)
    assert ordered[0] is fresh_hot
    assert ordered[1] is fresh_cold
    assert ordered[2] is old
    assert ordered[3] is unknown


def _searches():
    """The direct_reply queries of the loaded Account: search, then hot tab."""
    from src.core import account
    searches = account.current().searches
    return list(searches.replies), list(searches.hot_tab)


def test_reply_and_like_queries_are_ai_only():
    """Operator 2026-09-25: AI only, like the policy (#205). Every reply and
    like query carries an AI term, and none looks for crypto, markets or
    space posts."""
    from src.core import account
    replies, hot_tab = _searches()
    queries = replies + hot_tab + list(account.current().searches.likes)
    ai_terms = ("openai", "anthropic", "chatgpt", "claude", "gemini", "grok",
                "ai ", "\"ai", " ai)", "agi", "nvidia", "gpu", "llama", "deepseek",
                "cursor", "copilot", "humanoid", "robotics", " ia ")
    for q in queries:
        assert any(t in " " + q.lower() for t in ai_terms), f"no AI term in {q!r}"
    joined = " ".join(queries).lower()
    for banned in ("bitcoin", "btc", "crypto", "ethereum", "bittensor", "stock", "market",
                   "earnings", "etf", "portfolio", "sell off", "vix", "spacex", "starlink",
                   "starship", "nasa", "satellite", "orbit"):
        assert banned not in joined, f"{banned!r} is off the AI niche"


def _query_clauses(query: str, and_first: bool) -> list:
    """The alternatives of an X search query, each the list of terms a
    matching post holds. X's precedence of implicit AND and OR is not pinned,
    so the caller reads the query both ways."""
    import re
    tokens = [t for t in re.findall(r'"[^"]*"|\(|\)|[^\s()]+', query)
              if not re.fullmatch(r"\w+:\S+", t)]
    pos = 0

    def atom():
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        if tok == "(":
            inner = expr()
            pos += 1
            return inner
        return [[tok.strip('"')]]

    def conj(parts):
        clauses = [[]]
        for part in parts:
            clauses = [c + p for c in clauses for p in part]
        return clauses

    def more():
        return pos < len(tokens) and tokens[pos] != ")"

    def expr():
        nonlocal pos
        if and_first:
            alternatives = []
            while True:
                parts = [atom()]
                while more() and tokens[pos] != "OR":
                    parts.append(atom())
                alternatives += conj(parts)
                if not more():
                    return alternatives
                pos += 1
        parts = []
        while more():
            alternatives = atom()
            while more() and tokens[pos] == "OR":
                pos += 1
                alternatives = alternatives + atom()
            parts.append(alternatives)
        return conj(parts)

    return expr()


def test_every_reply_and_like_query_finds_posts_on_the_niche():
    """#205: a query alternative `post` rejects sends the reply jobs posts
    they drop, and the like job, which has no niche check, likes them."""
    from src.core import account
    from src.replies.direct_reply import is_on_niche
    replies, hot_tab = _searches()
    for query in replies + hot_tab + list(account.current().searches.likes):
        for and_first in (True, False):
            for clause in _query_clauses(query, and_first):
                assert is_on_niche(" ".join(clause)), f"{clause} of {query!r}"


def test_the_query_reader_splits_alternatives_both_ways():
    assert _query_clauses("a b OR c lang:en min_faves:5", True) == [["a", "b"], ["c"]]
    assert _query_clauses("a b OR c", False) == [["a", "b"], ["a", "c"]]
    assert _query_clauses('("x y" OR z) (n OR m)', True) == [
        ["x y", "n"], ["x y", "m"], ["z", "n"], ["z", "m"]]
    assert _query_clauses('("x y" OR z) (n OR m)', False) == [
        ["x y", "n"], ["x y", "m"], ["z", "n"], ["z", "m"]]


def test_prompts_are_english_only():
    """Operator 2026-06-09: 'we are english only bro'. The reply lane must
    not seek French posts."""
    replies, _ = _searches()
    assert not any("lang:fr" in q for q in replies), "FR reply query still present"


def test_vip_scan_uses_bestie_prompt_for_btctherapist(monkeypatch, llm, chokepoint, settings_override):
    """Bug 2026-06-07 (shipped live, operator: 'why did it reply in french
    to the bitcoin therapist?'): the VIP lane applied the Graphseo FR
    generator (French + deliberate-typo style) to @TheBTCTherapist's
    English post. Pin: VIP replies to the bestie use the EN bestie prompt,
    never the Graphseo prompt (its own Relation prompt); output passes through humanize."""
    import src.replies.direct_reply as dr
    from src.replies import reply_pipeline

    # ⚠️ The VIP scan imports scrape_x_search FUNCTION-LOCALLY from scraper:
    # patch THERE, not on direct_reply. (First version of this test patched
    # dr.* — the real Safari fired and posted live replies to
    # @TheBTCTherapist mid-test. conftest's _no_safari wall now makes that
    # mistake fail loudly instead.)
    from src.x import scraper
    settings_override(VIP_SCAN_HANDLES="TheBTCTherapist")
    url = _url_with_age(30).replace("/someone/", "/TheBTCTherapist/")
    monkeypatch.setattr(scraper, "scrape_x_search",
                        lambda q, max_tweets=20, tab="latest":
                        [{"url": url, "text": "working the weekend because bitcoin", "author": "TheBTCTherapist"}])

    llm.answers["working the weekend"] = "the AI side sends love — and a fruit basket"

    dr._run_vip_scan(reply_pipeline.Cycle())

    assert [c.label for c in llm.calls] == ["VIP_REPLY/TheBTCTherapist"], \
        "Graphseo FR generator must NEVER run for the bestie"
    assert "(The Bitcoin Therapist) is your BEST FRIEND" in llm.prompts[0]
    assert len(chokepoint.calls) == 1
    assert "—" not in chokepoint.calls[0].text, "humanize must strip em dashes from VIP replies"


def test_direct_reply_scans_rotating_query_subset(settings_override):
    """2026-07-10 reply throughput ("you used to be around 900/day now only
    600"): direct_reply scanned ALL ~26 search queries EVERY 1-2 min cycle —
    the same query scraped 4x/hour mostly yields dedup-skips, and search
    scrapes ate the Safari time replies needed for POSTING (~27/hr). Pin the
    contract: each cycle scans a bounded rotating slice, consecutive cycles
    rotate (no slice starvation), full coverage lands within ceil(N/K)
    cycles, and K is read at call time."""
    from src.replies import direct_reply as dr
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=8)
    qs = [f"q{i}" for i in range(26)]
    slices = [dr._queries_for_cycle(qs) for _ in range(4)]
    assert all(len(s) == 8 for s in slices), "cycle must pay for K scrapes only"
    assert slices[0] != slices[1], "consecutive cycles must rotate"
    assert set().union(*(set(s) for s in slices)) == set(qs), \
        "rotation must cover every query within ceil(N/K) cycles"
    # K >= N degrades to scan-everything; K read at call time
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=99)
    assert dr._queries_for_cycle(qs) == qs
    # the live cycle actually routes through the rotation
    import inspect
    src = inspect.getsource(dr.run_direct_reply_cycle)
    assert "_queries_for_cycle" in src, \
        "run_direct_reply_cycle must scan the rotating slice, not all queries"


def test_the_vip_calls_keep_their_shape_with_the_accounts_prompts(monkeypatch):
    """#203 moved the relation prompts into the Account's Relations: each VIP
    ReplyCall keeps its label, limits and provider, and the engine names no
    one. A Relation's provider is forced only when its CLI is installed; a
    Relation with a prompt and no provider keeps the VIP scan's call."""
    import shutil
    from src.core import account, config
    from src.replies import direct_reply as dr
    from src.replies.reply_generator import CallOptions

    relations = account.current().relations
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    own = dr._vip_call("graphseo")
    assert (own.template, own.model, own.label) == (relations.get("Graphseo").prompt,
                                                    config.PRIORITY_REPLY_MODEL, "GRAPHSEO_VIP")
    assert (own.dossier, own.text_limit, own.max_chars, own.strip_preamble, own.skip_window) == (
        False, 300, 220, False, 0)
    assert own.options == CallOptions(output_json=False, timeout=60, force_provider="claude")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert dr._vip_call("Graphseo").options.force_provider is None

    bestie, buddy = dr._vip_call("thebtctherapist"), dr._vip_call("vision_ia")
    assert (bestie.template, bestie.label) == (relations.get("TheBTCTherapist").prompt,
                                               "VIP_REPLY/thebtctherapist")
    assert (buddy.template, buddy.label) == (relations.default, "VIP_REPLY/vision_ia")
    for call in (bestie, buddy):
        assert (call.model, call.dossier, call.text_limit, call.strip_preamble, call.skip_window,
                call.max_chars, call.options) == (config.PRIORITY_REPLY_MODEL, False, 300, True, 20, None,
                                                  CallOptions())


def test_the_vip_scan_skips_a_handle_without_a_prompt(monkeypatch, llm, settings_override):
    """An Account without a default prompt starts only while every
    vip_scan handle has its own; a VIP_SCAN_HANDLES from .env past them
    skips the handle instead of calling the model without a prompt."""
    import dataclasses
    from src.core import account
    from src.replies import direct_reply as dr, reply_pipeline
    from src.x import scraper

    loaded = account.current()
    bare = dataclasses.replace(loaded, relations=dataclasses.replace(loaded.relations, default=None))
    monkeypatch.setattr(account, "current", lambda: bare)
    settings_override(VIP_SCAN_HANDLES="vision_ia")
    scraped = []
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: scraped.append(a) or [])

    assert dr._vip_call("vision_ia") is None
    assert dr._run_vip_scan(reply_pipeline.Cycle()) == 0
    assert scraped == [] and llm.calls == []
