"""Official X API transport for reserved native videos; never drives Safari."""
import json
import hashlib
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import uuid

from ..core import account
from ..video import config
from ..video.security import AccessError, json_request, request


class XClient:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg
        creds = config.credentials().get("x", {})
        self._token = creds.get("user_access_token", "")
        self.user_id = str(creds.get("user_id", ""))
        self.scopes = set(creds.get("scopes", []))

    def _headers(self):
        if not self._token:
            raise AccessError("missing X OAuth user access token")
        return {"Authorization": "Bearer " + self._token}

    def call(self, method, path, payload=None, *, publishing=False, body=None, headers=None, reservation=None):
        if self.cfg.publishing_transport != "api":
            raise AccessError("X API transport is disabled; Safari is selected")
        if not self.cfg.x_reads_enabled:
            raise AccessError("X API use has not been enabled/budgeted by the operator")
        now = time.time()
        if not self.store.circuit_ready("x", now):
            raise AccessError("X circuit open")
        limit = self.cfg.request_budget if publishing else self.cfg.request_budget - self.cfg.publishing_request_reserve
        if not self.store.budget("x", "requests", 1, limit, now):
            raise AccessError("X request budget exhausted")
        if method != "GET" and not config.live():
            raise AccessError("dry-run prevents every X upload and public write")
        if method != "GET":
            if method != "POST" or not (path in ("/2/tweets", "/2/media/upload/initialize")
                    or re.fullmatch(r"/2/media/upload/\d+/(append|finalize)", path)):
                raise AccessError("unsupported X write surface")
            if path == "/2/tweets":
                self._consume_submission(reservation, payload, now)
        try:
            if body is not None:
                data, _, _ = request("https://api.x.com" + path, hosts={"api.x.com"}, method=method,
                                     body=body, headers={**self._headers(), **(headers or {})}, timeout=20)
                result = json.loads(data) if data else {}
            else:
                result = json_request("https://api.x.com" + path, hosts={"api.x.com"}, method=method,
                                      payload=payload, headers=self._headers(), timeout=20)
            if result.get("errors"):
                raise AccessError("X returned partial/error data")
            self.store.circuit("x", now, failed=False)
            return result
        except (AccessError, TimeoutError, OSError) as exc:
            self.store.circuit("x", now, failed=True, retry_after=getattr(exc, "retry_after", 0))
            raise

    def _consume_submission(self, reservation, payload, now):
        """Even direct transport callers need a once-only durable submit intent."""
        from ..video import schedule
        from datetime import datetime, timezone
        if not reservation or not schedule.eligible(datetime.fromtimestamp(now, timezone.utc)):
            raise AccessError("public video write requires an admitted reservation")
        self.preflight(publishing=True, force=False)
        now = time.time()
        from ..guards.active_hours import break_until, stop_requested
        clock = datetime.fromtimestamp(now, timezone.utc)
        if not schedule.eligible(clock) or break_until(clock) is not None or stop_requested():
            raise AccessError("interaction cooldown or shutdown began before submission")
        with self.store.transaction() as db:
            flags = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM meta WHERE key IN ('paused','shutdown')")}
            row = db.execute("SELECT * FROM reservations WHERE id=? AND token=? AND state='submitting' "
                             "AND network_started IS NULL AND deadline>=? AND lease>=?", (*reservation, now + 20, now)).fetchone()
            if (not row or flags.get("paused", True) or flags.get("shutdown", False)
                    or payload != {"text": row["caption"], "media": {"media_ids": [row["media_id"]]}}):
                raise AccessError("public video reservation already consumed, paused or mismatched")
            db.execute("UPDATE reservations SET network_started=? WHERE id=?", (now, row["id"]))

    def preflight(self, *, publishing=False, force=True):
        if not self._token or not self.user_id:
            raise AccessError("X user_access_token and user_id are missing")
        if not {"tweet.read", "tweet.write", "users.read", "media.write"} <= self.scopes:
            raise AccessError("configured X OAuth scopes must include tweet.read, tweet.write, users.read, media.write")
        digest = hashlib.sha256(self._token.encode()).hexdigest()
        proof = self.store.meta("x_account_proof", {})
        if (not force and proof.get("credential_sha256") == digest and proof.get("user_id") == self.user_id
                and proof.get("username", "").casefold() == account.current().handle.casefold()
                and time.time() - proof.get("checked_at", 0) < 900):
            return {"account_verified": True, "user_id": self.user_id}
        user = self.call("GET", "/2/users/me", publishing=publishing)["data"]
        if str(user["id"]) != self.user_id or user["username"].casefold() != account.current().handle.casefold():
            raise AccessError("X token belongs to a different account")
        self.store.set_meta("x_account_proof", {"user_id": self.user_id, "username": user["username"],
                                               "credential_sha256": digest, "checked_at": time.time()})
        return {"account_verified": True, "write_scopes": "configured; server enforces on actual upload/post", "user_id": self.user_id}

    def timeline(self, cursor=None):
        if not re.fullmatch(r"\d+", self.user_id):
            raise AccessError("invalid X user ID")
        query = {"max_results": 100, "tweet.fields": "created_at,attachments,entities,public_metrics",
                 "expansions": "attachments.media_keys", "media.fields": "type,variants,duration_ms,public_metrics"}
        if cursor:
            query["pagination_token"] = cursor
        return self.call("GET", f"/2/users/{self.user_id}/tweets?" + urlencode(query))

    def search(self, query, cursor=None):
        params = {"query": query, "max_results": 100, "tweet.fields": "entities,attachments,created_at",
                  "expansions": "attachments.media_keys", "media.fields": "type,variants,duration_ms"}
        if cursor:
            params["next_token"] = cursor
        return self.call("GET", "/2/tweets/search/recent?" + urlencode(params))

    def upload(self, path, checkpoint, guard):
        """Persist media IDs immediately; check readiness, expiry and deadline before every chunk."""
        path = Path(path)
        guard()
        initialized = self.call("POST", "/2/media/upload/initialize", {
            "media_type": "video/mp4", "media_category": "tweet_video", "total_bytes": path.stat().st_size}, publishing=True)["data"]
        media_id = str(initialized["id"])
        if not media_id.isdigit():
            raise AccessError("invalid X media ID")
        expires = time.time() + int(initialized.get("expires_after_secs", 0))
        if expires <= time.time():
            raise AccessError("upload expiry missing or expired")
        media_key = initialized.get("media_key")
        checkpoint(media_id, media_key, expires)
        with path.open("rb") as stream:
            index = 0
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                guard()
                if time.time() + 30 >= expires:
                    raise AccessError("media expired before upload completed")
                boundary = "video" + uuid.uuid4().hex
                body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"segment_index\"\r\n\r\n{index}\r\n"
                        f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"chunk.mp4\"\r\n"
                        "Content-Type: application/octet-stream\r\n\r\n").encode() + chunk + f"\r\n--{boundary}--\r\n".encode()
                self.call("POST", f"/2/media/upload/{media_id}/append", publishing=True, body=body,
                          headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
                index += 1
        guard()
        result = self.call("POST", f"/2/media/upload/{media_id}/finalize", publishing=True)["data"]
        if result.get("media_key"):
            media_key = result["media_key"]
        if result.get("expires_after_secs"):
            expires = min(expires, time.time() + int(result["expires_after_secs"]))
        checkpoint(media_id, media_key, expires)
        while result.get("processing_info", {}).get("state", "succeeded") != "succeeded":
            state = result["processing_info"]
            if state["state"] == "failed":
                raise AccessError("X media processing failed")
            if state["state"] not in ("pending", "in_progress"):
                raise AccessError("X media processing state unknown")
            delay = max(1, int(state.get("check_after_secs", 2)))
            for _ in range(delay):
                guard()
                if time.time() + 30 >= expires:
                    raise AccessError("X media expired during processing")
                time.sleep(1)
            result = self.call("GET", "/2/media/upload?" + urlencode({"command": "STATUS", "media_id": media_id}), publishing=True)["data"]
        return media_id, media_key, expires

    def publish_reserved(self, reservation, token):
        """The only native-video public-write chokepoint, with final durable admission."""
        from ..video.publisher import authorize_submit, confirm, unknown, fail_before_submit
        now = time.time()
        row = authorize_submit(self.store, reservation, token, now, self.cfg)
        # No automatic retries here, including exceptions after a possible send.
        try:
            data = self.call("POST", "/2/tweets", {"text": row["caption"],
                             "media": {"media_ids": [row["media_id"]]}}, publishing=True, reservation=(reservation, token))["data"]
            post_id = str(data["id"])
            if not post_id.isdigit():
                raise ValueError("missing confirmed post ID")
        except AccessError as exc:
            if exc.status in (400, 401, 403, 404, 413, 422, 429):
                fail_before_submit(self.store, reservation, token, time.time(), f"X rejected request ({exc.status})", rejected=True)
            else:
                unknown(self.store, reservation, token, time.time(), "publish result uncertain")
            return
        except Exception:
            unknown(self.store, reservation, token, time.time(), "publish result uncertain")
            return
        confirm(self.store, reservation, token, time.time(), post_id)

    def metrics(self, post_id):
        public_only = self.store.meta("metrics_public_only", False)
        fields = "public_metrics" if public_only else "public_metrics,non_public_metrics,organic_metrics"
        try:
            return self.call("GET", "/2/tweets/" + post_id + "?" + urlencode({
                "tweet.fields": fields + ",created_at", "expansions": "attachments.media_keys",
                "media.fields": "type," + fields}))
        except AccessError as exc:
            if exc.status == 403 and not public_only:
                self.store.set_meta("metrics_public_only", True)
            raise
