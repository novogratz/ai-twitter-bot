#!/bin/bash
# Carry the live state across a pull that takes state files out of git
# (issue #193). Run it from the checkout, with the bot stopped: the whole
# procedure is in docs/OPERATIONS.md#deploying-issue-193. It works on the
# checkout it runs in, so a copy taken with `git show` serves before the pull.
#
#   bin/carry_state.sh save <backup-dir> <ref>
#       Copies every root file that moving from HEAD to <ref> deletes and
#       that exists here, with its SHA-256 in <backup-dir>/SHA256SUMS.
#   bin/carry_state.sh restore <backup-dir>
#       Puts back the saved files git now ignores, then checks each one
#       against SHA256SUMS. A saved file git does not ignore is an orphan
#       the pull deleted on purpose: it stays in the backup only.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

usage() {
    echo "usage: $0 save <backup-dir> <ref> | restore <backup-dir>" >&2
    exit 2
}

save() {
    local dir="$1" ref="$2"
    git rev-parse --verify -q "$ref^{commit}" >/dev/null || { echo "unknown ref: $ref" >&2; exit 1; }
    if [ -e "$dir" ] && [ -n "$(ls -A "$dir")" ]; then
        echo "$dir is not empty: choose a new backup directory" >&2
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
    local restored=() checked="" sum name
    while read -r sum name; do
        if ! git check-ignore -q -- "$name"; then
            echo "left out: $name (git does not ignore it)"
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
}

case "${2:-}" in
    /*) ;;
    *) echo "the backup directory must be an absolute path, outside the checkout" >&2; usage ;;
esac

case "${1:-}" in
    save) [ $# -eq 3 ] || usage; save "$2" "$3" ;;
    restore) [ $# -eq 2 ] || usage; restore "$2" ;;
    *) usage ;;
esac
