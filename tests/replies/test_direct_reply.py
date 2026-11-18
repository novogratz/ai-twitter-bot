"""src/replies/direct_reply: reply lane, query rotation and the VIP
ReplyCalls."""
import pytest



def _url_with_age(minutes: int) -> str:
    from datetime import datetime, timezone
    from src.x.x_urls import _TWITTER_EPOCH_MS
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    tweet_id = (now_ms - minutes * 60_000 - _TWITTER_EPOCH_MS) << 22
    return f"https://x.com/someone/status/{tweet_id}"


def _searches():
    """The direct_reply queries of the loaded Account: search, then hot tab."""
    from src.core import account
    searches = account.current().searches
    return list(searches.replies), list(searches.hot_tab)


def test_queries_stay_in_si_and_the_named_musk_ecosystem():
    """The 2026-10-23 ecosystem expansion keeps general markets out."""
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
                   "earnings", "etf", "portfolio", "sell off", "vix", "nasa", "satellite", "orbit"):
        assert banned not in joined, f"{banned!r} is off the niche"
    assert "grok imagine" in joined
    assert not any(term in joined for term in ("spacex", "starlink", "starship", "x premium", "twitter"))


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
    for query in replies + hot_tab + list(account.current().searches.likes) + list(account.current().searches.creators):
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
    to the bitcoin therapist?'): the VIP lane applied the SpecialVip FR
    generator (French + deliberate-typo style) to @FriendlyVip's
    English post. Pin: VIP replies to the bestie use the EN bestie prompt,
    never the SpecialVip prompt (its own Relation prompt); output passes through humanize."""
    import src.replies.direct_reply as dr
    from src.replies import reply_pipeline

    # ⚠️ The VIP scan imports scrape_x_search FUNCTION-LOCALLY from scraper:
    # patch THERE, not on direct_reply. (First version of this test patched
    # dr.* — the real Safari fired and posted live replies to
    # @FriendlyVip mid-test. conftest's _no_safari wall now makes that
    # mistake fail loudly instead.)
    from src.x import scraper
    settings_override(VIP_SCAN_HANDLES="FriendlyVip")
    url = _url_with_age(30).replace("/someone/", "/FriendlyVip/")
    monkeypatch.setattr(scraper, "scrape_x_search",
                        lambda q, max_tweets=20, tab="latest", text_limit=200:
                        [{"url": url, "text": "working the weekend because bitcoin", "author": "FriendlyVip"}])

    llm.answers["working the weekend"] = "the AI side sends love — and a fruit basket"

    dr._run_vip_scan(reply_pipeline.Cycle())

    assert [c.label for c in llm.calls] == ["VIP_REPLY/FriendlyVip"], \
        "SpecialVip FR generator must NEVER run for the bestie"
    from src.core import account
    expected = account.current().relations.get("FriendlyVip").prompt.format(
        author="friendlyvip", tweet_text="working the weekend because bitcoin")
    assert expected in llm.prompts[0]
    assert len(chokepoint.calls) == 1
    assert "—" not in chokepoint.calls[0].text, "humanize must strip em dashes from VIP replies"


@pytest.mark.parametrize("boosted", [False, True])
def test_direct_reply_scans_rotating_query_subset(settings_override, boosted):
    """2026-07-10 reply throughput ("you used to be around 900/day now only
    600"): direct_reply scanned ALL ~26 search queries EVERY 1-2 min cycle —
    the same query scraped 4x/hour mostly yields dedup-skips, and search
    scrapes ate the Safari time replies needed for POSTING (~27/hr). Pin the
    contract: each cycle scans a bounded rotating slice, consecutive cycles
    rotate (no slice starvation), full coverage lands within ceil(N/K)
    cycles, and K is read at call time."""
    from src.replies import direct_reply as dr
    from src.guards import active_hours
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=8,
                      REPLY_VOLUME_BOOST_DATE=active_hours.today_iso() if boosted else "")
    qs = [f"q{i}" for i in range(26)]
    slices = [dr._queries_for_cycle(qs) for _ in range(4)]
    expected = 16 if boosted else 8
    assert all(len(s) == expected for s in slices), "cycle must pay for K scrapes only"
    assert slices[0] != slices[1], "consecutive cycles must rotate"
    assert set().union(*(set(s) for s in slices)) == set(qs), \
        "rotation must cover every query within ceil(N/K) cycles"
    # K >= N degrades to scan-everything; K read at call time
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=99)
    assert dr._queries_for_cycle(qs) == qs


def test_the_vip_calls_keep_their_shape_with_the_accounts_prompts(monkeypatch):
    """#203 moved the relation prompts into the Account's Relations: each VIP
    ReplyCall keeps its label, limits and provider, and the engine names no
    one. A Relation's provider is forced only when its CLI is installed; a
    Relation with a prompt and no provider keeps the VIP scan's call."""
    import shutil
    from src.core import account
    from src.core.llm_client import TEXT_PROFILE, Surface
    from src.replies import direct_reply as dr

    relations = account.current().relations
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    own = dr._vip_call("specialvip")
    assert (own.template, own.surface, own.label) == (relations.get("SpecialVip").prompt,
                                                      Surface.RELATION_REPLY, "SPECIALVIP_VIP")
    assert (own.dossier, own.text_limit, own.max_chars, own.strip_preamble, own.skip_window) == (
        False, 1200, 278, False, 0)
    assert (own.provider, own.profile) == ("codex", TEXT_PROFILE)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert dr._vip_call("SpecialVip").provider is None

    bestie, buddy = dr._vip_call("friendlyvip"), dr._vip_call("vision_ia")
    assert (bestie.template, bestie.label) == (relations.get("FriendlyVip").prompt,
                                               "VIP_REPLY/friendlyvip")
    assert (buddy.template, buddy.label) == (relations.default, "VIP_REPLY/vision_ia")
    for call in (bestie, buddy):
        assert (call.surface, call.dossier, call.text_limit, call.strip_preamble, call.skip_window,
                call.max_chars, call.provider, call.profile) == (Surface.PRIORITY_REPLY_ON_AI_CLI, False, 1200,
                                                                 True, 20, None, None, TEXT_PROFILE)


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


def test_latest_lane_keeps_first_hour_posts_without_a_popularity_floor():
    from src.replies import direct_reply
    fresh_url, old_url = _url_with_age(20), _url_with_age(120)
    posts = [{"url": fresh_url, "text": "My SI video workflow", "likes": 0},
             {"url": old_url, "text": "My SI video workflow", "likes": 9000}]
    selected = direct_reply._search_candidates(posts, "SI video", "latest")
    assert [c.url for c in selected] == [fresh_url]
    assert selected[0].source.startswith("SEARCH-FRESH/")


def test_quoted_evidence_reaches_generation_without_changing_the_parent():
    from src.replies import direct_reply
    parent = _url_with_age(20)
    posts = [{"url": parent, "text": "Yes", "quoted_text": "New SI video generation workflow"}]
    selected = direct_reply._search_candidates(posts, "SI video", "latest")
    assert len(selected) == 1 and selected[0].url == parent
    assert selected[0].text.startswith("Yes\nQuoted post")
    assert not selected[0].is_reply
    posts[0]["is_reply"] = True
    assert direct_reply._search_candidates(posts, "SI video", "latest") == []


def _discovery_account(monkeypatch, *, groups=10, top=14, latest=12, creators=0):
    from dataclasses import replace
    from src.core import account

    loaded = account.current()
    custom = replace(loaded, network=replace(loaded.network,
        big_ai_hype=tuple(f"priority{i}" for i in range(groups * 6))),
        searches=replace(loaded.searches, replies=tuple(f"SI top {i}" for i in range(top)),
                         hot_tab=(), latest=tuple(f"SI latest {i}" for i in range(latest)),
                         creators=tuple(f"SI creator {i}" for i in range(creators))))
    monkeypatch.setattr(account, "current", lambda: custom)
    return custom


def test_priority_top_and_latest_pools_rotate_within_one_total_budget(monkeypatch, settings_override):
    from src.replies import direct_reply as dr

    _discovery_account(monkeypatch)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=16, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4,
                      DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4, REPLY_VOLUME_BOOST_DATE="")
    plans = [dr._query_plan() for _ in range(3)]
    for priority, creators, ordinary in plans:
        assert creators == []
        assert len(priority) == 4 and len(ordinary) == 12
        assert sum(tab == "top" for _, tab, _ in ordinary) == 8
        assert sum(tab == "latest" for _, tab, _ in ordinary) == 4
        assert len(set(priority + ordinary)) == 16
        assert all(tab == "latest" and len(authors) == 6 for _, tab, authors in priority)
        assert all(f"from:{author}" in query for query, _, authors in priority for author in authors)
        assert all(all(term in query for term in ("AI OR SI OR ASI", "superintelligence", "Codex", "CUDA"))
                   and len(query) < 500 for query, _, _ in priority)
    assert len({query for priority, _, _ in plans for query, _, _ in priority}) == 10
    assert len({query for _, _, ordinary in plans for query, tab, _ in ordinary if tab == "top"}) == 14
    assert len({query for _, _, ordinary in plans for query, tab, _ in ordinary if tab == "latest"}) == 12


@pytest.mark.parametrize("total,priority,latest,groups,top_pool,latest_pool,expected", [
    (16, 4, 4, 0, 14, 12, (0, 12, 4)),
    (16, 4, 4, 2, 2, 12, (2, 2, 12)),
    (3, 4, 4, 10, 14, 12, (3, 0, 0)),
    (16, 0, 4, 10, 2, 2, (0, 2, 2)),
    (8, 4, 99, 10, 14, 12, (4, 0, 4)),
])
def test_query_plan_clamps_requests_and_backfills_only_available_unique_queries(
        monkeypatch, settings_override, total, priority, latest, groups, top_pool, latest_pool, expected):
    from src.replies import direct_reply as dr

    _discovery_account(monkeypatch, groups=groups, top=top_pool, latest=latest_pool)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=total, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=priority,
                      DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=latest, REPLY_VOLUME_BOOST_DATE="")
    selected, creators, ordinary = dr._query_plan()
    assert creators == []
    assert (len(selected), sum(tab == "top" for _, tab, _ in ordinary),
            sum(tab == "latest" for _, tab, _ in ordinary)) == expected
    assert len(set(selected + ordinary)) == len(selected + ordinary) <= total


def test_grouped_latest_requires_exact_url_author_standalone_niche_and_24_hour_age(monkeypatch, settings_override):
    from dataclasses import replace
    from src.core import account
    from src.replies import direct_reply as dr
    from tests.helpers import fresh

    loaded = replace(account.current(), engagement_niche_only=True)
    monkeypatch.setattr(account, "current", lambda: loaded)
    allowed = {"url": fresh("priority", minutes=23 * 60), "text": "New SI inference model",
               "likes": 0, "views": 1234}
    unrelated = {**allowed, "url": fresh("other", n=1), "author": "priority"}
    nested = {**allowed, "url": fresh("priority", n=2), "is_reply": True}
    stale = {**allowed, "url": fresh("priority", minutes=24 * 60 + 1, n=3)}
    future = {**allowed, "url": fresh("priority", minutes=-1, n=4)}
    off_topic = {**allowed, "url": fresh("priority", n=5), "text": "AI crypto trading returns"}
    selected = dr._search_candidates([unrelated, nested, stale, future, off_topic, allowed],
                                     "from:priority", "latest", expected_authors=("PRIORITY",))
    assert len(selected) == 1 and selected[0].url == allowed["url"]
    assert selected[0].views == 1234 and selected[0].likes == 0
    assert selected[0].source.startswith("SEARCH-PRIORITY/")
    assert dr._search_candidates([allowed], "SI model", "latest") == []
    settings_override(DIRECT_REPLY_MAX_AGE_MINUTES=60)
    assert dr._search_candidates([allowed], "from:priority", "latest", expected_authors=("priority",)) == []


def test_priority_groups_are_discovered_before_a_full_ordinary_buffer_is_drafted(
        monkeypatch, settings_override, llm, chokepoint):
    from datetime import timedelta
    from src.replies import candidate_buffer, direct_reply as dr, reply_pipeline
    from tests.helpers import fresh

    _discovery_account(monkeypatch, groups=4)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=16, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4,
                      DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4, REPLY_PRIORITIZE_LARGE_ACCOUNTS=True,
                      VIP_SCAN_HANDLES="", REPLY_VOLUME_BOOST_DATE="")
    candidate_buffer.SEARCH.offer([reply_pipeline.Candidate(fresh("small"), "SI model project", "FEED",
                                                           likes=100, views=1_000_000)],
                                  max_age=timedelta(hours=1))
    groups = {query: authors for query, _, authors in dr._priority_searches()}
    reads, trace, expected = [], [], []

    def scrape(query, **kwargs):
        reads.append(query)
        trace.append("read")
        authors = groups[query]  # No ordinary search fits after the first confirmed Reply.
        url = fresh(authors[0], minutes=23 * 60, n=len(reads))
        expected.append(url)
        return [{"url": url, "text": "New SI model project", "likes": 0, "views": len(reads) * 1000}]

    def draft(_):
        trace.append("draft")
        return "A local SI model makes offline work easier."

    monkeypatch.setattr(dr, "scrape_x_search", scrape)
    llm.default = draft
    dr.run_direct_reply_cycle(max_replies=1)
    assert len(reads) == 4 and trace[:4] == ["read"] * 4
    assert chokepoint.sent == [expected[-1]]
    assert any(item.url.startswith("https://x.com/small/") for item in candidate_buffer.SEARCH.pending())


def test_a_full_empty_discovery_pass_reads_exactly_the_selected_16_queries(
        monkeypatch, settings_override, llm, chokepoint):
    from src.replies import direct_reply as dr

    _discovery_account(monkeypatch)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=16, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4,
                      DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4, VIP_SCAN_HANDLES="", REPLY_VOLUME_BOOST_DATE="")
    reads = []
    monkeypatch.setattr(dr, "scrape_x_search", lambda query, **kwargs: reads.append((query, kwargs["tab"])) or [])
    dr.run_direct_reply_cycle()
    assert len(reads) == len(set(reads)) == 16
    assert all(query.startswith("(from:") and tab == "latest" for query, tab in reads[:4])
    assert sum(tab == "top" for _, tab in reads[4:]) == 8
    assert sum(tab == "latest" for _, tab in reads[4:]) == 4
    assert llm.calls == [] and chokepoint.sent == []


def test_artist_searches_rotate_within_the_existing_16_read_budget(monkeypatch, settings_override):
    from src.replies import direct_reply as dr

    _discovery_account(monkeypatch, creators=6)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=16, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4,
                      DIRECT_REPLY_CREATOR_QUERIES_PER_CYCLE=2, DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4,
                      REPLY_VOLUME_BOOST_DATE="")
    plans = [dr._query_plan() for _ in range(3)]
    for priority, creators, ordinary in plans:
        assert len(priority) == 4 and len(creators) == 2
        assert sum(tab == "top" for _, tab, _ in ordinary) == 6
        assert sum(tab == "latest" for _, tab, _ in ordinary) == 4
        assert all(tab == "latest" and authors == () for _, tab, authors in creators)
        assert len(set(priority + creators + ordinary)) == 16
    assert len({query for _, creators, _ in plans for query, _, _ in creators}) == 6


@pytest.mark.parametrize("total,requested,expected", [(3, 2, 0), (5, 16, 1), (16, 0, 0), (16, 2, 2)])
def test_artist_allocation_is_optional_and_cannot_exceed_total(monkeypatch, settings_override, total, requested, expected):
    from src.replies import direct_reply as dr

    _discovery_account(monkeypatch, creators=6)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=total, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4,
                      DIRECT_REPLY_CREATOR_QUERIES_PER_CYCLE=requested, DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4,
                      REPLY_VOLUME_BOOST_DATE="")
    priority, creators, ordinary = dr._query_plan()
    assert len(creators) == expected
    assert len(set(priority + creators + ordinary)) == total


def test_artist_query_shared_with_general_latest_is_only_read_once(monkeypatch, settings_override):
    from dataclasses import replace
    from src.core import account
    from src.replies import direct_reply as dr

    loaded = _discovery_account(monkeypatch, groups=0, top=0, latest=0, creators=1)
    monkeypatch.setattr(account, "current", lambda: replace(loaded, searches=replace(
        loaded.searches, latest=loaded.searches.creators)))
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=16, DIRECT_REPLY_CREATOR_QUERIES_PER_CYCLE=2,
                      REPLY_VOLUME_BOOST_DATE="")
    priority, creators, ordinary = dr._query_plan()
    assert len(creators) == 1 and priority == ordinary == []


@pytest.mark.parametrize("draft_result", ["This SI model makes offline work easier.", "SKIP"])
def test_artists_get_four_attempts_before_a_full_major_author_buffer_without_extra_budget(
        monkeypatch, settings_override, llm, chokepoint, draft_result):
    from datetime import timedelta
    from src.replies import candidate_buffer, direct_reply as dr, reply_pipeline
    from tests.helpers import fresh

    loaded = _discovery_account(monkeypatch, groups=4, creators=6)
    settings_override(DIRECT_REPLY_QUERIES_PER_CYCLE=16, DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4,
                      DIRECT_REPLY_CREATOR_QUERIES_PER_CYCLE=2, DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4,
                      REPLY_PRIORITIZE_LARGE_ACCOUNTS=True, REPLY_CANDIDATE_BUFFER_LIMIT=8,
                      VIP_SCAN_HANDLES="", REPLY_VOLUME_BOOST_DATE="")
    majors = [reply_pipeline.Candidate(fresh(f"priority{i}", n=i), "SI model project", "SEARCH-PRIORITY")
              for i in range(8)]
    candidate_buffer.SEARCH.offer(majors, max_age=timedelta(hours=24))
    artists = [{"url": fresh(f"artist{i}", n=i + 100), "text": f"My first SI short film, project {i}", "likes": 0}
               for i in range(6)]
    reads, trace = [], []

    def scrape(query, **kwargs):
        reads.append(query)
        trace.append("read")
        return artists[:3] if query == loaded.searches.creators[0] else artists[3:] if query == loaded.searches.creators[1] else []

    def draft(prompt):
        trace.append("draft")
        return draft_result if any(f"@artist{i}" in prompt for i in range(6)) else "A local SI model makes offline work easier."

    monkeypatch.setattr(dr, "scrape_x_search", scrape)
    llm.default = draft
    dr.run_direct_reply_cycle(max_replies=6)
    assert trace[:6] == ["read"] * 6  # four major reads, two artist reads before drafting
    assert len(llm.calls) == 6  # four artist attempts, including SKIP, plus two ordinary
    assert all(any(f"@artist{i}" in prompt for i in range(6)) for prompt in llm.prompts[:4])
    assert all("@priority" in prompt for prompt in llm.prompts[4:])
    assert len(chokepoint.sent) == (6 if draft_result != "SKIP" else 2)
    assert len(candidate_buffer.SEARCH.entries) <= 8
    assert any("/artist" in item.url for item in candidate_buffer.SEARCH.pending())


def test_artist_sources_still_require_fresh_standalone_on_topic_posts(monkeypatch):
    from dataclasses import replace
    from src.core import account
    from src.replies import direct_reply as dr
    from tests.helpers import fresh

    loaded = replace(account.current(), engagement_niche_only=True)
    monkeypatch.setattr(account, "current", lambda: loaded)
    good = {"url": fresh("artist"), "text": "My first SI short film", "likes": 0}
    posts = [good, {**good, "url": fresh("nested", n=1), "is_reply": True},
             {**good, "url": fresh("old", minutes=61, n=2)},
             {**good, "url": fresh("future", minutes=-5, n=3)},
             {**good, "url": fresh("offtopic", n=4), "text": "SI crypto NFT trading"}]
    selected = dr._search_candidates(posts, "SI artist", "latest", creator=True)
    assert len(selected) == 1 and selected[0].url == good["url"]
    assert selected[0].source.startswith("SEARCH-CREATOR/") and selected[0].likes == 0


pytestmark = pytest.mark.usefixtures("relation_account")
