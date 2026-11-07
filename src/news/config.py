"""Operator configuration for the independent hourly news worker."""
from dataclasses import dataclass, field, fields
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

from ..core import account, settings


@dataclass(frozen=True)
class NewsConfig:
    search_adapter: str = "codex"
    delivery_adapter: str = "file"
    codex_model: str = ""
    codex_timeout_seconds: int = 240
    request_timeout: int = 20
    retries: int = 2
    cache_seconds: int = 1800
    requests_per_run: int = 80
    requests_per_day: int = 1200
    model_calls_per_run: int = 8
    model_calls_per_day: int = 120
    model_input_chars: int = 180000
    model_tokens_per_day: int = 2000000
    candidates_per_run: int = 6
    links_per_source: int = 8
    score_min: int = 85
    backup_score_min: int = 90
    video_gap_minutes: int = 30
    delivery_attempts: int = 5
    prompt_file: str = "news_prompt.md"
    history_files: list = field(default_factory=list)
    queue_files: list = field(default_factory=list)
    search_queries: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    evidence_hosts: list = field(default_factory=list)

    def __post_init__(self):
        if self.search_adapter not in ("codex", "none") or self.delivery_adapter not in ("file", "webhook"):
            raise ValueError("news adapters must be codex/none and file/webhook")
        for item in fields(self):
            value = getattr(self, item.name)
            if item.type is int and (type(value) is not int or value < (0 if item.name == "retries" else 1)):
                raise ValueError(f"invalid news setting: {item.name}")
            if item.type is list and not isinstance(value, list):
                raise ValueError(f"invalid news list: {item.name}")
        if not (self.retries <= 3 and self.codex_timeout_seconds <= 300 and self.request_timeout <= 60
                and self.candidates_per_run <= 12 and 80 <= self.score_min <= self.backup_score_min <= 100):
            raise ValueError("news time, retry, candidate or quality bounds exceeded")
        for source in self.sources:
            if set(source) != {"name", "url", "kind", "role", "owner", "path_prefix"}:
                raise ValueError("news sources need name/url/kind/role/owner/path_prefix")
            if source["kind"] not in ("rss", "html") or source["role"] not in ("primary", "reporting", "lead"):
                raise ValueError("invalid source kind/role")
            if urlsplit(source["url"]).scheme != "https":
                raise ValueError("news endpoints must use HTTPS")

    @property
    def hosts(self):
        return frozenset(self.evidence_hosts) | {urlsplit(s["url"]).hostname for s in self.sources}

    def source_info(self, url):
        host = urlsplit(url).hostname
        for source in self.sources:
            if urlsplit(source["url"]).hostname == host:
                return {k: source[k] for k in ("name", "role", "owner")}
        if host in ("x.com", "www.x.com", "twitter.com", "news.ycombinator.com", "reddit.com", "www.reddit.com"):
            return {"name": host, "role": "lead", "owner": host}
        family = ".".join((host or "").split(".")[-2:])
        for source in self.sources:
            if urlsplit(source["url"]).hostname.endswith("." + family) or urlsplit(source["url"]).hostname == family:
                return {"name": host, "role": "evidence", "owner": source["owner"]}
        return {"name": host, "role": "evidence", "owner": family}


def load(path=None):
    path = Path(path or settings.get("NEWS_CONFIG_FILE") or Path(account.current().folder) / "news.toml")
    raw = tomllib.loads(path.read_text())
    raw["prompt_file"] = str((path.parent / raw.get("prompt_file", "news_prompt.md")).resolve())
    for key in ("history_files", "queue_files"):
        raw[key] = [str((path.parent / p).resolve()) for p in raw.get(key, [])]
    return NewsConfig(**raw)
