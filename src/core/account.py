"""The Account the bot runs: accounts/<BOT_ACCOUNT>/account.toml.

The Account holds what the bot says and where it looks: its handle and
language, its Slots and their angles, its feeds, Evergreen topics and trusted
hosts, its relevance filter; its network (the accounts the jobs reply to,
scan, visit or skip, and the Blocked accounts it adds to the engine's), its
niche patterns, its X searches and its Relations. Its folder also holds the
Voice (voice_en.md, voice_fr.md) and the Relations' prompts.
`settings.load()` loads it at start, between the engine defaults and `.env`;
a missing Account, an unknown key or a badly typed value stops the start
with an `AccountError` naming the file.

Read it when it is used, inside the function: `account.current().editorial.
feeds`, never a module-level copy, so a test that swaps the Account reaches
every reader. One Account per process: the Safari lock and `bot.lock` stay
global.

The folder also holds the Operator files (`OperatorFile`, at the end), which
the bot reads and never writes.
"""
import json
import os
import re
import string
import tomllib
from dataclasses import dataclass

from . import settings
from .logger import log
from .state_errors import StateUnreadable

# Relative to the project root; a test points it at an absolute folder.
ACCOUNTS_DIR = "accounts"
LANGUAGES = ("en", "fr")
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
_CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")

_loaded: dict = {}


class AccountError(settings.SettingsError):
    """An Account the bot must not start with."""


@dataclass(frozen=True)
class EvergreenTopic:
    topic: str
    title: str
    url: str
    publisher: str


@dataclass(frozen=True)
class Editorial:
    slots: tuple  # (clock, angle) pairs, earliest first
    trend_angle: str
    trend_clocks: frozenset
    exceptional_clocks: frozenset
    feeds: tuple  # (publisher, url) pairs
    evergreen: tuple  # EvergreenTopic
    trusted_hosts: frozenset


@dataclass(frozen=True)
class Relevance:
    topic: re.Pattern
    off_topic: re.Pattern


@dataclass(frozen=True)
class Account:
    name: str
    folder: str  # absolute: accounts/<name>/, where the Account's other files live
    file: str  # account.toml relative to the project root, for messages
    handle: str
    language: str
    editorial: Editorial
    relevance: Relevance
    limits: dict  # engine setting name -> value, checked by settings
    network: "Network"
    niche: "Niche"
    searches: "Searches"
    relations: "Relations"


def current() -> Account:
    """The Account BOT_ACCOUNT names."""
    return load(settings.get("BOT_ACCOUNT"))


def load(name: str) -> Account:
    """The Account `name`, read and checked once per file."""
    if not _NAME.fullmatch(name):
        raise AccountError(f"BOT_ACCOUNT={name!r}: an Account name is a folder under "
                           f"{ACCOUNTS_DIR}/, lowercase letters, digits, - and _.")
    folder = os.path.abspath(os.path.join(settings.PROJECT_ROOT, ACCOUNTS_DIR, name))
    path = os.path.join(folder, "account.toml")
    if path not in _loaded:
        shown = os.path.join(ACCOUNTS_DIR, name, "account.toml")
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            raise AccountError(f"BOT_ACCOUNT={name}: no Account there, {shown} does not exist.") from None
        except tomllib.TOMLDecodeError as exc:
            raise AccountError(f"{shown} is not valid TOML: {exc}.") from None
        _loaded[path] = _parse(name, folder, shown, data)
    return _loaded[path]


def _parse(name: str, folder: str, shown: str, data: dict) -> Account:
    top = _Table(shown, "", data, required={"handle": str, "language": str, "editorial": dict,
                                             "relevance": dict, "network": dict, "niche": dict,
                                             "searches": dict},
                 optional={"limits": dict, "relations": dict})
    if top["language"] not in LANGUAGES:
        top.fail("language", f"takes one of {', '.join(LANGUAGES)}, not {top['language']!r}")
    editorial = _Table(shown, "editorial", top["editorial"],
                       required={"trend_angle": str, "slots": list, "feeds": list,
                                 "evergreen": list, "trusted_hosts": list})
    relevance = _Table(shown, "relevance", top["relevance"],
                       required={"topic": str, "off_topic": str})
    _check_voice(folder, os.path.dirname(shown))
    network = _network(top)
    return Account(
        name=name, folder=folder, file=shown, handle=top["handle"], language=top["language"],
        editorial=_editorial(editorial), relevance=Relevance(
            topic=_pattern(relevance, "topic"), off_topic=_pattern(relevance, "off_topic")),
        limits=dict(top.get("limits", {})), network=network, niche=_niche(top),
        searches=_searches(top),
        relations=_relations(folder, network, _Table(shown, "relations", top.get("relations", {}),
                                                     required={},
                                                     optional={"default": str, "handles": dict})))


def _editorial(table) -> Editorial:
    slots, trend, exceptional = [], set(), set()
    for i, raw in enumerate(table.items("slots", dict)):
        slot = _Table(table.file, f"editorial.slots[{i}]", raw, required={"clock": str},
                      optional={"angle": str, "trend": bool, "exceptional": bool})
        clock = slot["clock"]
        if not _CLOCK.fullmatch(clock):
            slot.fail("clock", f"takes HH:MM, not {clock!r}")
        if slots and clock <= slots[-1][0]:
            slot.fail("clock", f"{clock} must come after {slots[-1][0]}: Slots go earliest first")
        if slot.get("trend", False) and "angle" in slot:
            slot.fail("angle", "must be absent when trend = true, which takes trend_angle instead")
        if not slot.get("trend", False) and "angle" not in slot:
            slot.fail("angle", "is required unless trend = true")
        if slot.get("trend", False):
            trend.add(clock)
        if slot.get("exceptional", False):
            exceptional.add(clock)
        slots.append((clock, table["trend_angle"] if clock in trend else slot["angle"]))
    feeds = tuple((feed["publisher"], feed["url"])
                  for i, raw in enumerate(table.items("feeds", dict))
                  for feed in [_Table(table.file, f"editorial.feeds[{i}]", raw,
                                      required={"publisher": str, "url": str})])
    evergreen = tuple(EvergreenTopic(**_Table(table.file, f"editorial.evergreen[{i}]", raw,
                                              required={"topic": str, "title": str, "url": str,
                                                        "publisher": str}).values)
                      for i, raw in enumerate(table.items("evergreen", dict)))
    return Editorial(slots=tuple(slots), trend_angle=table["trend_angle"],
                     trend_clocks=frozenset(trend), exceptional_clocks=frozenset(exceptional),
                     feeds=feeds, evergreen=evergreen,
                     trusted_hosts=frozenset(table.items("trusted_hosts", str)))


def _pattern(table, key, flags=re.I) -> re.Pattern:
    try:
        return re.compile(table[key], flags)
    except re.error as exc:
        table.fail(key, f"is not a valid regular expression ({exc})")


# ── Network and niche (#204): the accounts, searches and patterns the jobs use ──

_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
_NETWORK_HANDLES = ("profile_visits", "vip_scan", "pinned_tracked", "vip_reply", "big_ai_hype",
                    "mid_size_ai", "high_traction_reply", "big_fr", "engage_vip",
                    "engage_targets", "reply_targets", "follow_engagers_skip")
_SEARCHES = ("replies", "hot_tab", "likes")


@dataclass(frozen=True)
class Network:
    """X handles as account.toml lists them: order, case and repeats kept."""
    blocked_accounts: tuple  # tokens added to config.BLOCKLIST, which none removes
    profile_visits: tuple
    vip_scan: tuple
    pinned_tracked: tuple
    vip_reply: tuple
    big_ai_hype: tuple
    mid_size_ai: tuple
    high_traction_reply: tuple
    big_fr: tuple
    engage_vip: tuple
    engage_targets: tuple
    reply_targets: tuple
    follow_engagers_skip: tuple

    @property
    def always_reply(self) -> tuple:
        """The accounts early_bird scans first: vip_reply, then the four lists
        after it, a handle listed twice kept at its first place."""
        return tuple(dict.fromkeys(self.vip_reply + self.big_ai_hype + self.mid_size_ai
                                   + self.high_traction_reply + self.big_fr))


@dataclass(frozen=True)
class Niche:
    post: re.Pattern
    ticker: re.Pattern  # case-sensitive: a $TICKER, not any dollar word
    bio: re.Pattern


@dataclass(frozen=True)
class Searches:
    replies: tuple
    hot_tab: tuple
    likes: tuple


def _network(top) -> Network:
    table = _Table(top.file, "network", top["network"],
                   required={key: list for key in _NETWORK_HANDLES},
                   optional={"blocked_accounts": list})
    for key in _NETWORK_HANDLES:
        for i, handle in enumerate(table.items(key, str)):
            if not _HANDLE.fullmatch(handle):
                table.fail(f"{key}[{i}]", f"takes an X handle without @, not {handle!r}")
    blocked = table.items("blocked_accounts", str) if "blocked_accounts" in table else []
    for i, token in enumerate(blocked):
        if not re.search(r"[^\W_]", token):
            table.fail(f"blocked_accounts[{i}]", f"takes a handle or a display name, not {token!r}")
    return Network(blocked_accounts=tuple(blocked),
                   **{key: tuple(table[key]) for key in _NETWORK_HANDLES})


def _niche(top) -> Niche:
    table = _Table(top.file, "niche", top["niche"], required={"post": str, "ticker": str, "bio": str})
    return Niche(post=_pattern(table, "post"), ticker=_pattern(table, "ticker", flags=0),
                 bio=_pattern(table, "bio"))


def _searches(top) -> Searches:
    table = _Table(top.file, "searches", top["searches"], required={key: list for key in _SEARCHES})
    for key in _SEARCHES:
        for i, query in enumerate(table.items(key, str)):
            if not query.strip():
                table.fail(f"{key}[{i}]", "is blank")
    return Searches(**{key: tuple(table[key]) for key in _SEARCHES})


class _Table:
    """One TOML table, its keys and their types checked on construction."""

    def __init__(self, file, where, values, *, required, optional=None):
        self.file, self.where, self.values = file, where, values
        types = {**required, **(optional or {})}
        unknown = sorted(set(values) - set(types))
        if unknown:
            self.fail(unknown[0], "is not a key the Account knows")
        for key in required:
            if key not in values:
                self.fail(key, "is missing")
        for key, value in values.items():
            if type(value) is not types[key]:
                self.fail(key, f"takes a {_kind(types[key])}, not {value!r}")

    def __getitem__(self, key):
        return self.values[key]

    def __contains__(self, key):
        return key in self.values

    def get(self, key, default):
        return self.values.get(key, default)

    def items(self, key, kind) -> list:
        """The list under `key`, each item of type `kind`."""
        for i, item in enumerate(self.values[key]):
            if type(item) is not kind:
                self.fail(f"{key}[{i}]", f"takes a {_kind(kind)}, not {item!r}")
        return self.values[key]

    def fail(self, key, problem):
        where = f"{self.where}.{key}" if self.where else key
        raise AccountError(f"{self.file}: {where} {problem}.")


def _kind(kind) -> str:
    return {str: "string", bool: "boolean", int: "integer", list: "list", dict: "table"}[kind]


# --- Relations: how the Replies treat particular accounts (#203) ---------------

# The fields reply_generator fills in a Reply prompt.
_PROMPT_FIELDS = frozenset({"author", "tweet_text", "original_tweet", "language_override"})
# The CLIs a Relation may name, as src/core/llm_client.ADAPTERS names them
# (a test holds the two together): importing llm_client here would run before
# settings.load() has finished.
CLI_PROVIDERS = ("claude", "codex", "gemini", "opencode")
# The dossier fields personality_store renders, and their types.
_DOSSIER = {"first_seen": str, "last_interaction": str, "interaction_count": int, "category": str,
            "stance": str, "notes": list, "feelings": str, "do": str, "dont": str}


@dataclass(frozen=True)
class Relation:
    """One account the Replies treat apart, by its handle."""
    handle: str  # as account.toml writes it
    prompt: str | None  # its own VIP scan prompt, read at start
    provider: str | None  # the CLI that writes its Replies whenever installed
    dossier: dict | None  # a fixed dossier, in place of personality.json's


@dataclass(frozen=True)
class Relations:
    """The VIP scan's prompts, read at start: a Relation's own prompt, the
    default prompt for a handle without one."""
    default: str | None
    handles: dict  # lowercased handle -> Relation

    def get(self, handle: str) -> Relation | None:
        return self.handles.get((handle or "").lower().lstrip("@").strip())

    def vip_prompt(self, handle: str) -> str | None:
        relation = self.get(handle)
        return relation.prompt if relation and relation.prompt else self.default


def _relations(folder, network, table) -> Relations:
    handles = {}
    for handle, raw in table.get("handles", {}).items():
        where = f"relations.handles.{handle}"
        if not _HANDLE.fullmatch(handle):
            table.fail(f"handles.{handle}", "is not an X handle (letters, digits and _, 15 at most)")
        if type(raw) is not dict:
            table.fail(f"handles.{handle}", f"takes a table, not {raw!r}")
        if handle.lower() in handles:
            table.fail(f"handles.{handle}", f"repeats {handles[handle.lower()].handle}: handles ignore case")
        entry = _Table(table.file, where, raw, required={},
                       optional={"prompt": str, "provider": str, "dossier": dict})
        if not entry.values:
            entry.fail("prompt", "is missing: a Relation sets a prompt, a dossier or both")
        if "provider" in entry and "prompt" not in entry:
            entry.fail("provider", "needs a prompt: it only writes the Relation's own prompt")
        if "provider" in entry and entry["provider"] not in CLI_PROVIDERS:
            entry.fail("provider", f"takes one of {', '.join(CLI_PROVIDERS)}, not {entry['provider']!r}")
        dossier = None
        if "dossier" in entry:
            dossier_table = _Table(table.file, f"{where}.dossier", entry["dossier"], required={},
                                   optional=_DOSSIER)
            if not dossier_table.values:
                entry.fail("dossier", "is empty: a fixed dossier sets at least one field")
            if "notes" in dossier_table:
                dossier_table.items("notes", str)
            dossier = dict(dossier_table.values)
        handles[handle.lower()] = Relation(
            handle=handle, prompt=_prompt(folder, entry, "prompt") if "prompt" in entry else None,
            provider=entry.get("provider", None), dossier=dossier)
    default = _prompt(folder, table, "default") if "default" in table else None
    if default is None:
        for handle in network.vip_scan:
            relation = handles.get(handle.lower())
            if not (relation and relation.prompt):
                table.fail("default", f"is missing: network.vip_scan lists {handle}, which has no "
                                      f"Relation with its own prompt, so the VIP scan needs a default prompt")
    return Relations(default=default, handles=handles)


def _inside(folder, name) -> str | None:
    """The real path of `name`, relative to `folder`, links resolved; None
    when it lands outside the folder."""
    real_folder = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(folder, name))
    return path if os.path.commonpath([real_folder, path]) == real_folder else None


VOICE_FILES = ("voice_en.md", "voice_fr.md")


def _check_voice(folder, shown_folder):
    for name in VOICE_FILES:
        shown = os.path.join(shown_folder, name)
        path = _inside(folder, name)
        if path is None:
            raise AccountError(f"{shown}: the Voice file links outside the Account's folder.")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError as exc:
            raise AccountError(f"{shown}: the Voice file cannot be read ({exc.strerror}).") from None
        if not text:
            raise AccountError(f"{shown}: the Voice file is empty.")


def _prompt(folder, table, key) -> str:
    """The prompt file `table[key]` names, relative to the Account's folder."""
    path = _inside(folder, table[key])
    if path is None:
        table.fail(key, f"names {table[key]!r}, outside the Account's folder")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError as exc:
        table.fail(key, f"names {table[key]!r}, which cannot be read ({exc.strerror})")
    if not text:
        table.fail(key, f"names {table[key]!r}, which is empty")
    try:
        fields = {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError as exc:
        table.fail(key, f"names {table[key]!r}, whose braces do not parse ({exc}); write a brace as {{{{ or }}}}")
    unknown = sorted(fields - _PROMPT_FIELDS)
    if unknown:
        table.fail(key, f"names {table[key]!r}, whose {{{unknown[0]}}} is no Reply prompt field "
                        f"({', '.join(sorted(_PROMPT_FIELDS))})")
    return text


# --- Operator files -----------------------------------------------------------


class OperatorFile:
    """A JSON file the Operator keeps in the Account folder, versioned with
    it: `accounts/<BOT_ACCOUNT>/<name>`, read at each call. The bot never
    writes it, so the class offers no write; what the bot keeps goes in a
    `state_store.StateFile`.

    `read` returns the parsed value. A missing file, bad JSON or a top-level
    type other than `kind` logs and raises StateUnreadable: the job that
    needs the file stops, and nothing recreates it with defaults."""

    def __init__(self, name: str, kind: type):
        self.name = name
        self._kind = kind

    @property
    def path(self) -> str:
        return os.path.join(current().folder, self.name)

    def read(self):
        shown = os.path.join(ACCOUNTS_DIR, current().name, self.name)
        try:
            with open(self.path, encoding="utf-8") as f:
                value = json.load(f)
        except FileNotFoundError:
            return self._unreadable(f"{shown} is missing: the Operator's file is never "
                                    f"recreated, restore it from git")
        except (OSError, ValueError) as exc:
            return self._unreadable(f"{shown} is unreadable ({exc})")
        if not isinstance(value, self._kind):
            return self._unreadable(f"{shown} is unreadable (top-level {type(value).__name__}, "
                                    f"expected {self._kind.__name__})")
        return value

    @staticmethod
    def _unreadable(why: str):
        log.error(f"[OPERATOR] {why}: refusing (docs/OPERATIONS.md#recovery).")
        raise StateUnreadable(why)
