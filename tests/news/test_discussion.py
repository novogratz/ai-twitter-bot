from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest
from jsonschema import ValidationError

from src.news import discussion, publisher
from src.news.config import NewsConfig
from src.news.store import Store
from src.video.security import Deferred

NOW = datetime(2026, 11, 17, 17, tzinfo=timezone.utc).timestamp()
DRAFT = {"topic": "model_choice", "question": "Which SI model is your favorite right now, and WHY?",
         "options": ["Grok", "Claude", "GPT", "Gemini", "DeepSeek", "Qwen", "Kimi"]}


@pytest.fixture
def cfg():
    return NewsConfig(discussion_topics=["model_choice", "coding_agents"],
                      discussion_models=DRAFT["options"])


@pytest.fixture
def store(tmp_path, settings_override):
    settings_override(NEWS_ENABLED=True, NEWS_AUTO_PUBLISH=True, DISCUSSION_POSTS_ENABLED=True)
    return Store(tmp_path / "news.sqlite3")


class Model:
    def __init__(self, *, approved=True):
        self.calls, self.approved = [], approved

    def call(self, task, data, schema):
        self.calls.append(task)
        if task == "DISCUSSION_DRAFT":
            return deepcopy(DRAFT)
        return {**{k: self.approved for k in discussion.REVIEW_FLAGS}, "reason": "Subjective preference."}


def prepared(store, cfg):
    payload = discussion.prepare(cfg, store=store, model=Model(), now=NOW)
    assert payload
    story = json.loads(store.rows("SELECT document FROM stories WHERE id=?", (payload["id"],))[0]["document"])
    return payload, story


def test_question_uses_reviewed_shared_outbox_without_publishing(store, cfg, monkeypatch):
    from src.x import twitter_client
    monkeypatch.setattr(twitter_client, "post_news", lambda *a: pytest.fail("preparation published"))
    model = Model()
    payload = discussion.prepare(cfg, store=store, model=model, now=NOW)
    assert model.calls == ["DISCUSSION_DRAFT", "DISCUSSION_REVIEW"]
    assert "\n\n• Grok\n• Claude" in payload["tweet"]
    assert payload["weighted_characters"] <= 280 and "https://" not in payload["tweet"]
    assert store.rows("SELECT state FROM outbox")[0]["state"] == "pending"
    assert not discussion.prepare(cfg, store=store, model=model, now=NOW + 7200)
    assert len(model.calls) == 2


def test_disabled_or_unapproved_questions_do_not_queue(store, cfg, settings_override):
    assert discussion.prepare(cfg, store=store, model=Model(approved=False), now=NOW) is None
    assert not store.rows("SELECT id FROM outbox")
    settings_override(DISCUSSION_POSTS_ENABLED=False)
    model = Model()
    assert discussion.prepare(cfg, store=store, model=model, now=NOW + 7200) is None
    assert not model.calls


@pytest.mark.parametrize("change", [
    {"question": "Is Grok 4.7 your favorite model right now, and why?"},
    {"question": "Which SI model is your favorite? https://example.com"},
    {"question": "What is your favorite SI model?\nPlease repost?"},
    {"options": ["Claude Fable 5.2"]},
    {"options": ["Grok", "Grok"]},
])
def test_stale_versions_and_unsupported_choices_are_refused(cfg, change):
    with pytest.raises((ValueError, ValidationError)):
        discussion.tweet(DRAFT | change, cfg)


def test_question_without_model_choices_is_supported(cfg):
    text, _ = discussion.tweet(DRAFT | {"options": []}, replace(cfg, discussion_models=[]))
    assert text == DRAFT["question"]


def test_final_admission_binds_review_bytes_and_opt_in(store, cfg, settings_override):
    payload, story = prepared(store, cfg)
    discussion.admit(store, cfg, story, payload["id"], payload["tweet"], NOW + 1)
    with pytest.raises(ValueError, match="bytes changed"):
        discussion.admit(store, cfg, story, payload["id"], payload["tweet"] + "!", NOW + 1)
    story["final_review"]["no_unsupported_claims"] = False
    with pytest.raises(ValueError, match="approval"):
        discussion.admit(store, cfg, story, payload["id"], payload["tweet"], NOW + 1)
    settings_override(DISCUSSION_POSTS_ENABLED=False)
    with pytest.raises(Deferred, match="disabled"):
        discussion.admit(store, cfg, story, payload["id"], payload["tweet"], NOW + 1)


@pytest.mark.parametrize("state", ["published", "submitting", "publish_unknown"])
def test_cadence_and_uncertain_claims_survive_reopening(store, cfg, state):
    payload, _ = prepared(store, cfg)
    store.execute("UPDATE outbox SET state=?,acknowledged=? WHERE id=?", (state, NOW, payload["id"]))
    reopened = Store(store.path)
    assert discussion.cadence_refusal(reopened, cfg, NOW + 24 * 3600)
    if state == "published":
        assert not discussion.cadence_refusal(reopened, cfg, NOW + 48 * 3600)
    else:
        assert discussion.cadence_refusal(reopened, cfg, NOW + 10 * 86400)


def test_duplicate_question_is_permanent(store, cfg):
    payload, _ = prepared(store, cfg)
    assert discussion.repeated(store, payload["tweet"])
    assert discussion.repeated(Store(store.path), payload["tweet"].replace("WHY", "why"))
    assert discussion.repeated(store, payload["tweet"].split("\n\n")[0] + "\n\n• Grok\n• GPT")


def test_imported_owner_question_is_not_repeated(store, cfg, tmp_path):
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps([{"post_kind": "discussion", "text": DRAFT["question"],
                                 "event_key": "owner-question", "status": "historical"}]))
    assert discussion.prepare(replace(cfg, history_files=[str(owner)]), store=store,
                              model=Model(), now=NOW) is None
    assert not store.rows("SELECT id FROM outbox")


def test_shared_publisher_keeps_video_reservations_and_text_spacing(store, cfg, monkeypatch):
    payload, _ = prepared(store, cfg)
    monkeypatch.setattr(publisher, "video_refusal", lambda *a: "protected video window")
    with pytest.raises(Deferred, match="protected video"):
        publisher.admit(store, cfg, payload["id"], NOW)


def test_discussion_cannot_fulfil_a_startup_news_request(store, cfg):
    store.set_meta("startup_news", {"state": "pending"})
    model = Model()
    assert discussion.prepare(cfg, store=store, model=model, now=NOW) is None
    assert not model.calls


def test_discussion_receipt_does_not_consume_startup_news_intent(store, cfg):
    payload, _ = prepared(store, cfg)
    store.execute("UPDATE outbox SET state='submitting' WHERE id=?", (payload["id"],))
    store.set_meta("startup_news", {"state": "pending"})
    assert publisher.confirmed(store, payload["id"], "https://x.com/example/status/123", NOW + 1)
    assert store.meta("startup_news")["state"] == "pending"


def test_discussion_scheduler_uses_serial_news_executor(settings_override):
    import main
    settings_override(NEWS_ENABLED=True, DISCUSSION_POSTS_ENABLED=True)
    jobs = {job.id: job for job in main.build_scheduler().get_jobs()}
    assert jobs["discussion_post_job"].executor == jobs["news_job"].executor == "news"
    assert "self_repost_job" not in jobs
    assert "discussion_post_job" not in {job.id for job in main.build_scheduler(reply_only=True).get_jobs()}


def test_discussion_interval_cannot_be_below_a_day(cfg):
    with pytest.raises(ValueError):
        replace(cfg, discussion_interval_hours=23)
