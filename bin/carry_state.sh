#!/bin/bash
# Carry the live state across a pull that takes state files out of git
# (issue #193). Run it from the checkout, with the bot stopped: the whole
# procedure is in docs/OPERATIONS.md#deploying-issue-193. It works on the
# checkout it runs in, so a copy taken with `git show` serves before the pull.
# Both commands refuse to start while bot.lock is held or a main.py runs
# from this checkout.
#
# Since issue #207 the state lives under state/<BOT_ACCOUNT>/, which git
# ignores as a whole, so no pull deletes it. The script still works on the
# root only: `restore` puts the files back there, for bin/migrate_state.py
# to move (docs/OPERATIONS.md#deploying-issue-207).
#
#   bin/carry_state.sh save [--force] <backup-dir> <ref>
#       Copies every root file that moving from HEAD to <ref> deletes and
#       that exists here, with its SHA-256 in <backup-dir>/SHA256SUMS.
#       Refuses a non-empty <backup-dir>, and an action_ledger.json equal to
#       its committed copy: the live ledger always has rows the commit lacks,
#       so an equal one means `git checkout HEAD --` already ran and the live
#       copies are gone. --force skips that ledger check, for a checkout the
#       bot never ran in.
#   bin/carry_state.sh restore <backup-dir>
#       Refuses while a saved file is still tracked: the pull is not done.
#       Otherwise puts back the saved files git now ignores, then checks each
#       one against SHA256SUMS. A saved file git neither tracks nor ignores
#       is an orphan the pull deleted on purpose: it stays in the backup only.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

usage() {
    echo "usage: $0 save [--force] <backup-dir> <ref> | restore <backup-dir>" >&2
    exit 2
}

refuse_if_bot_runs() {
    local held=0 here pid
    if [ -f bot.lock ]; then
        # Same lock as main.py: flock on bot.lock, released when python exits.
        python3 - bot.lock <<'EOF' || held=$?
import fcntl, sys
with open(sys.argv[1]) as handle:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(3)
EOF
        case "$held" in
            0) ;;
            3) echo "bot.lock is held: stop the bot and its supervisor first" >&2; exit 1 ;;
            *) echo "could not test bot.lock with python3" >&2; exit 1 ;;
        esac
    fi
    here="$(pwd -P)"
    for pid in $(pgrep -if 'python.*main\.py' || true); do
        if [ "$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$here" ]; then
            echo "a main.py runs from this checkout (PID $pid): stop the bot and its supervisor first" >&2
            exit 1
        fi
    done
}

save() {
    local force="$1" dir="$2" ref="$3"
    git rev-parse --verify -q "$ref^{commit}" >/dev/null || { echo "unknown ref: $ref" >&2; exit 1; }
    if [ -e "$dir" ] && [ -n "$(ls -A "$dir")" ]; then
        echo "$dir is not empty: a backup is already there, restore from it instead of saving again" >&2
        exit 1
    fi
    if [ -z "$force" ] && git cat-file -e HEAD:action_ledger.json 2>/dev/null \
        && [ -f action_ledger.json ] && git diff --quiet HEAD -- action_ledger.json; then
        echo "action_ledger.json equals its committed copy: the live state is already gone" \
            "(git checkout HEAD -- ran before save?). Recover it from an existing backup;" \
            "--force only for a checkout the bot never ran in" >&2
        exit 1
    fi
    mkdir -p "$dir"
    local names=()
    while IFS= read -r name; do
        case "$name" in */*) continue ;; esac
        [ -f "$name" ] && names+=("$name")
    done < <(git diff --name-only --no-renames --diff-filter=D HEAD "$ref")
    if [ ${#names[@]} -eq 0 ]; then
        echo "moving to $ref deletes no root file here: nothing to save"
        return
    fi
    cp -p "${names[@]}" "$dir/"
    shasum -a 256 "${names[@]}" > "$dir/SHA256SUMS"
    (cd "$dir" && shasum -a 256 -c --quiet SHA256SUMS)
    echo "saved ${#names[@]} files to $dir:"
    printf '  %s\n' "${names[@]}"
}

restore() {
    local dir="$1"
    [ -f "$dir/SHA256SUMS" ] || { echo "$dir/SHA256SUMS is missing" >&2; exit 1; }
    local restored=() tracked=() checked="" sum name
    while read -r sum name; do
        git ls-files --error-unmatch -- "$name" >/dev/null 2>&1 && tracked+=("$name")
    done < "$dir/SHA256SUMS"
    if [ ${#tracked[@]} -gt 0 ]; then
        echo "pull not done: git still tracks ${#tracked[@]} saved files (${tracked[*]})." \
            "Pull first, then restore; nothing was copied" >&2
        exit 1
    fi
    while read -r sum name; do
        if ! git check-ignore -q -- "$name"; then
            echo "left out: $name (git neither tracks nor ignores it)"
            continue
        fi
        if [ -e "$name" ]; then
            if ! cmp -s "$name" "$dir/$name"; then
                echo "$name exists and differs from the backup: nothing overwritten, compare by hand" >&2
                exit 1
            fi
        else
            cp -p "$dir/$name" "$name"
            restored+=("$name")
        fi
        checked+="$sum  $name"$'\n'
    done < "$dir/SHA256SUMS"
    [ -n "$checked" ] || { echo "nothing to restore"; return; }
    printf '%s' "$checked" | shasum -a 256 -c --quiet
    echo "restored ${#restored[@]} files; $(printf '%s' "$checked" | wc -l | tr -d ' ') match the backup"
    if [ ${#restored[@]} -gt 0 ] && [ -f bin/migrate_state.py ]; then
        echo "they are at the root: move them to state/ with bin/migrate_state.py before starting the bot"
    fi
}

command="${1:-}"
[ $# -gt 0 ] && shift
force=""
if [ "$command" = save ] && [ "${1:-}" = --force ]; then
    force=1
    shift
fi

case "${1:-}" in
    /*) ;;
    *) echo "the backup directory must be an absolute path, outside the checkout" >&2; usage ;;
esac

case "$command" in
    save) [ $# -eq 2 ] || usage; refuse_if_bot_runs; save "$force" "$1" "$2" ;;
    restore) [ $# -eq 1 ] || usage; refuse_if_bot_runs; restore "$1" ;;
    *) usage ;;
esac
