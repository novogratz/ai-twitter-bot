"""Operator-owned video settings; no source metadata can configure the workers."""
from dataclasses import dataclass, field, fields
from pathlib import Path
import json
import math
import re
import sqlite3
import tomllib

from ..core import account, config as core_config, settings

PLATFORMS = ("instagram", "tiktok", "bilibili", "rednote", "x")


@dataclass(frozen=True)
class VideoConfig:
    publishing_transport: str = "safari"
    browser_upload_seconds: int = 45
    windows: tuple = ("07:00", "09:00", "12:00", "17:00", "21:00")
    paired_windows: tuple = ("07:00", "21:00")
    scheduled_daily_cap: int = 8
    news_enabled: bool = False
    news_daily_cap: int = 10
    auto_edit: bool = False
    source_max_duration_seconds: int = 300
    edit_min_seconds: int = 8
    edit_max_seconds: int = 60
    min_hook_score: int = 8
    bangers_only: bool = False
    one_line_caption: bool = False
    audience_examples: tuple = ()
    startup_on_boot: bool = False
    pair_minutes: int = 15
    protect_primary_windows: bool = True
    preparation_lead_seconds: int = 1800
    initial_history_pages: int = 0
    allow_unknown_momentum: bool = False
    allow_source_overlays: bool = False
    caption_disclosure: bool = True
    grace_seconds: int = 600
    min_spacing_seconds: int = 900
    startup_seconds: int = 3600
    day_poll_seconds: int = 1200
    night_poll_seconds: int = 600
    buffer_target: int = 16
    queue_limit: int = 500
    score_threshold: float = 80.0
    confidence_min: float = 0.9
    preferred_age_hours: int = 72
    max_age_hours: int = 168
    lease_seconds: int = 900
    media_job_seconds: int = 600
    max_media_memory_mb: int = 2048
    asset_retention_days: int = 14
    task_timeout_seconds: int = 120
    render_timeout_seconds: int = 120
    max_attempts: int = 4
    request_budget: int = 500
    publishing_request_reserve: int = 40
    download_budget_bytes: int = 2_000_000_000
    storage_budget_bytes: int = 5_000_000_000
    max_download_bytes: int = 150_000_000
    inference_budget_usd: float = 0.0
    inspection_cost_ceiling_usd: float = 0.0
    max_duration_seconds: int = 140
    render_threads: int = 1
    max_load_per_cpu: float = 0.75
    min_free_memory_mb: int = 1024
    max_reply_backlog: int = 12
    reply_latency_ratio: float = 1.10
    min_latency_samples: int = 30
    inspection_command: tuple = ()
    inspection_provider: str = "command"
    codex_model: str = ""  # blank inherits the existing Codex Reply model
    codex_timeout_seconds: int = 180
    codex_daily_calls: int = 96
    codex_daily_input_tokens: int = 2_000_000
    codex_inspection_reserve: int = 48
    codex_max_reply_calls: int = 2
    inspection_fps: int = 2
    font_file: str = "/System/Library/Fonts/Supplemental/Arial.ttf"
    watermark: str = ""
    targets: dict = field(default_factory=dict)
    target_handles: dict = field(default_factory=dict)
    platforms: dict = field(default_factory=dict)
    permissions: dict = field(default_factory=dict)
    media_hosts: tuple = ()
    local_import_roots: tuple = ()
    # API use must be explicitly budgeted by the operator, including paid reads.
    x_reads_enabled: bool = False

    def __post_init__(self):
        if self.publishing_transport not in ("safari", "api"):
            raise ValueError("publishing_transport must be safari or api")
        if self.inspection_provider not in ("command", "codex"):
            raise ValueError("inspection_provider must be command or codex")
        if not isinstance(self.codex_model, str):
            raise ValueError("codex_model must be a string")
        for name in ("codex_timeout_seconds", "codex_daily_calls", "codex_daily_input_tokens", "codex_inspection_reserve", "codex_max_reply_calls"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not 30 <= self.codex_timeout_seconds <= 300 or self.codex_timeout_seconds >= self.lease_seconds:
            raise ValueError("Codex timeout must be 30..300 seconds and inside the job lease")
        if self.codex_inspection_reserve >= self.codex_daily_calls or self.inspection_fps not in (1, 2):
            raise ValueError("invalid Codex reserve or inspection frame sampling")
        if type(self.browser_upload_seconds) is not int or not 10 <= self.browser_upload_seconds <= 180:
            raise ValueError("browser_upload_seconds must be 10..180 to bound upload plus X processing")
        if type(self.x_reads_enabled) is not bool:
            raise ValueError("x_reads_enabled must be a boolean")
        if type(self.startup_on_boot) is not bool:
            raise ValueError("startup_on_boot must be a boolean")
        if type(self.scheduled_daily_cap) is not int or not 5 <= self.scheduled_daily_cap <= 13:
            raise ValueError("scheduled_daily_cap must be 5..13")
        for name in ("news_enabled", "auto_edit", "bangers_only", "one_line_caption"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if type(self.news_daily_cap) is not int or not 1 <= self.news_daily_cap <= 10:
            raise ValueError("news_daily_cap must be 1..10")
        for name in ("source_max_duration_seconds", "edit_min_seconds", "edit_max_seconds", "min_hook_score"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.auto_edit and not 8 <= self.edit_min_seconds <= self.edit_max_seconds <= self.max_duration_seconds:
            raise ValueError("edit duration must be 8 seconds through the output duration limit")
        if not self.max_duration_seconds <= self.source_max_duration_seconds <= 300:
            raise ValueError("source duration must be within the output limit and 300 seconds")
        if not 8 <= self.min_hook_score <= 10:
            raise ValueError("opening hook threshold must be 8..10")
        if not set(self.target_handles) <= set(self.targets) or any(
                not isinstance(handle, str) or not re.fullmatch(r"@[A-Za-z0-9_]{1,15}", handle)
                for handle in self.target_handles.values()):
            raise ValueError("target_handles must map configured cast keys to X handles")
        if type(self.protect_primary_windows) is not bool:
            raise ValueError("protect_primary_windows must be a boolean")
        if type(self.allow_unknown_momentum) is not bool:
            raise ValueError("allow_unknown_momentum must be a boolean")
        if type(self.preparation_lead_seconds) is not int or not 300 <= self.preparation_lead_seconds <= 3600:
            raise ValueError("preparation lead must be 300..3600 seconds")
        if type(self.initial_history_pages) is not int or not 0 <= self.initial_history_pages <= 60:
            raise ValueError("initial history pages must be 0 (complete archive) or 1..60")
        if type(self.allow_source_overlays) is not bool:
            raise ValueError("allow_source_overlays must be a boolean")
        if type(self.caption_disclosure) is not bool:
            raise ValueError("caption_disclosure must be a boolean")
        for key in ("score_threshold", "confidence_min", "inference_budget_usd", "inspection_cost_ceiling_usd",
                    "max_load_per_cpu", "reply_latency_ratio"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"video {key} must be a finite number")
        for name in ("windows", "paired_windows", "inspection_command", "media_hosts", "local_import_roots", "audience_examples"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if len(self.audience_examples) > 6 or any(not isinstance(item, dict)
                or type(item.get("views")) is not int or item["views"] < 0
                or not isinstance(item.get("url"), str) or not item["url"].startswith("https://x.com/")
                or not isinstance(item.get("observed_at"), str)
                or not isinstance(item.get("caption"), str) or len(item["caption"]) > 600
                for item in self.audience_examples):
            raise ValueError("audience examples require at most six observed public posts")
        for key in ("pair_minutes", "min_spacing_seconds", "grace_seconds", "startup_seconds", "queue_limit",
                    "buffer_target", "lease_seconds", "task_timeout_seconds", "render_timeout_seconds",
                    "day_poll_seconds", "night_poll_seconds", "max_attempts", "max_download_bytes",
                    "storage_budget_bytes", "download_budget_bytes", "request_budget", "max_duration_seconds"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"video {key} must be a positive integer")
        for key in ("media_job_seconds", "max_media_memory_mb", "min_free_memory_mb", "min_latency_samples", "max_reply_backlog", "asset_retention_days"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"video {key} must be a positive integer")
        for key in ("inference_budget_usd", "inspection_cost_ceiling_usd"):
            value = getattr(self, key)
            if type(value) not in (int, float) or value < 0:
                raise ValueError(f"video {key} must be a nonnegative number")
        if not 0 < self.max_load_per_cpu <= 1 or self.reply_latency_ratio < 1:
            raise ValueError("invalid background resource/latency thresholds")
        if not 0 < self.preferred_age_hours <= self.max_age_hours:
            raise ValueError("preferred age must be positive and within fallback")
        if self.pair_minutes < 15 or self.min_spacing_seconds < 900 or self.startup_seconds > 3600:
            raise ValueError("video spacing cannot be below 15 minutes; startup cannot exceed one eligible hour")
        if self.grace_seconds > 600 or not 0 <= self.score_threshold <= 100:
            raise ValueError("video grace must be <=600 seconds; score must be 0..100")
        if not 0.9 <= self.confidence_min <= 1 or self.render_threads != 1:
            raise ValueError("video confidence must be >=0.9; reserve resources with one render thread")
        if self.max_age_hours > 730 * 24 or self.max_duration_seconds > 140:
            raise ValueError("video fallback is at most two years; conservative duration cap is 140 seconds")
        if self.lease_seconds <= max(self.task_timeout_seconds, self.render_timeout_seconds):
            raise ValueError("video lease must exceed every bounded subprocess deadline")
        if self.lease_seconds <= self.media_job_seconds + self.task_timeout_seconds:
            raise ValueError("video lease must exceed the complete media-job deadline plus one download")
        if self.publishing_request_reserve >= self.request_budget:
            raise ValueError("video request budget must leave both discovery and publishing capacity")
        if self.inspection_command and not Path(self.inspection_command[0]).is_absolute():
            raise ValueError("inspection_command must start with an absolute executable path")
        if not set(self.platforms) <= set(PLATFORMS):
            raise ValueError("unknown video platform")
        from .schedule import clocks
        clocks(self)  # also validates the configured distinct slots


def enabled():
    return settings.get("VIDEO_ENABLED")


def source_duration_limit(cfg):
    return cfg.source_max_duration_seconds if cfg.auto_edit else cfg.max_duration_seconds


def live():
    return enabled() and settings.get("VIDEO_LIVE") and not core_config.dry_run()


def owns_profile():
    """Also guard a misconfigured rollback while a video service remains activated."""
    if enabled():
        return True
    from .store import DATABASE
    if not Path(str(DATABASE)).exists():
        return False
    try:
        db = sqlite3.connect("file:" + str(DATABASE) + "?mode=ro", uri=True, timeout=.05)
        try:
            row = db.execute("SELECT value FROM meta WHERE key='profile_owned'").fetchone()
            return bool(row and json.loads(row[0]))
        finally:
            db.close()
    except (sqlite3.Error, ValueError):
        return True  # guarded publication state is unreadable


def legacy_usage(now):
    """Preserve video facts when the operator returns to the older profile policy."""
    from .store import DATABASE
    from .schedule import local
    if not Path(str(DATABASE)).exists():
        return 0, None
    start = local(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    db = sqlite3.connect("file:" + str(DATABASE) + "?mode=ro", uri=True, timeout=.05)
    try:
        count = db.execute("SELECT COUNT(*) FROM reservations WHERE state='confirmed' AND confirmed>=?", (start,)).fetchone()[0]
        last = db.execute("SELECT MAX(confirmed) FROM reservations WHERE state='confirmed'").fetchone()[0]
        return count, last
    finally:
        db.close()


def load() -> VideoConfig:
    path = Path(settings.get("VIDEO_CONFIG_FILE") or (Path(account.current().folder) / "video.toml"))
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    unknown = set(raw) - {f.name for f in fields(VideoConfig)}
    if unknown:
        raise ValueError(f"unknown video configuration keys: {sorted(unknown)}")
    return VideoConfig(**raw)


def credentials() -> dict:
    path = settings.get("VIDEO_CREDENTIALS_FILE")
    if not path:
        return {}
    file = Path(path).expanduser()
    if file.stat().st_mode & 0o077:
        raise ValueError("video credentials file must be private (chmod 600)")
    value = json.loads(file.read_text())
    if not isinstance(value, dict):
        raise ValueError("video credentials must be a JSON object")
    return value


def safe_label(value, limit=120):
    """Single-line reporting only; never log tokens, source text or signed URLs."""
    return re.sub(r"[^\w .:/@-]", "?", str(value))[:limit]
