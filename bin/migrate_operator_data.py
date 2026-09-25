#!/usr/bin/env python3
"""Split the Operator's files from the bot's state (issue #206), once, with
the bot stopped: the whole procedure is in
docs/OPERATIONS.md#deploying-issue-206.

    python3 bin/migrate_operator_data.py --from <backup-dir>

<backup-dir> holds the old whitelist.json and respect_list.json, saved by
bin/carry_state.sh before the pull moved them to accounts/<BOT_ACCOUNT>/.
The script first checks, and writes nothing if a check fails:

  - the old whitelist, outside its discovered tier, equals the Account's
    whitelist.json, and the old respect list equals the Account's
    respect_list.json;
  - the baseline, as_of and note still in following_count.json equal the
    Account's following_baseline.json.

Then it creates whitelist_discovered.json when missing, even empty, adds the
old discovered tier to it, keeping the handles already there, and drops
baseline, as_of and note from following_count.json, keeping count and
updated. It never writes an Operator file, refuses to start while bot.lock
is held or a state file waits at the project root for bin/migrate_state.py
(issue #207), and a second run changes nothing.
"""
import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.core import state_store  # noqa: E402
from src.core.account import OperatorFile  # noqa: E402
from src.core.state_errors import StateUnreadable  # noqa: E402
from src.guards import follow_policy, respect_list  # noqa: E402

BASELINE = OperatorFile("following_baseline.json", dict)
BASELINE_KEYS = ("baseline", "as_of", "note")


class Refused(Exception):
    """A check failed: nothing was written."""


def _old(folder: str, name: str):
    """The old root file saved in `folder`, None when it is not there."""
    path = os.path.join(folder, name)
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise Refused(f"{path} is unreadable ({exc})") from None
    if not isinstance(value, dict):
        raise Refused(f"{path}: top-level {type(value).__name__}, expected an object")
    return value


def _same_as_operator(folder: str, name: str, old, operator: OperatorFile) -> None:
    if old != operator.read():
        raise Refused(f"{os.path.join(folder, name)} differs from {operator.path}: carry the "
                      f"Operator's edits to the Account's file and commit them, then run again")


def migrate(folder: str) -> list:
    """Check, then carry the values. Returns the report lines; raises
    Refused, with nothing written, when a check fails."""
    try:
        return _migrate(folder)
    except StateUnreadable as exc:
        raise Refused(str(exc)) from None


def _migrate(folder: str) -> list:
    report = []
    old_whitelist = _old(folder, "whitelist.json")
    if old_whitelist is None:
        if not os.path.exists(follow_policy.DISCOVERED.path):
            raise Refused(f"no whitelist.json in {folder} and no {follow_policy.DISCOVERED.name} "
                          f"yet: pass the directory bin/carry_state.sh saved it to")
        carried = []
        report.append(f"whitelist.json: none in {folder}, nothing to carry")
    else:
        operator_part = copy.deepcopy(old_whitelist)
        carried = list((operator_part.get("tiers") or {}).pop("discovered", None) or [])
        _same_as_operator(folder, "whitelist.json", operator_part, follow_policy.WHITELIST)

    old_respect = _old(folder, "respect_list.json")
    if old_respect is not None:
        _same_as_operator(folder, "respect_list.json", old_respect, respect_list.RESPECT)
        report.append(f"respect_list.json: identical to {respect_list.RESPECT.path}")

    count_doc = follow_policy.FOLLOWING_COUNT.read()
    stale = {k: count_doc[k] for k in BASELINE_KEYS if k in count_doc}
    if stale:
        baseline = BASELINE.read()
        differ = sorted(k for k, v in stale.items() if baseline.get(k) != v)
        if differ:
            raise Refused(f"{follow_policy.FOLLOWING_COUNT.name}: {', '.join(differ)} differ from "
                          f"{BASELINE.path}: carry them there and commit them, then run again")

    if old_whitelist is not None:
        # Written even when the old tier is empty: the follow policy refuses
        # while it is missing, and a later run without the backup knows the
        # carry is done.
        if not os.path.exists(follow_policy.DISCOVERED.path):
            follow_policy.DISCOVERED.write([])
        added = follow_policy.add_discovered(carried)
        report.append(f"{follow_policy.DISCOVERED.name}: {len(follow_policy.DISCOVERED.read())} "
                      f"handles, {len(added)} added from {len(carried)} in the old discovered tier")

    count = count_doc.get("count")
    if stale:
        follow_policy.FOLLOWING_COUNT.update(
            lambda doc: {k: v for k, v in doc.items() if k not in BASELINE_KEYS})
        report.append(f"{follow_policy.FOLLOWING_COUNT.name}: count {count} kept, "
                      f"{', '.join(stale)} left to {BASELINE.name}")
    else:
        report.append(f"{follow_policy.FOLLOWING_COUNT.name}: count {count}, nothing to drop")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="folder", required=True,
                        help="directory holding the old whitelist.json and respect_list.json")
    args = parser.parse_args()
    if state_store.bot_holds_lock(ROOT):
        print("bot.lock is held: stop the bot and its supervisor first", file=sys.stderr)
        sys.exit(1)
    try:
        state_store.require_migrated()
    except state_store.Unmigrated as exc:
        print(f"REFUSED, nothing written: {exc}", file=sys.stderr)
        sys.exit(1)
    state_store.ensure_root()
    try:
        report = migrate(args.folder)
    except Refused as exc:
        print(f"REFUSED, nothing written: {exc}", file=sys.stderr)
        sys.exit(1)
    for line in report:
        print(line)


if __name__ == "__main__":
    main()
