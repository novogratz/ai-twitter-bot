"""src/replies/direct_reply: reply lane, query rotation and the VIP
ReplyCalls."""


def _url_with_age(minutes: int) -> str:
    from tests.helpers import status_id
    return f"https://x.com/someone/status/{status_id(minutes)}"


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
    from src.replies.reply_source import is_on_niche
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

    # ⚠️ Both lanes look scrape_x_search up on direct_reply (#243): patch
    # it there. (A version of this test patched the wrong module — the real
    # Safari fired and posted live replies to @TheBTCTherapist mid-test.
    # conftest's _no_safari wall now makes that mistake fail loudly instead.)
    settings_override(VIP_SCAN_HANDLES="TheBTCTherapist")
    url = _url_with_age(5).replace("/someone/", "/TheBTCTherapist/")
    monkeypatch.setattr(dr, "scrape_x_search",
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
    Relation with a prompt and no provider keeps the VIP scan's call, the
    priority Reply's (#248)."""
    import shutil
    from src.core import account
    from src.core.llm_client import TEXT_PROFILE, Surface
    from src.replies import direct_reply as dr

    relations = account.current().relations
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    own = dr._vip_call("graphseo")
    assert (own.template, own.surface, own.label) == (relations.get("Graphseo").prompt,
                                                      Surface.RELATION_REPLY, "GRAPHSEO_VIP")
    assert (own.text_limit, own.strip_preamble, own.skip_window) == (1200, False, 0)
    assert (own.provider, own.profile) == ("claude", TEXT_PROFILE)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert dr._vip_call("Graphseo").provider is None

    bestie, buddy = dr._vip_call("thebtctherapist"), dr._vip_call("vision_ia")
    assert (bestie.template, bestie.label) == (relations.get("TheBTCTherapist").prompt,
                                               "VIP_REPLY/thebtctherapist")
    assert (buddy.template, buddy.label) == (relations.default, "VIP_REPLY/vision_ia")
    for call in (bestie, buddy):
        assert (call.surface, call.text_limit, call.strip_preamble, call.skip_window,
                call.provider, call.profile) == (Surface.PRIORITY_REPLY, 1200,
                                                 True, 20, None, TEXT_PROFILE)


def test_a_relation_without_its_cli_warns_of_the_provider_it_falls_back_on(monkeypatch, settings_override):
    """The Operator, 2026-09-28 (#248): a Relation whose CLI is missing
    falls back on the Reply provider, and says so, naming both. When the
    Reply provider is that missing CLI, the warning says the Reply fails."""
    import shutil

    from src.replies import direct_reply as dr

    warnings = []
    monkeypatch.setattr(dr.log, "warning", lambda msg, *a, **k: warnings.append(msg))
    settings_override(AI_CLI="codex", REPLY_LLM_PROVIDER="gemini")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    dr._vip_call("Graphseo")
    assert warnings == []

    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert dr._vip_call("Graphseo").provider is None
    assert warnings == ["[VIP] Relation @Graphseo: claude is not installed, "
                        "the Reply goes to the Reply provider (gemini)."]

    settings_override(REPLY_LLM_PROVIDER="")
    dr._vip_call("Graphseo")
    assert warnings[-1] == ("[VIP] Relation @Graphseo: claude is not installed, "
                            "the Reply goes to the Reply provider (codex).")

    settings_override(REPLY_LLM_PROVIDER="Claude")
    dr._vip_call("Graphseo")
    assert warnings[-1] == ("[VIP] Relation @Graphseo: claude is not installed, it is the Reply provider "
                            "too: the Reply fails, or goes to the fallback CLI if one is set.")


def test_the_vip_scan_warns_of_a_missing_cli_once_per_generation(monkeypatch, llm, chokepoint,
                                                                 settings_override):
    """The scan's check for a prompt builds no call and warns of nothing;
    each Reply generated for the Relation warns once."""
    import shutil

    from src.replies import direct_reply as dr, reply_pipeline

    warnings = []
    monkeypatch.setattr(dr.log, "warning", lambda msg, *a, **k: warnings.append(msg))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    settings_override(VIP_SCAN_HANDLES="Graphseo")
    tweets = []
    monkeypatch.setattr(dr, "scrape_x_search", lambda q, max_tweets=20, tab="latest": list(tweets))

    dr._run_vip_scan(reply_pipeline.Cycle())
    assert warnings == [] and llm.calls == []

    tweets.append({"url": _url_with_age(5).replace("/someone/", "/Graphseo/"),
                   "text": "les agents IA changent le SEO", "author": "Graphseo"})
    dr._run_vip_scan(reply_pipeline.Cycle())
    assert len(llm.calls) == 1
    assert len(warnings) == 1 and "claude is not installed" in warnings[0]


def test_the_vip_scan_skips_a_handle_without_a_prompt(monkeypatch, llm, settings_override):
    """An Account without a default prompt starts only while every
    vip_scan handle has its own; a VIP_SCAN_HANDLES from .env past them
    skips the handle instead of calling the model without a prompt."""
    import dataclasses
    from src.core import account
    from src.replies import direct_reply as dr, reply_pipeline

    loaded = account.current()
    bare = dataclasses.replace(loaded, relations=dataclasses.replace(loaded.relations, default=None))
    monkeypatch.setattr(account, "current", lambda: bare)
    settings_override(VIP_SCAN_HANDLES="vision_ia")
    scraped = []
    monkeypatch.setattr(dr, "scrape_x_search", lambda *a, **k: scraped.append(a) or [])

    assert dr._vip_call("vision_ia") is None
    assert dr._run_vip_scan(reply_pipeline.Cycle()) == 0
    assert scraped == [] and llm.calls == []
