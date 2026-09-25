"""The Account the bot runs: accounts/<BOT_ACCOUNT>/account.toml.

The Account holds what the bot says and where it looks: its handle and
language, its Slots and their angles, its feeds, Evergreen topics and trusted
hosts, its relevance filter. `settings.load()` loads it at start, between the
engine defaults and `.env`; a missing Account, an unknown key or a badly
typed value stops the start with an `AccountError` naming the file.

Read it when it is used, inside the function: `account.current().editorial.
feeds`, never a module-level copy, so a test that swaps the Account reaches
every reader. One Account per process: the Safari lock and `bot.lock` stay
global.
"""
import os
import re
import tomllib
from dataclasses import dataclass

from . import settings

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
    file: str
    handle: str
    language: str
    editorial: Editorial
    relevance: Relevance
    limits: dict  # engine setting name -> value, checked by settings


def current() -> Account:
    """The Account BOT_ACCOUNT names."""
    return load(settings.get("BOT_ACCOUNT"))


def load(name: str) -> Account:
    """The Account `name`, read and checked once per file."""
    if not _NAME.fullmatch(name):
        raise AccountError(f"BOT_ACCOUNT={name!r}: an Account name is a folder under "
                           f"{ACCOUNTS_DIR}/, lowercase letters, digits, - and _.")
    path = os.path.join(settings.PROJECT_ROOT, ACCOUNTS_DIR, name, "account.toml")
    if path not in _loaded:
        shown = os.path.join(ACCOUNTS_DIR, name, "account.toml")
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            raise AccountError(f"BOT_ACCOUNT={name}: no Account there, {shown} does not exist.") from None
        except tomllib.TOMLDecodeError as exc:
            raise AccountError(f"{shown} is not valid TOML: {exc}.") from None
        _loaded[path] = _parse(name, shown, data)
    return _loaded[path]


def _parse(name: str, shown: str, data: dict) -> Account:
    top = _Table(shown, "", data, required={"handle": str, "language": str, "editorial": dict,
                                             "relevance": dict}, optional={"limits": dict})
    if top["language"] not in LANGUAGES:
        top.fail("language", f"takes one of {', '.join(LANGUAGES)}, not {top['language']!r}")
    editorial = _Table(shown, "editorial", top["editorial"],
                       required={"trend_angle": str, "slots": list, "feeds": list,
                                 "evergreen": list, "trusted_hosts": list})
    relevance = _Table(shown, "relevance", top["relevance"],
                       required={"topic": str, "off_topic": str})
    return Account(
        name=name, file=shown, handle=top["handle"], language=top["language"],
        editorial=_editorial(editorial), relevance=Relevance(
            topic=_pattern(relevance, "topic"), off_topic=_pattern(relevance, "off_topic")),
        limits=dict(top.get("limits", {})))


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
        if slot.get("trend", False) == ("angle" in slot):
            slot.fail("angle", "is required unless trend = true, which takes trend_angle instead")
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


def _pattern(table, key) -> re.Pattern:
    try:
        return re.compile(table[key], re.I)
    except re.error as exc:
        table.fail(key, f"is not a valid regular expression ({exc})")


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
    return {str: "string", bool: "boolean", list: "list", dict: "table"}[kind]
