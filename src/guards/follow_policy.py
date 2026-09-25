"""The follow policy: may the account follow this handle, and the follow
files it reads and keeps (CONTEXT.md: Follow refusal).

- `judge(handle)` runs before the profile opens: the handle, the whitelist,
  anti-churn, the daily cap, the spacing, the following ceiling and ratio
  brake, then the quality-reject cache.
- `judge_profile(handle, read_profile)` runs on the open profile, before
  the click: the quality gate, which caches what it rejects for 30 days.
- `followed()` and `record_followed(handle)` are the record of the accounts
  followed; `adjust_following(delta)` keeps the following count.

`follow_account` asks both judgements and names the refusal in its outcome,
so a job acts on the cause without checking the rule again. The ledger
facts (today's follows, spacing, last touch) come from `action_guard`.
"""
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..core import config
from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..core.state_store import DISPOSABLE, GUARDED, StateFile
from . import action_guard

# Guarded: the record of the accounts followed. engage_job follows every
# pool handle missing from it, and the ceiling counts it when
# following_count.json holds no count.
FOLLOWED = StateFile("followed_accounts.json", [], GUARDED)
# Guarded: the ceiling's count; the followed list under-counts the real
# following, so falling back to it would admit follows past the ceiling.
FOLLOWING_COUNT = StateFile("following_count.json", {}, GUARDED)
# Disposable: growth samples, where a fresh sample matters more than the
# series; without them the ceiling takes its lowest value and the ratio
# brake refuses, so losing them never admits a follow.
FOLLOWER_HISTORY = StateFile("follower_history.json", [], DISPOSABLE)
# Guarded: the Operator's follow whitelist, which account_curator extends.
# Read as empty, it would unprotect every seed from an unfollow.
WHITELIST = StateFile("whitelist.json", {}, GUARDED)
# Disposable: the quality gate reads the profile again before any click, so
# a lost cache costs a profile visit, never a follow.
QUALITY_REJECTS = StateFile("follow_quality_rejects.json", {}, DISPOSABLE)

_HANDLE_RE = re.compile(r"[A-Za-z0-9_]{1,15}")


class Refusal(Enum):
    TOO_SOON = "too soon after the last follow"
    CAP_REACHED = "follow budget reached"
    QUALITY_REJECTED = "quality gate"
    POLICY = "follow policy"


@dataclass(frozen=True)
class Verdict:
    refusal: Refusal | None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.refusal is None


ADMITTED = Verdict(None)


# --- whitelist --------------------------------------------------------------

def load_whitelist() -> dict:
    """Return {"tier1": set, ..., "tier4": set, "all": set} of lowercased
    handles. tier4 (2026-06-07 spec: crypto/markets crossover seeds) is
    optional in the file. Raises StateUnreadable while whitelist.json
    cannot be read."""
    raw = WHITELIST.read()

    def _norm(seq):
        return {str(h).lower().lstrip("@") for h in (seq or [])}

    tiers = raw.get("tiers", raw)  # tolerate flat or nested shape
    t1 = _norm(tiers.get("tier1") or tiers.get("tier1_sources_targets"))
    t2 = _norm(tiers.get("tier2") or tiers.get("tier2_peers"))
    t3 = _norm(tiers.get("tier3") or tiers.get("tier3_watch"))
    t4 = _norm(tiers.get("tier4"))
    # "discovered" tier: curator-promoted handles (2026-06-07 operator grant
    # — the bot develops its own follow list). Same follow rights as seeds;
    # additions capped + logged in account_curator.
    t5 = _norm(tiers.get("discovered"))
    return {"tier1": t1, "tier2": t2, "tier3": t3, "tier4": t4,
            "discovered": t5, "all": t1 | t2 | t3 | t4 | t5}


def is_whitelisted(handle: str,
                   tiers=("tier1", "tier2", "tier3", "tier4", "discovered")) -> bool:
    """Raises StateUnreadable while whitelist.json cannot be read."""
    h = (handle or "").lower().lstrip("@")
    wl = load_whitelist()
    return any(h in wl[t] for t in tiers)


# --- the record of the accounts followed -----------------------------------

def followed() -> set:
    """Every handle the account followed or found already followed. Raises
    StateUnreadable while followed_accounts.json cannot be read."""
    return set(FOLLOWED.read())


def record_followed(handle: str) -> None:
    """Add `handle` to the record, merged with the disk under the file's lock
    so concurrent jobs keep each other's follows. Runs after a follow shipped
    or was found done: an unreadable record is logged, never raised, and
    stays as it is."""
    try:
        FOLLOWED.update(lambda on_disk: sorted(set(on_disk) | {handle}))
    except StateUnreadable as exc:
        log.error(f"[FOLLOW] @{handle} not added to the followed accounts: {exc}")


# --- follower / following counts (best-effort, conservative) ---------------

def _current_counts() -> tuple[int | None, int]:
    """(followers, following). Followers from follower_history.json (latest),
    None when unknown. Following: the env override, else following_count.json,
    else the tracked followed set (which under-counts true following).
    Raises StateUnreadable when following_count.json or the followed set
    cannot be read.
    """
    followers = None
    hist = FOLLOWER_HISTORY.read()
    try:
        if hist:
            followers = int(hist[-1].get("count"))
    except (AttributeError, ValueError, TypeError):
        pass

    override = os.environ.get("FOLLOWING_COUNT_OVERRIDE")
    if override and override.isdigit():
        return followers, int(override)
    try:
        return followers, int(FOLLOWING_COUNT.read().get("count"))
    except (ValueError, TypeError):
        return followers, len(FOLLOWED.read())


def adjust_following(delta: int) -> None:
    """Keep the live following counter in sync after a real follow/unfollow.

    The ratio invariant needs the TRUE following count, which followed_accounts
    .json under-reports. We track it from a manually-seeded baseline and apply
    +1 per follow / -1 per unfollow so the gate reflects reality as the prune
    runs. A periodic profile scrape can overwrite count for an exact resync.
    """
    if config.dry_run():
        return

    def adjust(doc):
        cur = doc.get("count")
        if not isinstance(cur, int):
            return None  # no baseline set — don't fabricate one
        return {**doc, "count": max(0, cur + delta), "updated": datetime.now().isoformat()}
    # Runs after a shipped write: raising would hide it from the caller. The
    # file stays as it is, and judge refuses while it is unreadable.
    try:
        FOLLOWING_COUNT.update(adjust)
    except StateUnreadable as exc:
        log.error(f"[FOLLOW] following count not adjusted by {delta:+d}: {exc}")


def _following_ceiling(followers: int | None) -> int:
    """Max total following allowed right now (2026-06-07 spec, Part 1),
    given the latest follower count, None when unknown.

    Hard constraints, never violated: total following cap 300; while
    followers are low (< FOLLOW_LOW_PHASE_FOLLOWERS) stay under the credible
    ~150; once followers exceed that, keep following <= followers (still
    capped at 300).
    """
    # Growth mode (operator 2026-06-11: follows + followback back ON):
    # the ceiling is FOLLOW_TOTAL_CAP alone — the followers-tied bound
    # below would block every follow while the manual purge is mid-flight
    # (following > followers). Daily cap + spacing + anti-churn still apply.
    if config.FOLLOW_GROWTH_MODE:
        return config.FOLLOW_TOTAL_CAP
    if followers is None or followers < config.FOLLOW_LOW_PHASE_FOLLOWERS:
        return min(config.FOLLOW_TOTAL_CAP, config.FOLLOW_LOW_PHASE_CEILING)
    return min(config.FOLLOW_TOTAL_CAP, followers)


# --- before the profile opens -----------------------------------------------

def judge(handle: str, *, reciprocal: bool = False) -> Verdict:
    """2026-06-07 spec follow policy — whitelist-only seed/discovery list,
    hard total-following ceiling (300 cap / ~150 while followers are low),
    20/day pacing with >=10-min randomized gaps, 30-day anti-churn — then
    the quality-reject cache.

    `reciprocal=True` (a follow-back of someone who already engages with us)
    bypasses ONLY the whitelist-only gate when FOLLOWBACK_BYPASS_WHITELIST is
    set — every other gate (churn, daily cap, spacing, ceiling) still applies.

    TOO_SOON and CAP_REACHED are about the account's follow budget, not the
    handle: a later cycle may admit the same handle. A ceiling that cannot
    be read or checked counts as reached.
    """
    # X handles are [A-Za-z0-9_]{1,15}. Anything else (spaces, slashes,
    # accents, > 15 chars) is a scraper artifact like "aisha mansion" and
    # would just burn a profile visit.
    if not _HANDLE_RE.fullmatch(handle or ""):
        return Verdict(Refusal.POLICY, f"invalid handle {handle!r}")
    h = handle.lower()
    # judge_profile reads the whitelist too: an unreadable one admits no
    # follow, whitelist-only mode or not.
    try:
        whitelisted = is_whitelisted(h)
    except StateUnreadable as exc:
        return Verdict(Refusal.POLICY, f"whitelist unreadable ({exc})")
    exempt = reciprocal and config.FOLLOWBACK_BYPASS_WHITELIST
    if config.FOLLOW_WHITELIST_ONLY and not whitelisted and not exempt:
        return Verdict(Refusal.POLICY,
                       "not on whitelist (whitelist-only mode; no strangers, no reciprocity)")
    if action_guard.within_churn_cooldown(h):
        return Verdict(Refusal.POLICY, f"anti-churn: touched within {config.CHURN_COOLDOWN_DAYS}d")
    follows_today = action_guard.count_today(action_guard.FOLLOW)
    if follows_today >= config.MAX_FOLLOWS_PER_DAY:
        return Verdict(Refusal.CAP_REACHED, f"daily follow cap reached ({config.MAX_FOLLOWS_PER_DAY})")
    # Never burst-follow: >=10-min jittered gap between follows (spec Part 1).
    why = action_guard.too_soon(action_guard.FOLLOW)
    if why:
        return Verdict(Refusal.TOO_SOON, why)
    # Hard total-following ceiling — never exceed 300; ~150 while followers
    # are low; following <= followers once followers pass the low phase.
    try:
        followers, following = _current_counts()
    except StateUnreadable as exc:
        return Verdict(Refusal.CAP_REACHED, f"following ceiling unreadable ({exc})")
    ceiling = _following_ceiling(followers)
    if following + 1 > ceiling:
        return Verdict(Refusal.CAP_REACHED, f"total following ceiling reached ({following} >= {ceiling})")
    # Legacy net-negative ratio brake (kept behind FOLLOW_ENFORCE_RATIO).
    if config.FOLLOW_ENFORCE_RATIO:
        if followers is None:
            return Verdict(Refusal.CAP_REACHED, "follower count unknown: ratio brake cannot be checked")
        unfollows_today = action_guard.count_today(action_guard.UNFOLLOW)
        over_ceiling = (following + 1) > config.FOLLOW_RATIO_CEILING * followers
        if over_ceiling and follows_today >= unfollows_today:
            return Verdict(Refusal.CAP_REACHED,
                           f"over ratio ceiling (following {following} vs "
                           f"{config.FOLLOW_RATIO_CEILING}*{followers}); day not net-negative "
                           f"(follows {follows_today} >= unfollows {unfollows_today})")
    # A candidate already judged small/off-niche within 30 days never burns
    # another profile visit.
    if _quality_reject_recent(h):
        return Verdict(Refusal.QUALITY_REJECTED, "rejected by the quality gate within 30 days")
    return ADMITTED


# --- on the open profile: the quality gate ---------------------------------
# Operator 2026-06-12: "the accounts you follow are trash, very small
# accounts... not related to AI or investment or crypto — fix your
# algorithm". The gate rides the profile visit follow_account already
# makes: scrape followers + bio from the loaded page, refuse before
# clicking. Whitelisted seeds are exempt; rejects are cached 30 days so a
# bad candidate never burns a second profile visit.

_NICHE_BIO_RE = re.compile(
    r"\b(ai|a\.i\.|artificial intelligence|machine learning|\bml\b|llm|gpt|agent|"
    r"crypto|bitcoin|btc|eth|web3|defi|blockchain|token|"
    r"invest|investor|investing|trader|trading|markets?|stocks?|equit|finance|"
    r"financial|fintech|macro|quant|hedge|portfolio|capital|wealth|analyst|"
    r"founder|builder|startup|venture|\bvc\b|tech|software|engineer|nvidia|"
    r"bourse|économie|economy)\b",
    re.IGNORECASE,
)


def _parse_follower_count(text: str) -> int:
    """'12.3K' → 12300, '1,423' → 1423, '2.1M' → 2100000, junk → -1."""
    t = (text or "").strip().replace(",", "").replace(" ", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMm])?$", t)
    if not m:
        return -1
    try:
        n = float(m.group(1))
    except ValueError:
        return -1
    suffix = (m.group(2) or "").lower()
    return int(n * (1_000_000 if suffix == "m" else 1_000 if suffix == "k" else 1))


# Operator 2026-07-19: "follow US / english accounts not foreigner langage
# follows". Non-Latin scripts (CJK, Cyrillic, Arabic, Hangul, Thai, Hebrew,
# Devanagari) — accented Latin (José, Müller) intentionally NOT matched.
_NON_LATIN_SCRIPT_RE = re.compile(
    "["
    "Ѐ-ӿ"   # Cyrillic
    "֐-׿"   # Hebrew
    "؀-ۿ"   # Arabic
    "ऀ-ॿ"   # Devanagari
    "฀-๿"   # Thai
    "぀-ヿ"   # Hiragana + Katakana
    "㄰-㆏"   # Hangul compat jamo
    "一-鿿"   # CJK unified
    "가-힯"   # Hangul syllables
    "]"
)
# Common function words of major Latin-script languages that are rare in
# English bios. ≥3 hits = the bio is written in that language, not just
# quoting a name. Kept short on purpose — precision over recall.
_NON_EN_WORDS_RE = re.compile(
    r"\b(les|des|une|avec|pour|dans|vous|nous|los|las|para|desde|und|der|"
    r"nicht|für|gli|sono|anche|não|você|uma|bir|için|"
    r"değil|yang|dan|untuk)\b",
    re.IGNORECASE,
)


def _looks_non_english_profile(name: str, bio: str) -> str:
    """Return a reject reason if the profile reads non-English, else ''."""
    blob = f"{name or ''} {bio or ''}"
    if len(_NON_LATIN_SCRIPT_RE.findall(blob)) >= 3:
        return "non-English profile (non-Latin script)"
    if len(_NON_EN_WORDS_RE.findall(blob)) >= 3:
        return "non-English profile (foreign-language bio)"
    return ""


def _quality_decision(followers: int, bio: str, name: str,
                      whitelisted: bool, engager: bool = False) -> tuple:
    """Pure gate logic → (ok, reason). Env read at call time.

    `engager=True` (2026-07-19 follow-your-engagers lane): the candidate
    already replied to/engaged US, which is the highest follow-back-
    probability signal there is AND proves the niche by behavior — so the
    min-followers and bio-niche gates are skipped. The English gate,
    blocklist, caps, spacing and churn cooldown still apply."""
    if whitelisted:
        return (True, "whitelisted seed (gate exempt)")
    min_followers = int(os.environ.get("FOLLOW_MIN_FOLLOWERS", "2000"))
    if not engager:
        if followers < 0:
            return (False, "followers count unreadable — won't follow blind")
        if followers < min_followers:
            return (False, f"too small ({followers} followers < {min_followers})")
    if os.environ.get("FOLLOW_REQUIRE_ENGLISH", "1") == "1":
        why = _looks_non_english_profile(name, bio)
        if why:
            return (False, why)
    if not engager and os.environ.get("FOLLOW_REQUIRE_NICHE", "1") == "1":
        blob = f"{name or ''} {bio or ''}"
        if not _NICHE_BIO_RE.search(blob):
            return (False, "off-niche bio (no AI/markets/crypto signal)")
    return (True, "")


def _quality_reject_recent(handle: str, days: int = 30) -> bool:
    ts = QUALITY_REJECTS.read().get((handle or "").lower(), "")
    try:
        return bool(ts) and (datetime.now() - datetime.fromisoformat(ts)).days < days
    except (TypeError, ValueError):
        return False


def _record_quality_reject(handle: str) -> None:
    QUALITY_REJECTS.update(
        lambda doc: {**doc, (handle or "").lower(): datetime.now().isoformat()})


def judge_profile(handle: str, read_profile: Callable[[], dict], *,
                  engager: bool = False) -> Verdict:
    """The quality gate on the open profile. `read_profile` returns its
    followers, bio and name; it runs only once the whitelist is read. A
    rejected handle is cached for 30 days, where `judge` finds it."""
    try:
        whitelisted = is_whitelisted(handle)
    except StateUnreadable as exc:
        return Verdict(Refusal.POLICY, f"whitelist unreadable ({exc})")
    profile = read_profile()
    ok, why = _quality_decision(
        _parse_follower_count(profile.get("followers", "")),
        profile.get("bio", ""), profile.get("name", ""),
        whitelisted=whitelisted, engager=engager)
    if not ok:
        _record_quality_reject(handle)
        return Verdict(Refusal.QUALITY_REJECTED, why)
    return ADMITTED
