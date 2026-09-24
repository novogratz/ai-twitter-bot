"""src/replies/direct_reply: reply lane, candidate order, pipeline and the
VIP scan."""
from src.guards import replied_store as rs


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
    from src.replies.direct_reply import _freshness_sort_key
    fresh_hot = {"url": _url_with_age(20), "likes": 400}
    fresh_cold = {"url": _url_with_age(25), "likes": 2}
    old = {"url": _url_with_age(60 * 60), "likes": 90000}
    unknown = {"url": "https://x.com/someone", "likes": 50}
    ordered = sorted([unknown, old, fresh_cold, fresh_hot], key=_freshness_sort_key)
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


def test_reply_callers_never_premark_store(monkeypatch, tmp_path, llm):
    """2026-06-07 post-mortem: five bots 'locked the URL in BEFORE posting'
    (save_replied premark) — the reply chokepoint (2026-06-05) loads that
    same store and silently refused its OWN caller's reply, 100% of the
    time, while unconditional log_reply calls wrote phantom rows into
    engagement_log. Contract pinned here: (1) the on-disk store must NOT
    contain the URL at the moment reply_to_tweet is invoked; (2) log_reply
    fires ONLY when reply_to_tweet returns True."""
    import src.replies.direct_reply as dr

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    url = _url_with_age(5)
    tweets = [{"url": url, "text": "nvidia margins at 75 percent again", "author": "some_ai_account"}]

    premarked_at_call = []
    def fake_reply(u, text):
        premarked_at_call.append(u in rs.load_replied())
        return True
    logged = []
    monkeypatch.setattr(dr, "reply_to_tweet", fake_reply)
    monkeypatch.setattr(dr, "humanize", lambda t: t)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(dr, "_is_on_niche", lambda t: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 1000, 0))

    n = dr._reply_to_tweets(tweets, set(), "SEARCH-HOT", en_counter=[0])
    assert premarked_at_call == [False], \
        "caller premarked the store — the chokepoint would refuse its own reply"
    assert n == 1 and len(logged) == 1

    # Chokepoint refusal (False) → no phantom engagement_log row, posted=0.
    logged.clear()
    url2 = _url_with_age(6)
    tweets2 = [{"url": url2, "text": "tsmc capex at 40 billion now", "author": "some_ai_account"}]
    monkeypatch.setattr(dr, "reply_to_tweet", lambda u, t: False)
    n2 = dr._reply_to_tweets(tweets2, set(), "SEARCH-HOT", en_counter=[0])
    assert n2 == 0 and logged == [], \
        "chokepoint skip must not produce a phantom engagement_log row"


def test_vip_scan_uses_bestie_prompt_for_btctherapist(monkeypatch, tmp_path, llm):
    """Bug 2026-06-07 (shipped live, operator: 'why did it reply in french
    to the bitcoin therapist?'): the VIP lane applied the Graphseo FR
    generator (French + deliberate-typo style) to @TheBTCTherapist's
    English post. Pin: VIP replies to the bestie use the EN bestie prompt,
    never the Graphseo voice (_graphseo_voice); output passes through humanize."""
    import src.replies.direct_reply as dr

    # ⚠️ The VIP scan imports scrape_x_search / reply_to_tweet FUNCTION-
    # LOCALLY from scraper / twitter_client — patch THERE, not on direct_reply.
    # (First version of this test patched dr.* — the real Safari fired and
    # posted live replies to @TheBTCTherapist mid-test. conftest's
    # _no_safari wall now makes that mistake fail loudly instead.)
    import src.x.twitter_client as tc
    from src.x import scraper
    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setenv("VIP_SCAN_HANDLES", "TheBTCTherapist")
    url = _url_with_age(30).replace("/someone/", "/TheBTCTherapist/")
    monkeypatch.setattr(scraper, "scrape_x_search",
                        lambda q, max_tweets=20, tab="latest":
                        [{"url": url, "text": "working the weekend because bitcoin", "author": "TheBTCTherapist"}])

    llm.answers["working the weekend"] = "the AI side sends love — and a fruit basket"
    sent = []
    monkeypatch.setattr(tc, "reply_to_tweet", lambda u, t: sent.append(t) or True)
    import src.core.engagement_log as el
    monkeypatch.setattr(el, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)

    dr._run_graphseo_scan(set())

    assert [c.label for c in llm.calls] == ["VIP_REPLY/TheBTCTherapist"], \
        "Graphseo FR generator must NEVER run for the bestie"
    assert llm.prompts[0].startswith(dr.BESTIE_REPLY_PROMPT.split("{author}")[0])
    assert len(sent) == 1
    assert "—" not in sent[0], "humanize must strip em dashes from VIP replies"


def test_startup_reply_warmup_is_bounded(monkeypatch):
    """Operator 2026-06-07: 'more quote retweet on AI'. Root cause was an
    UNBOUNDED startup reply warmup that ran 20+ min and blocked
    scheduler.start() — so the dedicated quote/AI-viral jobs never came
    online (15:43 boot: 300+ replies, 0 quotes). run_direct_reply_cycle
    must honor max_replies and STOP, yielding Safari."""
    import src.replies.direct_reply as dr
    # Every query returns 5 fresh on-niche tweets; without the cap the cycle
    # would reply to all of them across all 21 queries.
    calls = {"replies": 0, "queries": 0}
    def fake_search(q, max_tweets=25, tab="top"):
        calls["queries"] += 1
        base = 2063900000000000000 + calls["queries"] * 100
        return [{"url": f"https://x.com/acct/status/{base+i}",
                 "text": "openai shipped a new reasoning model today", "author": "acct"}
                for i in range(5)]
    def fake_reply_block(tweets, tried, source, source_detail="", remaining=None, en_counter=None, **k):
        # Honor the remaining budget like the real _reply_to_tweets.
        n = len(tweets) if remaining is None else min(len(tweets), remaining)
        calls["replies"] += n
        return n
    monkeypatch.setattr(dr, "scrape_x_search", fake_search)
    monkeypatch.setattr(dr, "_reply_to_tweets", fake_reply_block)
    monkeypatch.setattr(dr, "_run_graphseo_scan", lambda tried, remaining=None, **k: 0)

    dr.run_direct_reply_cycle(max_replies=12)
    assert calls["replies"] == 12, f"warmup must stop at the cap, got {calls['replies']}"
    assert calls["queries"] < 21, "must stop scanning queries once the budget is spent"


def test_direct_reply_default_cycle_is_bounded(monkeypatch):
    """2026-09-23: APScheduler skipped direct_reply_job because a cycle could
    outlive its 2-minute interval. The steady-state call must use the per-cycle
    cap, not the old unbounded None behavior."""
    import src.replies.direct_reply as dr

    calls = {"replies": 0, "queries": 0}

    def fake_search(q, max_tweets=25, tab="top"):
        calls["queries"] += 1
        base = 2063900000000001000 + calls["queries"] * 100
        return [{"url": f"https://x.com/acct/status/{base+i}",
                 "text": "openai shipped a useful model update today", "author": "acct"}
                for i in range(5)]

    def fake_reply_block(tweets, tried, source, source_detail="", remaining=None, en_counter=None, **k):
        n = len(tweets) if remaining is None else min(len(tweets), remaining)
        calls["replies"] += n
        return n

    monkeypatch.setattr(dr, "DIRECT_REPLY_MAX_PER_CYCLE", 3)
    monkeypatch.setattr(dr, "scrape_x_search", fake_search)
    monkeypatch.setattr(dr, "_reply_to_tweets", fake_reply_block)
    monkeypatch.setattr(dr, "_run_graphseo_scan", lambda tried, remaining=None, **k: 0)

    dr.run_direct_reply_cycle()
    assert calls["replies"] == 3
    assert calls["queries"] < 21


def test_reply_pipeline_overlaps_generation_with_posting(monkeypatch, llm):
    """2026-06-09 (operator: 'BOT REALLY SLOW... ACCELERATE'): the reply loop
    serialized a ~30-50s LLM call THEN ~20s of Safari per reply. The pipeline
    must START generating reply N+1 while reply N is still posting — and keep
    the contracts: one gen + one post per candidate, log only on ship."""
    import threading
    from src.replies import direct_reply as dr

    second_gen_started = threading.Event()
    llm.answers["Author: @userb"] = lambda prompt: second_gen_started.set() or \
        "a sharp, substantive take for userb that passes every gate"

    posts = []

    def fake_post(url, reply):
        if not posts:
            # The pipeline guarantee: while the FIRST reply is posting, the
            # SECOND generation has already started.
            assert second_gen_started.wait(timeout=5), \
                "gen of candidate 2 never started during posting of candidate 1 (pipeline broken)"
        posts.append(url)
        return True

    monkeypatch.setattr(dr, "reply_to_tweet", fake_post)
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_is_on_niche", lambda t: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 999, 0))
    monkeypatch.setattr(dr, "humanize", lambda t: t)

    tweets = [
        {"url": _url_with_age(1).replace("/someone/", "/usera/"), "text": "AI thing one", "author": "a"},
        {"url": _url_with_age(2).replace("/someone/", "/userb/"), "text": "AI thing two", "author": "b"},
    ]
    posted = dr._reply_to_tweets(tweets, set(), "SEARCH-TEST")
    assert posted == 2, f"both candidates must ship (posted={posted})"
    assert sorted(llm.parents("Author: @usera", "Author: @userb")) == ["Author: @usera", "Author: @userb"], \
        "exactly one generation per candidate, for the URL handle"
    assert len(posts) == 2

    # remaining bound: with remaining=1, exactly one generation is submitted.
    llm.calls.clear(); posts.clear()
    posted = dr._reply_to_tweets(list(tweets), set(), "SEARCH-TEST", remaining=1, skipped=set())
    assert posted == 1 and len(llm.calls) == 1, \
        "remaining=1 must bound generations AND posts to 1"


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
