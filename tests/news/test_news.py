"""Real persistence and editorial gates; models, network and Safari are fixtures."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from src.news import editor, history, pipeline, publisher
from src.news.adapters import Delivery, HTTP, PendingDelivery, canonical
from src.news.config import NewsConfig
from src.news.store import Store, identity
from src.video.security import Deferred

NOW = datetime(2026, 11, 7, 17, 0, tzinfo=timezone.utc).timestamp()
URL = "https://lab.example.com/research/new-model"
WHEN = "2026-11-07T16:00:00+00:00"
QUOTE = "The model solved 80% of tasks in our controlled test."


@pytest.fixture
def cfg():
    return NewsConfig(search_adapter="none", sources=[], candidates_per_run=3,
                      evidence_hosts=["lab.example.com", "report.example.com"], video_gap_minutes=30)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "news.sqlite3")


@pytest.fixture
def doc():
    return {"url": URL, "text": QUOTE + " " + WHEN, "dates": [{"kind": "published", "value": WHEN}],
            "role": "primary", "owner": "lab", "links": []}


@pytest.fixture
def story():
    return {**{k: True for k in editor.FLAGS}, "reason": "An exceptional demonstrated result.",
        "event_key": "lab-model-r1-release", "development": "initial-release", "title": "A new model result",
        "summary": "Lab reports improved task solving in a controlled test.", "url": URL,
        "event_date": WHEN, "announcement_date": WHEN, "publication_date": WHEN, "development_date": WHEN,
        "date_evidence": {"url": URL, "quote": WHEN, "value": WHEN}, "material_update": False,
        "update_evidence": "", "duplicate_of": "", "independent_required": False,
        "independent_confirmed": False, "corroboration_urls": [],
        "claims": [{"claim": "80% in the lab's controlled test", "url": URL, "quote": QUOTE}],
        "qualifiers": ["controlled test"], "attribution": "The lab says", "breaking": True,
        "scores": {k: 19 for k in ("significance", "novelty", "hook", "relevance", "freshness")},
        "paragraphs": ["The lab says its model solved 80% of tasks in a controlled test.", "SI BANGER."]}


class Model:
    def __init__(self, story):
        self.story, self.calls = story, []

    def call(self, task, data, schema, **kwargs):
        self.calls.append((task, data))
        if task == "TRIAGE":
            return {"urls": [r["url"] for r in data["leads"]]}
        if task == "VERIFY_AND_WRITE":
            return deepcopy(self.story)
        if task == "FINAL_REVIEW":
            return {**{k: True for k in editor.REVIEW_FLAGS}, "reason": "Supported and attributed."}
        return {"leads": []}


class Sources:
    def __init__(self, doc):
        self.doc = doc

    def document(self, url):
        return deepcopy(self.doc)

    def discover(self, source):
        return []


def seed(store, url=URL):
    store.lead({"url": url, "title": "New model task solving", "evidence_urls": [], "publication_hint": WHEN}, NOW)


def test_verified_story_and_format(story, doc, cfg):
    assert editor.gate(story, [doc], [], NOW - 86400, NOW, cfg)[0] == "verified"
    text, length = editor.tweet(story)
    assert "\n\nSI BANGER.\n\nhttps://" in text
    assert text.endswith(URL) and length < 280


@pytest.mark.parametrize("change", ["old_event", "old_development", "invented_date", "no_quote", "no_corroboration"])
def test_stale_and_unsupported_stories_hold(story, doc, cfg, change):
    if change == "old_event":
        story["event_date"] = "2025-01-01"
    elif change == "old_development":
        story["development_date"] = story["date_evidence"]["value"] = "2025-01-01"
    elif change == "invented_date":
        story["date_evidence"]["quote"] = QUOTE
    elif change == "no_quote":
        story["claims"][0]["quote"] = "This claim never appeared in the source."
    else:
        story["independent_required"] = True
    assert editor.gate(story, [doc], [], NOW - 86400, NOW, cfg)[0] in ("stale", "held")


def test_same_owner_is_not_independent(story, doc, cfg):
    other = {**doc, "url": "https://report.example.com/article"}
    story.update(independent_required=True, independent_confirmed=True, corroboration_urls=[URL, other["url"]])
    assert editor.gate(story, [doc, other], [], NOW - 86400, NOW, cfg)[0] == "held"
    other["owner"] = "independent_reporter"
    assert editor.gate(story, [doc, other], [], NOW - 86400, NOW, cfg)[0] == "verified"


def test_event_dedup_across_outlets_and_rejections(story, doc, cfg):
    prior = {**story, "url": "https://report.example.com/another-headline", "state": "rejected"}
    assert editor.gate(story, [doc], [prior], NOW - 86400, NOW, cfg)[0] == "duplicate"
    story.update(development="independent-replication", material_update=True, update_evidence=QUOTE)
    assert editor.gate(story, [doc], [prior], NOW - 86400, NOW, cfg)[0] == "verified"


def test_unpublished_hold_can_clear_when_evidence_is_complete(story, doc, cfg):
    prior = {**deepcopy(story), "id":"held-candidate", "state":"held", "verified":False}
    story["duplicate_of"] = prior["id"]
    assert story["material_update"] is False
    assert editor.gate(story, [doc], [prior], NOW-86400, NOW, cfg)[0] == "verified"
    for state in ("rejected", "queued", "delivered", "published"):
        prior["state"] = state
        assert editor.gate(story, [doc], [prior], NOW-86400, NOW, cfg)[0] == "duplicate"


def test_missing_attribution_and_qualifiers_are_not_trimmed(story):
    story["paragraphs"] = ["The model solved 80% of tasks. SI BANGER."]
    with pytest.raises(ValueError, match="qualifier"):
        editor.tweet(story)
    story["paragraphs"] = ["It solved 80% of tasks in a controlled test. SI BANGER."]
    with pytest.raises(ValueError, match="attribution"):
        editor.tweet(story)


def test_x_weighting_and_long_source_url(story):
    from twitter_text import parse_tweet
    assert parse_tweet("👩🏽‍💻").weightedLength == 2
    assert parse_tweet("中文").weightedLength == 4
    assert parse_tweet("e\u0301").weightedLength == 1
    assert parse_tweet("\n\n").weightedLength == 2
    assert parse_tweet("https://lab.example.com/" + "a" * 300).weightedLength == 23
    story["paragraphs"] = ["The lab says " + "a" * 260 + " controlled test SI BANGER."]
    with pytest.raises(ValueError, match="weighted"):
        editor.tweet(story)


def test_canonical_tracking_query_and_fragment():
    assert canonical(URL + "?utm_source=x&model=v2#top") == URL + "?model=v2"
    with pytest.raises(ValueError):
        canonical("https://secret@lab.example.com/path")


def test_empty_run_is_silent_and_creates_no_delivery(store, cfg, tmp_path, capsys):
    results = pipeline.run(cfg, store=store, http=Sources({}), model=Model({}),
        delivery=Delivery(cfg, tmp_path / "inbox"), now=NOW, import_history=False)
    assert results == [] and store.rows("SELECT * FROM outbox") == []
    assert not (tmp_path / "inbox").exists()
    assert capsys.readouterr().out == ""


def test_end_to_end_persisted_dedup_and_ack(store, cfg, story, doc, tmp_path):
    seed(store)
    model = Model(story)
    delivery = Delivery(cfg, tmp_path / "inbox")
    first = pipeline.run(cfg, store=store, http=Sources(doc), model=model, delivery=delivery, now=NOW, import_history=False)
    assert len(first) == 1 and first[0]["role"] == "main"
    reopened = Store(store.path)
    second = pipeline.run(cfg, store=reopened, http=Sources(doc), model=model, delivery=delivery, now=NOW+3600, import_history=False)
    assert second == [] and len(list((tmp_path / "inbox").iterdir())) == 1
    reopened.acknowledge(first[0]["id"], NOW+4000)
    assert reopened.rows("SELECT state FROM stories")[0]["state"] == "acknowledged"


def test_delivery_retry_after_destination_accepts_uses_identical_id(store, cfg, story, doc, tmp_path):
    seed(store)
    real = Delivery(cfg, tmp_path / "inbox")
    class Interrupted:
        def send(self, ident, payload):
            real.send(ident, payload)
            raise TimeoutError("ack lost")
    assert pipeline.run(cfg, store=store, http=Sources(doc), model=Model(story), delivery=Interrupted(), now=NOW, import_history=False) == []
    original = store.rows("SELECT * FROM outbox")[0]
    assert original["state"] == "pending"
    result = pipeline.run(cfg, store=store, http=Sources(doc), model=Model(story), delivery=real, now=NOW+3600, import_history=False)
    assert result[0]["id"] == original["id"]
    assert len(list((tmp_path / "inbox").iterdir())) == 1


def test_source_outage_preserves_watermark_and_backfills(store, cfg, caplog):
    cfg = replace(cfg, sources=[{"name":"Lab", "url": "https://lab.example.com/feed", "kind":"rss", "role":"primary", "owner":"lab", "path_prefix":"/"}])
    store.set_meta("last_complete", NOW - 3 * 86400)
    class Down(Sources):
        def discover(self, source):
            raise TimeoutError
    pipeline.run(cfg, store=store, http=Down({}), model=Model({}), delivery=object(), now=NOW, import_history=False)
    assert store.rows("SELECT window_start,status FROM runs")[0] == {"window_start": NOW - 3*86400, "status":"partial"}
    assert store.meta("last_complete") == NOW - 3*86400
    assert "Partial coverage" in caplog.text


def test_legacy_startup_uses_confirmed_source_posts_only(store, monkeypatch):
    from types import SimpleNamespace
    old = datetime(2026, 10, 31, 19, 13, tzinfo=timezone.utc)
    data = {"published": [
        {"ts": old.isoformat(), "text": "Recorded news", "source_url": URL},
        {"ts": WHEN, "text": "Unsourced text", "source_url": ""},
        {"ts": WHEN, "text": "Invalid source", "source_url": "not-a-url"},
        {"ts": "2026-11-08T12:00:00Z", "text": "Future", "source_url": URL},
        {"ts": "invalid", "text": "Unknown time", "source_url": URL}],
        "pending_sources": {"today": {"ts": WHEN, "text": "Unconfirmed", "url": URL}}}
    before = deepcopy(data)
    monkeypatch.setattr(history, "STATE", SimpleNamespace(path="legacy.json", read=lambda: data))
    assert history.startup_window(store, NOW-86400, NOW) == old.timestamp()
    assert store.meta("legacy_startup_anchor") == {"at": old.timestamp(), "origin": "legacy.json"}
    assert data == before


def test_complete_news_scan_supersedes_legacy_anchor(store, monkeypatch):
    from types import SimpleNamespace
    store.set_meta("last_complete", NOW-3600)
    def unexpected_read():
        raise AssertionError("completed news must not restart old catch-up")
    monkeypatch.setattr(history, "STATE", SimpleNamespace(read=unexpected_read))
    assert history.startup_window(store, NOW-86400, NOW) == NOW-86400


def test_partial_initial_run_recovers_legacy_gap_until_complete(store, cfg, monkeypatch):
    from types import SimpleNamespace
    old = datetime(2026, 10, 31, 19, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(history, "STATE", SimpleNamespace(path="legacy.json", read=lambda:
        {"published": [{"ts": old.isoformat(), "text": "Recorded news", "source_url": URL}]}))
    monkeypatch.setattr(history, "context", lambda *a: [])
    # An installation that already had a partial 24-hour first run still catches up.
    store.set_meta("first_window", NOW-86400)
    class Down(Sources):
        def discover(self, source):
            raise TimeoutError
    outage = replace(cfg, sources=[{"name":"Lab", "url":"https://lab.example.com/feed", "kind":"rss",
                                    "role":"primary", "owner":"lab", "path_prefix":"/"}])
    pipeline.run(outage, store=store, http=Down({}), model=Model({}), delivery=object(), now=NOW)
    assert store.meta("last_complete") is None
    assert store.meta("first_window") == old.timestamp()
    pipeline.run(cfg, store=store, http=Sources({}), model=Model({}), delivery=object(), now=NOW+3600)
    assert store.meta("last_complete") == NOW+3600
    pipeline.run(cfg, store=store, http=Sources({}), model=Model({}), delivery=object(), now=NOW+7200)
    runs = store.rows("SELECT window_start,status FROM runs ORDER BY started")
    assert runs == [{"window_start":old.timestamp(), "status":"partial"},
                    {"window_start":old.timestamp(), "status":"complete"},
                    {"window_start":NOW+7200-86400, "status":"complete"}]


def test_preparation_keeps_reviewed_delivery_pending_without_ack(store, cfg, story, doc, tmp_path):
    seed(store)
    assert pipeline.run(cfg, store=store, http=Sources(doc), model=Model(story),
        delivery=PendingDelivery(), now=NOW, import_history=False) == []
    row = store.rows("SELECT * FROM outbox")[0]
    assert row["state"] == "pending" and row["attempts"] == 0
    assert row["receipt"] is None and row["acknowledged"] is None
    delivered = pipeline.deliver(Store(store.path), cfg, Delivery(cfg, tmp_path/'inbox'), NOW+3600)
    assert len(delivered) == 1 and delivered[0]["id"] == row["id"]
    assert store.rows("SELECT state FROM outbox")[0]["state"] == "delivered"


def test_history_import_missing_corrupt_and_queued(store, tmp_path):
    path = tmp_path / "history.json"
    history.import_file(store, path, NOW)
    assert store.rows("SELECT status FROM coverage")[0]["status"] == "missing"
    path.write_text(json.dumps([{"text":"Lab model r1 announced", "source_url":URL, "scheduled_at":WHEN}]))
    history.import_file(store, path, NOW, queue=True)
    assert store.related("Lab model r1")[0]["state"] == "queued"
    path.write_text("broken")
    with pytest.raises(ValueError):
        history.import_file(store, path, NOW)
    assert store.rows("SELECT COUNT(*) AS n FROM stories")[0]["n"] == 1


def test_nonbreaking_recommendation_avoids_video_and_uses_dst(story):
    story["breaking"] = False
    before = datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc).timestamp()
    video = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc).timestamp()
    line = editor.recommendation(story, before, [video], 30)
    assert "09:30 EST" in line and "-0500" in line
    summer = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).timestamp()
    assert "EDT" in editor.recommendation(story, summer, [], 30)


def test_news_job_coexists_with_videos_without_restoring_editorial(settings_override):
    from main import build_scheduler
    settings_override(NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True, VIDEO_ENABLED=True)
    scheduler = build_scheduler()
    assert scheduler.get_job("news_job").trigger.interval.total_seconds() == 3600
    assert scheduler.get_job("video_health_job")
    assert not scheduler.get_job("editorial_job")
    assert not build_scheduler(reply_only=True).get_job("news_job")


def pending(store, cfg, story, doc):
    story.update(evidence=[doc], verified_at=NOW, window_start=NOW-86400,
                 final_review={k: True for k in editor.REVIEW_FLAGS})
    text = editor.tweet(story)[0]
    story["reviewed_text_hash"] = identity(text)
    story["evidence_hash"] = identity([{k: doc.get(k) for k in ("url","text","dates")}])
    ident = store.remember(story, "verified", NOW)
    store.enqueue(ident, "run", {"id":ident,"role":"main","tweet":text}, NOW)
    return ident


def test_publisher_requires_switches_and_unchanged_evidence(store, cfg, story, doc, monkeypatch, settings_override):
    ident = pending(store, cfg, story, doc)
    with pytest.raises(Deferred):
        publisher.admit(store, cfg, ident, NOW)
    settings_override(NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True, VIDEO_ENABLED=False)
    monkeypatch.setattr(publisher.action_guard, "can_post", lambda *a, **k:(True,""))
    assert publisher.admit(store, cfg, ident, NOW)["id"] == ident
    bad = {**story, "paragraphs":["Changed content. SI BANGER."]}
    store.execute("UPDATE stories SET document=? WHERE id=?", (json.dumps(bad),ident))
    with pytest.raises(ValueError):
        publisher.admit(store, cfg, ident, NOW)


def test_uncertain_send_never_retries_or_reports_delivery(store, cfg, story, doc):
    ident = pending(store,cfg,story,doc)
    class Uncertain:
        calls = 0
        def send(self, key, payload):
            self.calls += 1
            store.execute("UPDATE outbox SET state='publish_unknown' WHERE id=?", (key,))
            raise TimeoutError
    adapter = Uncertain()
    assert pipeline.deliver(store,cfg,adapter,NOW) == []
    assert pipeline.deliver(store,cfg,adapter,NOW+3600) == []
    assert adapter.calls == 1
    assert store.rows("SELECT state FROM outbox")[0]["state"] == "publish_unknown"


def test_reciprocal_video_hold_reads_without_creating_db(store, monkeypatch):
    monkeypatch.setattr(publisher,"DATABASE",str(store.path))
    store.execute("INSERT INTO outbox(id,story,run,payload,state) VALUES ('one','one','run','{}','publish_unknown')")
    assert publisher.video_hold(NOW) == "news send unresolved"
    store.execute("UPDATE outbox SET state='published',acknowledged=?",(NOW-60,))
    assert publisher.video_hold(NOW) == "spacing after confirmed news"
    assert publisher.video_hold(NOW+3600) == ""


def test_short_primary_index_links_survive_as_unverified_url_leads(store, cfg, monkeypatch):
    http = HTTP(store, cfg, NOW)
    monkeypatch.setattr(http, "get", lambda url: {"format":"markup", "body":
        '<a href="/research/release"><img src="image.png"></a><a href="/research/release">Learn more</a>'})
    source = {"url":"https://lab.example.com/research/", "kind":"html", "path_prefix":"/research/"}
    leads = http.discover(source)
    assert len(leads) == 1
    assert leads[0]["title"] == "URL lead: /research/release"


def test_supporting_links_use_artifacts_and_corroboration_before_navigation(cfg, doc):
    paper = "https://lab.example.com/research/model-paper.pdf"
    fixes = "https://report.example.org/security/advisories/release-1"
    cfg = replace(cfg, evidence_hosts=[*cfg.evidence_hosts, "report.example.org"])
    doc["owner"] = cfg.source_info(URL)["owner"]
    doc["links"] = [
        {"url":"https://lab.example.com/", "title":"Lab"},
        {"url":"https://lab.example.com/blog", "title":"Blog"},
        {"url":URL+"/", "title":"This announcement"},
        {"url":"https://lab.example.com/research/team", "title":"Meet our team"},
        {"url":paper, "title":"Read the paper"},
        {"url":fixes, "title":"Released fixes"},
        {"url":"https://x.com/lab/status/123", "title":"Independent report"}]
    assert pipeline._supporting_links(doc, cfg) == [fixes, paper]


def test_rate_limit_cooldown_persists_without_repeated_requests(store, cfg, monkeypatch):
    from src.video import security
    calls = []
    def limited(*args, **kwargs):
        calls.append(True)
        raise security.AccessError("limited",status=429,retry_after=7200)
    monkeypatch.setattr(security,"request",limited)
    with pytest.raises(RuntimeError,match="failed"):
        HTTP(store,cfg,NOW).get(URL)
    with pytest.raises(RuntimeError,match="cooldown"):
        HTTP(Store(store.path),cfg,NOW+3600).get(URL)
    assert len(calls) == 1


@pytest.mark.parametrize("received", [True,False])
def test_safari_write_requires_exact_receipt_before_ledger(store,cfg,story,doc,monkeypatch,received):
    from src.x import twitter_client,news_page,safari_video,safari
    from src.x.confirmed_write import WriteOutcome
    from src.guards import content_guard,respect_list,action_guard
    ident=pending(store,cfg,story,doc)
    payload=json.loads(store.rows("SELECT payload FROM outbox")[0]["payload"])
    monkeypatch.setattr(publisher,"admit",lambda *a:payload)
    monkeypatch.setattr(content_guard,"validate",lambda *a,**k:(True,""))
    monkeypatch.setattr(content_guard,"is_duplicate",lambda *a:False)
    monkeypatch.setattr(content_guard,"note_posted",lambda *a:None)
    monkeypatch.setattr(respect_list,"scrub_text_or_skip",lambda text:(text,""))
    monkeypatch.setattr(safari_video,"require_browser_owner",lambda:None)
    monkeypatch.setattr(news_page,"prepare",lambda text:True)
    def click(text,**kwargs):
        assert store.rows("SELECT state FROM outbox")[0]["state"] == "submitting"
        return True
    monkeypatch.setattr(news_page,"composer",click)
    receipt="https://x.com/ExampleAuthor/status/12345"
    monkeypatch.setattr(news_page,"receipt",lambda *a:receipt if received else "")
    monkeypatch.setattr(safari,"close_front_tab",lambda:None)
    monkeypatch.setattr(twitter_client,"_record_posted",lambda *a:None)
    rows=[]
    monkeypatch.setattr(action_guard,"record",lambda *a,**k:rows.append((a,k)))
    result=twitter_client.post_news(store,cfg,ident)
    assert result is (WriteOutcome.SHIPPED if received else WriteOutcome.UNCONFIRMED)
    assert bool(rows) is received
    assert store.rows("SELECT state FROM outbox")[0]["state"] == ("published" if received else "publish_unknown")


def test_news_exception_does_not_unlock_ordinary_originals(monkeypatch,settings_override):
    from src.guards import action_guard,active_hours
    from src.guards.ledger import MemoryLedger
    from src.video import config as vc
    settings_override(NEWS_ENABLED=True,NEWS_AUTO_PUBLISH=True,VIDEO_ENABLED=True)
    monkeypatch.setattr(action_guard,"LEDGER",MemoryLedger())
    monkeypatch.setattr(action_guard,"is_active",lambda:True)
    monkeypatch.setattr(action_guard,"break_until",lambda:None)
    monkeypatch.setattr(action_guard,"stop_requested",lambda:False)
    monkeypatch.setattr(vc,"legacy_usage",lambda now:(10,NOW-60))
    assert action_guard.can_post(action_guard.POST)[0] is False
    assert action_guard.can_post(action_guard.POST,news=True)[0] is True
    assert action_guard.can_post(action_guard.RETWEET,news=True)[0] is False


def test_final_review_can_refuse_misleading_mechanism(store,cfg,story,doc,tmp_path):
    seed(store)
    class Skeptic(Model):
        def call(self,task,*args,**kwargs):
            result=super().call(task,*args,**kwargs)
            if task == "FINAL_REVIEW":
                result["mechanism_correct"]=False
                result["reason"]="Software executed a preset, not a model changing its mind."
            return result
    assert pipeline.run(cfg,store=store,http=Sources(doc),model=Skeptic(story),
        delivery=Delivery(cfg,tmp_path/'inbox'),now=NOW,import_history=False) == []
    assert store.rows("SELECT * FROM outbox") == []
    assert store.rows("SELECT state FROM stories")[0]["state"] == "held"


@pytest.mark.parametrize("backup_score,expected", [(17,1),(19,2)])
def test_main_and_optional_backup_are_distinct_and_bounded(store,cfg,story,doc,tmp_path,backup_score,expected):
    variants={}
    documents={}
    for index in range(3):
        url=URL+str(index)
        seed(store,url)
        item=deepcopy(story)
        item.update(url=url,event_key=f"different-release-{index}",title=f"Release {index}")
        item["claims"][0]["url"]=url
        item["date_evidence"]["url"]=url
        item["scores"]={k:20 if index == 0 else backup_score for k in item["scores"]}
        variants[url]=item
        documents[url]={**doc,"url":url}
    class DifferentModel(Model):
        def call(self,task,data,*args,**kwargs):
            if task == "VERIFY_AND_WRITE":
                return deepcopy(variants[data["lead"]["url"]])
            return super().call(task,data,*args,**kwargs)
    class DifferentSources(Sources):
        def document(self,url):
            return documents[url]
    results=pipeline.run(cfg,store=store,http=DifferentSources(doc),model=DifferentModel(story),
        delivery=Delivery(cfg,tmp_path/'inbox'),now=NOW,import_history=False)
    assert len(results)==expected
    assert [r["role"] for r in results] == ["main","backup"][:expected]
    assert len({r["id"] for r in results}) == expected


def test_breaking_recommendation_is_current_run(story):
    assert "Immediately: 2026-11-07 12:00 EST" in editor.recommendation(story,NOW,[],30)
