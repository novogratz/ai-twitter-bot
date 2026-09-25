"""src/replies/direct_reply: reply lane, candidate order, query rotation and
the VIP voices."""


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


def test_reply_queries_are_on_lane():
    """Spec lane: AI x markets x psychology. NO space content; the tier1-2
    seeds + foils must be scanned directly via from: queries."""
    from src.replies.direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
    joined = " ".join(SEARCH_QUERIES + HOT_TAB_QUERIES).lower()
    for banned in ("spacex", "starship", "nasa", "satellite", "rocket lab", "orbit"):
        assert banned not in joined, f"space term {banned!r} is off-persona"
    for seed in ("from:thebtctherapist", "from:morganhousel", "from:saylor"):
        assert seed in joined, f"missing seed scan {seed!r}"
    # Market-trauma VOICE still represented (panic/drawdown reply targets),
    # but trimmed to 1 query — operator 2026-06-08 "focus more on AI": the
    # therapist voice frames AI replies; it's no longer a topic lane.
    assert "panic" in joined, "market-trauma voice target missing"


def test_reply_queries_are_ai_first():
    """Operator 2026-06-07: 'bot needs to be more AI focused' / 'i want to
    see more AI shit'. The reply lane must be majority-AI: at least half of
    the search queries carry an AI term, BTC tail stays minimal (feud lane
    only, ≤2 queries)."""
    from src.replies.direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
    ai_terms = ("openai", "anthropic", "chatgpt", "claude", "gemini", "grok",
                "ai ", "\"ai", "agi", "nvidia", "gpu", "llama", "deepseek",
                "palantir", "cursor", "copilot", "tsmc", "humanoid", " ia ")
    def is_ai(q):
        ql = " " + q.lower()
        return any(t in ql for t in ai_terms)
    topic_queries = [q for q in SEARCH_QUERIES if not q.startswith("from:")]
    ai_count = sum(1 for q in topic_queries if is_ai(q))
    assert ai_count * 2 >= len(topic_queries), \
        f"AI queries must be the majority of the reply lane ({ai_count}/{len(topic_queries)})"
    btc_only = [q for q in topic_queries
                if ("bitcoin" in q.lower() or "btc" in q.lower()) and not is_ai(q)]
    assert len(btc_only) <= 2, "BTC tail must stay minimal (feud lane only)"
    hot_ai = sum(1 for q in HOT_TAB_QUERIES if is_ai(q))
    assert hot_ai * 2 >= len(HOT_TAB_QUERIES)


def test_prompts_are_english_only():
    """Operator 2026-06-09: 'we are english only bro'. The reply lane must
    not seek French posts."""
    from src.replies.direct_reply import SEARCH_QUERIES
    assert not any("lang:fr" in q for q in SEARCH_QUERIES), "FR reply query still present"


def test_vip_scan_uses_bestie_prompt_for_btctherapist(monkeypatch, llm, chokepoint):
    """Bug 2026-06-07 (shipped live, operator: 'why did it reply in french
    to the bitcoin therapist?'): the VIP lane applied the Graphseo FR
    generator (French + deliberate-typo style) to @TheBTCTherapist's
    English post. Pin: VIP replies to the bestie use the EN bestie prompt,
    never the Graphseo voice (_graphseo_voice); output passes through humanize."""
    import src.replies.direct_reply as dr
    from src.replies import reply_pipeline

    # ⚠️ The VIP scan imports scrape_x_search FUNCTION-LOCALLY from scraper:
    # patch THERE, not on direct_reply. (First version of this test patched
    # dr.* — the real Safari fired and posted live replies to
    # @TheBTCTherapist mid-test. conftest's _no_safari wall now makes that
    # mistake fail loudly instead.)
    from src.x import scraper
    monkeypatch.setenv("VIP_SCAN_HANDLES", "TheBTCTherapist")
    url = _url_with_age(30).replace("/someone/", "/TheBTCTherapist/")
    monkeypatch.setattr(scraper, "scrape_x_search",
                        lambda q, max_tweets=20, tab="latest":
                        [{"url": url, "text": "working the weekend because bitcoin", "author": "TheBTCTherapist"}])

    llm.answers["working the weekend"] = "the AI side sends love — and a fruit basket"

    dr._run_graphseo_scan(reply_pipeline.Cycle())

    assert [c.label for c in llm.calls] == ["VIP_REPLY/TheBTCTherapist"], \
        "Graphseo FR generator must NEVER run for the bestie"
    assert "(The Bitcoin Therapist) is your BEST FRIEND" in llm.prompts[0]
    assert len(chokepoint.calls) == 1
    assert "—" not in chokepoint.calls[0].text, "humanize must strip em dashes from VIP replies"


def test_direct_reply_scans_rotating_query_subset(monkeypatch):
    """2026-07-10 reply throughput ("you used to be around 900/day now only
    600"): direct_reply scanned ALL ~26 search queries EVERY 1-2 min cycle —
    the same query scraped 4x/hour mostly yields dedup-skips, and search
    scrapes ate the Safari time replies needed for POSTING (~27/hr). Pin the
    contract: each cycle scans a bounded rotating slice, consecutive cycles
    rotate (no slice starvation), full coverage lands within ceil(N/K)
    cycles, and the K env is read at call time."""
    from src.replies import direct_reply as dr
    monkeypatch.setenv("DIRECT_REPLY_QUERIES_PER_CYCLE", "8")
    qs = [f"q{i}" for i in range(26)]
    slices = [dr._queries_for_cycle(qs) for _ in range(4)]
    assert all(len(s) == 8 for s in slices), "cycle must pay for K scrapes only"
    assert slices[0] != slices[1], "consecutive cycles must rotate"
    assert set().union(*(set(s) for s in slices)) == set(qs), \
        "rotation must cover every query within ceil(N/K) cycles"
    # K >= N degrades to scan-everything; env read at call time
    monkeypatch.setenv("DIRECT_REPLY_QUERIES_PER_CYCLE", "99")
    assert dr._queries_for_cycle(qs) == qs
    # the live cycle actually routes through the rotation
    import inspect
    src = inspect.getsource(dr.run_direct_reply_cycle)
    assert "_queries_for_cycle" in src, \
        "run_direct_reply_cycle must scan the rotating slice, not all queries"
