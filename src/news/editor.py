"""Evidence gates and complete, weighted-length-checked news tweets."""
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .adapters import timestamp

TZ = ZoneInfo("America/Toronto")


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string"}
BOOL = {"type": "boolean"}


def array(item, limit=20):
    return {"type": "array", "items": item, "maxItems": limit}


LEADS = obj({"leads": array(obj({"url": TEXT, "title": TEXT, "publication_hint": TEXT,
                                "evidence_urls": array(TEXT, 3)}), 24)})
TRIAGE = obj({"urls": array(TEXT, 12)})
FLAGS = ("verified", "exceptional", "original_evidence", "si_relevant", "numbers_checked", "availability_checked",
         "mechanism_correct", "attribution_complete", "uncertainty_preserved")
STORY = obj({**{k: BOOL for k in FLAGS}, "reason": TEXT, "event_key": TEXT, "development": TEXT,
    "title": TEXT, "summary": TEXT, "url": TEXT, "event_date": TEXT, "announcement_date": TEXT,
    "publication_date": TEXT, "development_date": TEXT,
    "date_evidence": obj({"url": TEXT, "quote": TEXT, "value": TEXT}),
    "material_update": BOOL, "update_evidence": TEXT, "duplicate_of": TEXT,
    "independent_required": BOOL, "independent_confirmed": BOOL, "corroboration_urls": array(TEXT, 3),
    "claims": array(obj({"claim": TEXT, "url": TEXT, "quote": TEXT}), 6),
    "qualifiers": array(TEXT, 4), "attribution": TEXT, "breaking": BOOL,
    "scores": obj({k: {"type": "integer", "minimum": 0, "maximum": 20}
                   for k in ("significance", "novelty", "hook", "relevance", "freshness")}),
    "paragraphs": array(TEXT, 3)})
REVIEW_FLAGS = ("facts_supported", "dates_supported", "mechanism_correct", "attribution_complete",
                "uncertainty_preserved", "exceptional", "duplicate_free", "material_update_proven",
                "english", "branding_only", "source_preserved", "natural", "qualifiers_preserved")
REVIEW = obj({**{k: BOOL for k in REVIEW_FLAGS}, "reason": TEXT})


def normalize(value):
    return " ".join(value.split()).casefold()


def date_value(value):
    precise = timestamp(value)
    if precise is not None:
        return precise
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value).replace(tzinfo=TZ).timestamp()
    except (ValueError, TypeError):
        pass
    return None


def supported_date(value, quote, doc):
    target = date_value(value)
    if target is None:
        return False
    candidates = [m["value"] for m in doc.get("dates", []) if m["value"] in quote]
    candidates += re.findall(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2}))?", quote)
    for found in re.findall(r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}", quote):
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
            try:
                candidates.append(datetime.strptime(found, fmt).date().isoformat())
                break
            except ValueError:
                pass
    for candidate in candidates:
        stamp = date_value(candidate)
        if stamp is not None and (stamp == target or (len(value) == 10 and datetime.fromtimestamp(stamp, TZ).date().isoformat() == value)):
            return True
    return False


def gate(story, documents, history, start, now, cfg):
    if not story["verified"]:
        return "held", story["reason"] or "insufficient verification"
    if not all(story[k] for k in FLAGS):
        return "rejected", story["reason"] or "editorial gate refused"
    by_url = {d["url"]: d for d in documents}
    if story["url"] not in by_url or by_url[story["url"]]["role"] == "lead":
        return "held", "tweet source was not read or is only a lead"
    if not story["event_key"].strip() or not story["development"].strip():
        return "held", "missing event identity"
    if not any(d["role"] in ("primary", "evidence") for d in documents):
        return "held", "original evidence was not fetched"
    if not story["claims"]:
        return "held", "missing evidence passages"
    for claim in story["claims"]:
        doc = by_url.get(claim["url"])
        if not doc or len(claim["quote"].split()) < 4 or normalize(claim["quote"]) not in normalize(doc["text"]):
            return "held", "claim passage absent from fetched source"
    date = story["date_evidence"]
    doc = by_url.get(date["url"])
    available = normalize(doc["text"] + " " + " ".join(d["value"] for d in doc.get("dates", []))) if doc else ""
    if not date["quote"].strip() or normalize(date["quote"]) not in available or date["value"] != story["development_date"]:
        return "held", "development date lacks fetched evidence"
    if not supported_date(story["development_date"], date["quote"], doc):
        return "held", "normalized development date is unsupported"
    developed = date_value(story["development_date"])
    if developed is None or developed > now:
        return "held", "development time unknown or future"
    if developed < start:
        return "stale", "event predates the search window; republication is not a new event"
    # An old event with a fresh page timestamp is not breaking news.
    event = date_value(story["event_date"])
    if event is not None and event < start and not story["material_update"]:
        return "stale", "old event without a material new development"
    if story["independent_required"]:
        sources = [by_url.get(url) for url in story["corroboration_urls"]]
        owners = {d["owner"] for d in sources if d and d["role"] != "lead"}
        if not story["independent_confirmed"] or len(owners) < 2:
            return "held", "consequential/disputed claim needs independent corroboration"
    prior = [h for h in history if h.get("event_key") == story["event_key"] or h.get("url") == story["url"]
             or h.get("id") == story["duplicate_of"]]
    if any(h.get("development") == story["development"] and h.get("state") not in ("held", "verified") for h in prior):
        return "duplicate", "underlying development already recorded"
    if any(h.get("state") not in ("held", "verified") for h in prior) or story["material_update"]:
        update = normalize(story["update_evidence"])
        if not story["material_update"] or len(update.split()) < 4 or not any(update in normalize(d["text"]) for d in documents):
            return "duplicate", "no evidenced material new development"
    if sum(story["scores"].values()) < cfg.score_min:
        return "rejected", "below exceptional-story threshold"
    return "verified", ""


def tweet(story):
    # Preserve intentional paragraphs and literal names/quotes/URLs. No truncation.
    from twitter_text import parse_tweet, extract_urls_with_indices
    paragraphs = [p.strip() for p in story["paragraphs"] if p.strip()]
    text = "\n\n".join([*paragraphs, story["url"]])
    result = parse_tweet(text)
    urls = extract_urls_with_indices(text)
    if not result.valid or result.weightedLength > 280:
        raise ValueError("complete tweet exceeds X weighted character limit")
    if len(urls) != 1 or urls[0]["url"] != story["url"] or not text.endswith(story["url"]):
        raise ValueError("tweet needs exactly one direct source URL at the end")
    if not paragraphs or "BANGER" not in text or "\u2014" in text or re.search(r"(?<!\w)#\w", text):
        raise ValueError("tweet format/branding refused")
    if any(normalize(q) not in normalize(text) for q in story["qualifiers"] if q):
        raise ValueError("required qualifier missing from tweet")
    if story["attribution"] and normalize(story["attribution"]) not in normalize(text):
        raise ValueError("required attribution missing from tweet")
    return text, result.weightedLength


def recommendation(story, now, occupied, gap_minutes):
    local = datetime.fromtimestamp(now, TZ)
    precise = timestamp(story["development_date"])
    breaking = story["breaking"] and precise is not None and 0 <= now - precise <= 3 * 3600
    collision = lambda t: any(abs(t.timestamp() - stamp) < gap_minutes * 60 for stamp in occupied)
    if breaking:
        target = local
        note = "Immediately" + ("; nearby queued/video post" if collision(target) else "")
    else:
        options = []
        for day in range(3):
            base = local + timedelta(days=day)
            for hour, minute in ((9, 0), (12, 15), (16, 0)):
                for shift in range(0, 91, 15):
                    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(minutes=shift)
                    if candidate >= local and not collision(candidate):
                        options.append(candidate)
        target = min(options) if options else local + timedelta(days=1)
        note = "Recommended" if options else "Tentative; queue crowded"
    dates = f"Event {story['event_date'] or 'unknown'}; announced {story['announcement_date'] or 'unknown'}; source {story['publication_date'] or 'unknown'}"
    return f"{dates} | {note}: {target:%Y-%m-%d %H:%M %Z} (America/Toronto, {target:%z})."
