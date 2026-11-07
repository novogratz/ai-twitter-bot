"""Bounded public reads, isolated Codex calls and idempotent draft delivery."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from jsonschema import validate

from ..core import llm_client, settings, state_store
from ..video import codex_session, security
from .store import INBOX, dumps


def canonical(url):
    part = urlsplit(url.strip())
    if part.scheme != "https" or not part.hostname or part.username or part.password or part.port not in (None, 443):
        raise ValueError("news URL must be public HTTPS")
    query = [(k, v) for k, v in parse_qsl(part.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid", "ref_src")]
    return urlunsplit(("https", part.hostname.lower(), part.path or "/", urlencode(query), ""))


def timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return result.timestamp() if result.tzinfo else None


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.links, self.dates = [], [], []
        self.canonical = ""
        self.hidden = 0
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.hidden += 1
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href", "")
        if tag == "meta" and any(w in (attrs.get("property", "") + attrs.get("name", "")).lower()
                                  for w in ("published", "modified", "date")):
            self.dates.append({"kind": attrs.get("property") or attrs.get("name"), "value": attrs.get("content", "")})
        if tag == "time" and attrs.get("datetime"):
            self.dates.append({"kind": "time", "value": attrs["datetime"]})
        if tag == "a" and attrs.get("href") and not self.hidden:
            self.link = {"url": attrs["href"], "title": ""}

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.link is not None:
            self.links.append(self.link)
            self.link = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.link is not None:
                self.link["title"] += data


class HTTP:
    def __init__(self, store, cfg, now):
        self.store, self.cfg, self.now, self.calls = store, cfg, now, 0

    def get(self, url):
        security.validate_url(url, self.cfg.hosts)
        cached = self.store.rows("SELECT document FROM cache WHERE url=? AND expires>?", (url, self.now))
        if cached:
            return json.loads(cached[0]["document"])
        cooling = self.store.rows("SELECT until FROM circuits WHERE url=? AND until>?", (url, self.now))
        if cooling:
            raise RuntimeError("source rate-limit/error cooldown")
        for attempt in range(self.cfg.retries + 1):
            if self.calls >= self.cfg.requests_per_run:
                raise RuntimeError("news request budget for this run exhausted")
            self.store.charge("requests", 1, self.cfg.requests_per_day, self.now)
            self.calls += 1
            try:
                data, headers, _ = security.request(url, hosts=self.cfg.hosts, timeout=self.cfg.request_timeout,
                    max_bytes=2_000_000, headers={"User-Agent": "SI-news-drafts/1.0", "Accept-Encoding": "identity"})
                mime = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
                if "pdf" in mime or data.startswith(b"%PDF"):
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(data))
                    if len(reader.pages) > 60:
                        raise ValueError("paper exceeds bounded full-text reader")
                    body = "\n".join(p.extract_text() or "" for p in reader.pages)
                    result = {"body": body, "format": "text"}
                else:
                    result = {"body": data.decode("utf-8", "replace"), "format": "markup"}
                self.store.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                                   (url, self.now + self.cfg.cache_seconds, dumps(result)))
                return result
            except (security.AccessError, OSError, TimeoutError) as exc:
                status, retry = getattr(exc, "status", 0), getattr(exc, "retry_after", 0)
                if status in (401, 403, 404, 429) or attempt == self.cfg.retries or retry:
                    self.store.execute("INSERT OR REPLACE INTO circuits VALUES (?,?)", (url, self.now + max(300, retry)))
                    raise RuntimeError(f"source read failed ({status or type(exc).__name__})") from None
                time.sleep(min(2, .25 * 2 ** attempt))

    def document(self, url):
        raw = self.get(url)
        page = Page()
        if raw["format"] == "markup":
            page.feed(raw["body"])
            body = " ".join(" ".join(page.text).split())
        else:
            body = raw["body"]
        if len(body) < 200:
            raise ValueError("source has insufficient readable evidence")
        resolved = canonical(url)
        if page.canonical:
            observed = canonical(urljoin(url, page.canonical))
            if urlsplit(observed).hostname == urlsplit(url).hostname:
                resolved = observed
        links = []
        for link in page.links:
            try:
                dest = canonical(urljoin(url, link["url"]))
                if urlsplit(dest).hostname in self.cfg.hosts:
                    links.append({"url": dest, "title": " ".join(link["title"].split())[:300]})
            except ValueError:
                continue
        # Metadata is evidence with an explicit kind, never an event date by default.
        for match in re.finditer(r'"(datePublished|dateModified)"\s*:\s*"([^"\n]+)"', raw["body"]):
            page.dates.append({"kind": match[1], "value": match[2]})
        return {"url": resolved, "requested_url": url, "text": body[:40000], "truncated": len(body) > 40000,
                "dates": page.dates, "links": links[:80], **self.cfg.source_info(url)}

    def discover(self, source):
        url = source["url"]
        raw = self.get(url)
        leads = []
        if source["kind"] == "rss":
            root = ET.fromstring(raw["body"])
            if root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
                raise ValueError("endpoint did not return RSS/Atom")
            for node in root.iter():
                if node.tag.split("}")[-1] not in ("item", "entry"):
                    continue
                fields = {n.tag.split("}")[-1]: n for n in node}
                link = next((n.attrib.get("href") or n.text for n in node
                             if n.tag.split("}")[-1] == "link" and n.attrib.get("rel", "alternate") == "alternate"), "")
                title = fields.get("title")
                date = next((fields[k].text for k in ("pubDate", "published", "updated") if k in fields), "")
                leads.append({"url": link or "", "title": "" if title is None else "".join(title.itertext()),
                              "publication_hint": date or "", "evidence_urls": []})
        else:
            page = Page()
            page.feed(raw["body"])
            leads = [{**link, "url": urljoin(url, link["url"]), "publication_hint": "", "evidence_urls": []}
                     for link in page.links]
        result = []
        for lead in leads:
            try:
                lead["url"] = canonical(lead["url"])
                part = urlsplit(lead["url"])
                if part.hostname not in self.cfg.hosts or not part.path.startswith(source["path_prefix"]) or lead["url"] == url:
                    continue
                if len(lead["title"].strip()) <= 15:
                    # Some primary indexes put headlines beside an empty/image
                    # link. A URL hint is a lead, never a fabricated source title.
                    lead["title"] = "URL lead: " + part.path
                if lead["url"] not in {x["url"] for x in result}:
                    result.append(lead)
            except ValueError:
                continue
        return result[:self.cfg.links_per_source]


class Codex:
    def __init__(self, store, cfg, now):
        self.store, self.cfg, self.now, self.calls = store, cfg, now, 0
        self.prompt = Path(cfg.prompt_file).read_text()

    def call(self, task, data, schema, *, search=False):
        if llm_client._read_codex_lockout() is not None:
            raise RuntimeError("shared Codex quota lockout")
        prompt = self.prompt + "\n\nTASK: " + task + "\nUNTRUSTED DATA:\n" + dumps(data)
        if len(prompt) > self.cfg.model_input_chars or self.calls >= self.cfg.model_calls_per_run:
            raise RuntimeError("news model input/run budget exhausted")
        # Actual observed usage, including overruns, is retained. No invented dollar costs.
        self.store.charge("model_tokens", 0, self.cfg.model_tokens_per_day, self.now)
        self.store.charge("model_calls", 1, self.cfg.model_calls_per_day, self.now)
        self.calls += 1
        with tempfile.TemporaryDirectory(prefix="news-codex-") as directory:
            folder = Path(directory)
            schema_path = folder / "schema.json"
            schema_path.write_text(dumps(schema))
            args = codex_session.command(self.cfg, schema_path, folder, (), search=search)
            # Independent subprocess handles: never reuse the media worker's global child.
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
                inp.write(prompt.encode())
                inp.seek(0)
                process = subprocess.Popen(args, stdin=inp, stdout=out, stderr=err, cwd=folder, start_new_session=True)
                deadline = time.monotonic() + self.cfg.codex_timeout_seconds
                try:
                    while process.poll() is None:
                        if time.monotonic() >= deadline or os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 4_000_000:
                            raise TimeoutError("news model deadline/output limit")
                        time.sleep(.1)
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                out.seek(0)
                err.seek(0)
                raw = llm_client.LLMResult(process.returncode, out.read(4_000_000).decode("utf-8", "replace"),
                                           err.read(10000).decode("utf-8", "replace"))
            answer, events = llm_client.codex_background_response(raw, prompt)
            allowed = {"agent_message", "reasoning"} | ({"web_search"} if search else set())
            used = {e.get("item", {}).get("type") for e in events if e.get("type") == "item.completed"}
            if used - allowed:
                raise ValueError("unexpected model tool activity")
            usage = next(e.get("usage", {}) for e in reversed(events) if e.get("type") == "turn.completed")
            total = sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens"))
            self.store.charge("model_tokens", total, 10**12, self.now)
            validate(answer, schema)
            return answer


class PendingDelivery:
    """Operator preparation leaves delivery to the single running publisher."""
    def send(self, delivery_id, payload):
        raise security.Deferred("prepared for the bot's next hourly news run")


class Delivery:
    def __init__(self, cfg, inbox=None):
        self.cfg, self.inbox = cfg, Path(inbox or str(INBOX))

    def send(self, delivery_id, payload):
        if self.cfg.delivery_adapter == "file":
            self.inbox.mkdir(parents=True, exist_ok=True)
            path = self.inbox / (delivery_id + ".json")
            body = dumps(payload) + "\n"
            if path.exists():
                if path.read_text() != body:
                    raise ValueError("delivery identifier already has different content")
            else:
                state_store.atomic_write_bytes(str(path), body.encode())
            return {"id": delivery_id, "destination": str(path), "accepted": True}
        url = settings.get("NEWS_WEBHOOK_URL")
        if not url:
            raise ValueError("NEWS_WEBHOOK_URL is required for webhook delivery")
        # Receiver must persist the idempotency key before acknowledging it.
        host = urlsplit(url).hostname
        headers = {"Idempotency-Key": delivery_id}
        token = settings.get("NEWS_WEBHOOK_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        response = security.json_request(url, hosts={host}, method="POST", payload=payload,
            headers=headers, timeout=self.cfg.request_timeout, max_bytes=20000)
        if response.get("id") != delivery_id or response.get("accepted") is not True:
            raise ValueError("destination did not acknowledge the stable delivery ID")
        return {"id": delivery_id, "accepted": True, "destination": "configured webhook"}
