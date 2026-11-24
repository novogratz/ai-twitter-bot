"""Visible Instagram grids in the signed-in Safari session supply leads only.

2026-11-23: Codex web search cannot see Instagram (two leads in three weeks),
while the normal pages list every reel. A creator's Reels tab shows each reel
with its displayed play counter; Instagram's keyword search lists reels for a
query. One bounded read per turn collects visible links. A lead is never a
permission, a publication date or an inspection: the exact reel page, the
download, the model review and novelty still decide.
"""
import json
import re
import time
from urllib.parse import quote

from .security import AccessError

USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}")
LINK = re.compile(r"/(?:([A-Za-z0-9._]{1,30})/)?(?:reel|p)/([A-Za-z0-9_-]{5,40})/?")
SYNTHETIC = re.compile(r"(?<![a-z0-9])(?:ai|aigc|ia)(?![a-z0-9])|#ai\w+|deepfake|synthetic|face ?swap|parody|parodie"
                       r"|sora|kling|seedance|grok imagine|生成|换脸|換臉|合成|鬼畜", re.I)
CREATOR_GRID, KEYWORD_SEARCH = "visible Instagram creator Reels grid", "visible Instagram keyword search"

GRID = r"""JSON.stringify((()=>{
  if(!['www.instagram.com','instagram.com'].includes(location.hostname))return {};
  const visible=e=>!!(e&&e.getClientRects().length);
  const login=location.pathname.startsWith('/accounts/')||!!document.querySelector('input[name="username"]');
  const items=[...document.querySelectorAll('a[href*="/reel/"],a[href*="/p/"]')].filter(visible).slice(0,120)
    .map(a=>({href:a.getAttribute('href')||'',text:(a.innerText||'').replace(/\s+/g,' ').trim().slice(0,40),
      reel:[...a.querySelectorAll('svg[aria-label]')].some(s=>/reel|clip|video|vidéo/i.test(s.getAttribute('aria-label')))}));
  return {path:location.pathname,login,items};})())"""


class LeadRefused(AccessError):
    """A completed lead decision: the exact reel page was read and is not a fit."""


def count(text):
    """A displayed counter's lower bound: '87K' is at least 87,000 plays."""
    match = re.fullmatch(r"\s*([0-9]+(?:[,.   ][0-9]{3})*|[0-9]+(?:[.,][0-9]+)?)\s*([KMB])?\s*", text or "", re.I)
    if not match:
        return None
    number, suffix = match.groups()
    if not suffix:
        digits = re.sub(r"[,.   ]", "", number)
        return int(digits) if digits.isdigit() else None
    try:
        return int(float(number.replace(",", ".")) * {"K": 1000, "M": 1_000_000, "B": 1_000_000_000}[suffix.upper()])
    except ValueError:
        return None


def learned_creators(store, cfg, limit=40):
    """Creators worth revisiting: an inspected target parody, or a reel the audience made big.

    2026-11-24: search surfaced 258K- and 78K-like reels whose creators were never
    read again. Five times the like floor on an exact reel page earns its creator a
    place in the grid rotation; the grid then ranks that creator's reels by plays."""
    result = []
    big = max(1, cfg.audience_min_likes) * 5
    for row in store.rows("SELECT creator,document FROM candidates WHERE platform='instagram' "
                          "AND state NOT IN ('rejected','duplicate') AND reason NOT LIKE 'lead refused%' "
                          "AND (json_extract(document,'$.inspection.synthetic_parody') "
                          "OR json_extract(document,'$.source_stats.likes')>=?) ORDER BY updated DESC LIMIT 300", (big,)):
        doc = json.loads(row["document"])
        review = doc.get("inspection", {})
        proven = review.get("synthetic_parody") and set(review.get("cast", [])) & set(cfg.targets)
        popular = cfg.audience_min_likes > 0 and (doc.get("source_stats", {}).get("likes") or 0) >= big
        if USERNAME.fullmatch(row["creator"] or "") and (proven or popular) and row["creator"] not in result:
            result.append(row["creator"])
    return result[:limit]


def pages(store, cfg):
    """Creator grids and keyword searches, as two independent rotations."""
    options = cfg.platforms.get("instagram", {})
    creators = list(dict.fromkeys(name for name in [*options.get("creators", []), *learned_creators(store, cfg)]
                                  if isinstance(name, str) and USERNAME.fullmatch(name)))
    queries = [q.strip() for q in options.get("browse_queries", []) if isinstance(q, str) and 0 < len(q.strip()) <= 80]
    return ([("creator", name, f"https://www.instagram.com/{name}/reels/") for name in creators],
            [("search", q, "https://www.instagram.com/explore/search/keyword/?q=" + quote(q, safe="")) for q in queries])


def choose(store, cfg, cursor):
    """Alternate the two rotations: a short creator list is revisited often,
    a long query bank never pushes the proven creators hours away."""
    grids, searches = pages(store, cfg)
    order = (grids, searches) if cursor % 2 == 0 else (searches, grids)
    for group in order:
        if group:
            return group[(cursor // 2) % len(group)]
    return None


def leads(items, kind, value, known, options, now):
    """Bounded, validated links; counters rank creator reels, never approve them."""
    found = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        match = LINK.fullmatch(str(item.get("href", "")))
        if not match:
            continue
        owner, code = match.groups()
        if code in known or code in found:
            continue
        views = count(str(item.get("text", ""))) if kind == "creator" else None
        if kind == "creator" and ((owner or value).casefold() != value.casefold() or views is None
                                  or views < options.get("browse_min_views", 20000)):
            continue
        if kind == "search" and item.get("reel") is not True:
            continue
        url = "https://www.instagram.com/reel/" + code
        evidence = {"url": url, "observed_at": now, "method": CREATOR_GRID if kind == "creator" else KEYWORD_SEARCH,
                    "page": value[:80], "views": views}
        found[code] = {"source_id": code, "canonical_url": url, "creator": value if kind == "creator" else "",
                       "title": "", "published_at": None, "access_status": "visible Instagram grid link",
                       "discovery_evidence": evidence,
                       **({"metrics": {"views": views}, "metrics_observed_at": now} if views is not None else {})}
    ranked = sorted(found.values(), key=lambda lead: -(lead["discovery_evidence"]["views"] or 0))
    return ranked[:max(1, min(24, options.get("browse_leads_per_read", 6)))]


def lead_refusal(doc, cfg):
    """Cheap decisions on the exact reel page, before any download or model call."""
    # "Banger" starts with an audience: the displayed plays on the creator grid
    # or the reel's own like count. Both unknown is not evidence of a flop.
    plays = doc.get("discovery_evidence", {}).get("views")
    likes = doc.get("source_stats", {}).get("likes")
    known = [(value, floor) for value, floor in ((plays, cfg.audience_min_views), (likes, cfg.audience_min_likes))
             if type(value) is int and floor > 0]
    if known and all(value < floor for value, floor in known):
        return "audience below the configured plays and likes floors"
    if doc.get("discovery_evidence", {}).get("method") != KEYWORD_SEARCH:
        return ""
    caption = str(doc.get("title", ""))
    named = any(alias.casefold() in caption.casefold() for aliases in cfg.targets.values() for alias in aliases)
    return "" if named or SYNTHETIC.search(caption) else "search result caption names no target or synthetic parody"


def browse_next(store, cfg, now):
    """One short Safari read of the next creator grid or search page."""
    options = cfg.platforms.get("instagram", {})
    if (not options.get("enabled", True) or not options.get("safari_browse")
            or store.meta("platform_disabled:instagram", False) or store.meta("next_instagram_browse", 0) > now):
        return None
    cursor = store.meta("instagram_browse_cursor", 0)
    choice = choose(store, cfg, cursor)
    if not choice:
        return None
    interval = max(300, options.get("browse_seconds", 900))
    kind, value, url = choice
    store.set_meta("next_instagram_browse", now + interval)
    if not store.budget("instagram", "requests", 1, cfg.request_budget - cfg.publishing_request_reserve, now):
        return None
    from ..x import safari
    from ..x.safari_video import browser_session
    target = url.split("?", 1)[0]
    seen, payload = {}, {}
    with browser_session():
        if not safari.open_url(url):
            raise AccessError("Instagram page did not open")
        try:
            def read():
                raw = safari._run_js(GRID, timeout_s=5, target_url=target)
                data = json.loads(raw) if raw and len(raw) <= 200000 else {}
                seen.update((item.get("href"), item) for item in data.get("items", []) if isinstance(item, dict))
                return data
            for _ in range(16):
                payload = read()
                if payload.get("login") or seen:
                    break
                time.sleep(.5)
            for _ in range(max(0, min(6, options.get("browse_scrolls", 2))) if seen else 0):
                safari._run_js("window.scrollBy(0, window.innerHeight * 2); 'scrolled'", timeout_s=5, target_url=target)
                time.sleep(1.5)
                read()
        finally:
            safari.close_front_tab()
    store.set_meta("instagram_browse_cursor", cursor + 1)
    status = {"checked_at": now, "kind": kind, "page": value[:80], "visible": len(seen)}
    if payload.get("login") or not seen:
        # A sign-in wall or an empty shell is not an empty catalog. Wait
        # longer; the operator signs in again, nothing is bypassed.
        reason = "Instagram session is signed out" if payload.get("login") else "no visible reels on this page"
        store.set_meta("next_instagram_browse", now + (21600 if payload.get("login") else max(interval, 3600)))
        store.set_meta("instagram_browse", status | {"status": "limited", "reason": reason})
        store.event(now, "instagram_browse_limited", value[:80], reason)
        return "instagram page unavailable"
    known = {row["source_id"] for row in store.rows("SELECT source_id FROM candidates WHERE platform='instagram'")}
    from .connectors import ingest
    accepted = ingest(store, "instagram", leads(list(seen.values()), kind, value, known, options, now), now, cfg)
    store.set_meta("instagram_browse", status | {"status": "operational", "accepted": accepted})
    store.event(now, "instagram_leads", value[:80], f"{accepted} new of {len(seen)} visible ({kind})")
    return "instagram leads read"
