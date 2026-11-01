from dataclasses import replace

import pytest

from src.video import publisher as p, reconcile
from src.video.security import AccessError
from src.x.video_client import XClient


def prepare(store, cfg, ready, at):
    ready()
    row = p.reserve(store, at(), cfg)
    with store.transaction() as db:
        db.execute("UPDATE reservations SET state='uploading',media_id='999',media_key='13_999',media_expires=? WHERE id=?",
                   (at().timestamp() + 3600, row["id"]))
    return row


@pytest.mark.parametrize("exc,state", [(TimeoutError(), "publish_unknown"), (AccessError("server", status=500), "publish_unknown"),
                                     (AccessError("rate", status=429), "failed"), (AccessError("expired", status=400), "failed")])
def test_ambiguous_timeout_held_explicit_rejection_released(video_store, video_cfg, ready, at, monkeypatch, exc, state):
    row = prepare(video_store, video_cfg, ready, at)
    monkeypatch.setattr("src.x.video_client.time.time", lambda: at().timestamp())
    monkeypatch.setattr("src.guards.content_guard.validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr("src.guards.respect_list.scrub_text_or_skip", lambda t: (t, ""))
    client = XClient(video_store, video_cfg)
    def failed(*a, **k): raise exc
    monkeypatch.setattr(client, "call", failed)
    client.publish_reserved(row["id"], row["token"])
    assert video_store.rows("SELECT state FROM reservations")[0]["state"] == state
    assert bool(video_store.rows("SELECT * FROM content_claims")) is (state == "publish_unknown")


def test_unknown_requires_positive_media_key_and_caption_match(video_store, video_cfg, ready, at):
    row = prepare(video_store, video_cfg, ready, at)
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET state='publish_unknown'")
    class Client:
        posts = []
        def timeline(self, cursor): return {"data": self.posts}
    client = Client()
    reconcile.reconcile_unknown(video_store, client, at().timestamp())
    assert video_store.rows("SELECT state FROM reservations")[0]["state"] == "publish_unknown"
    client.posts = [{"id": "123456", "text": row["caption"], "attachments": {"media_keys": ["13_999"]}}]
    reconcile.reconcile_unknown(video_store, client, at().timestamp())
    assert video_store.rows("SELECT state FROM reservations")[0]["state"] == "confirmed"


def test_media_expiry_rechecked_before_public_write(video_store, video_cfg, ready, at):
    row = prepare(video_store, video_cfg, ready, at)
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET media_expires=?", (at().timestamp() - 1,))
    with pytest.raises(ValueError, match="expired"):
        p.authorize_submit(video_store, row["id"], row["token"], at().timestamp(), video_cfg)
    assert video_store.rows("SELECT state FROM reservations")[0]["state"] == "uploading"


def test_dry_run_transport_blocks_upload_itself(video_store, video_cfg, settings_override):
    settings_override(DRY_RUN=True)
    client = XClient(video_store, replace(video_cfg, x_reads_enabled=True))
    with pytest.raises(AccessError, match="dry-run"):
        client.call("POST", "/2/media/upload/initialize", {})


def test_chunked_upload_processing_and_checkpoints(video_store, video_cfg, tmp_path, monkeypatch):
    client = XClient(video_store, video_cfg)
    path = tmp_path / "asset.mp4"
    path.write_bytes(b"0" * (4 * 1024 * 1024 + 100))
    calls, checkpoints = [], []
    def call(method, endpoint, *a, **kw):
        calls.append(endpoint)
        if endpoint.endswith("initialize"):
            return {"data": {"id": "123", "media_key": "13_123", "expires_after_secs": 3600}}
        if endpoint.endswith("finalize"):
            return {"data": {"processing_info": {"state": "pending", "check_after_secs": 1}}}
        if "STATUS" in endpoint:
            return {"data": {"processing_info": {"state": "succeeded"}}}
        return {}
    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr("src.x.video_client.time.sleep", lambda _: None)
    result = client.upload(path, lambda *v: checkpoints.append(v), lambda: None)
    assert result[0] == "123" and len(checkpoints) == 2
    assert sum(c.endswith("append") for c in calls) == 2
    assert any("STATUS" in c for c in calls)


def test_upload_failed_processing_never_creates_post(video_store, video_cfg, tmp_path, monkeypatch):
    client = XClient(video_store, video_cfg)
    path = tmp_path / "asset.mp4"
    path.write_bytes(b"test")
    calls = []
    def call(method, endpoint, *a, **kw):
        calls.append(endpoint)
        if endpoint.endswith("initialize"): return {"data": {"id": "123", "expires_after_secs": 3600}}
        if endpoint.endswith("finalize"): return {"data": {"processing_info": {"state": "failed"}}}
        return {}
    monkeypatch.setattr(client, "call", call)
    with pytest.raises(AccessError, match="processing failed"):
        client.upload(path, lambda *v: None, lambda: None)
    assert "/2/tweets" not in calls


def test_account_preflight_is_bound_to_credentials_and_expected_account(video_store, video_cfg, monkeypatch):
    from src.core import account
    client = XClient(video_store, video_cfg)
    client._token, client.user_id = "fixture-token", "123"
    client.scopes = {"tweet.read", "tweet.write", "users.read", "media.write"}
    calls = []
    def correct(*a, **kw):
        calls.append(1)
        return {"data": {"id": "123", "username": account.current().handle}}
    monkeypatch.setattr(client, "call", correct)
    client.preflight(force=False)
    client.preflight(force=False)
    assert len(calls) == 1
    client._token = "rotated-fixture-token"
    client.preflight(force=False)
    assert len(calls) == 2
    monkeypatch.setattr(client, "call", lambda *a, **kw: {"data": {"id": "999", "username": "wrong-account"}})
    with pytest.raises(AccessError, match="different account"):
        client.preflight()
