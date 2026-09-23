#!/usr/bin/env bash
#
# Generate, and later re-sync, the two deploy repositories from this one.
#
# This repository stays the source of truth. web/ and api/ are edited here, and
# this script rewrites each of those directories into a repository of its own
# where the directory's contents sit at the root, keeping the commits that
# touched it. Run it again after any change to web/ or api/ and the new commits
# are carried across; nothing is rewritten and nothing outside the prefix moves.
#
#   ./scripts/split-repos.sh                 both, from the current branch
#   ./scripts/split-repos.sh web             one of them
#   ./scripts/split-repos.sh --branch master both, from a named branch
#   ./scripts/split-repos.sh --dest ~/src    somewhere other than the parent dir
#
# The direction is one way. A commit made directly in a deploy repository is not
# carried back here, and the next sync will merge over it rather than take it.
# docs/repos.md section 3 has the procedure if that ever has to be undone.

set -euo pipefail

MONO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$(dirname "$MONO")"
BRANCH=""
PREFIXES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --dest)   DEST="$2";   shift 2 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    web|api)  PREFIXES+=("$1"); shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ ${#PREFIXES[@]} -eq 0 ]] && PREFIXES=(web api)
[[ -z "$BRANCH" ]] && BRANCH="$(git -C "$MONO" rev-parse --abbrev-ref HEAD)"

# A split of a dirty tree would silently omit whatever is not committed, and the
# deploy repository would then be a state that exists nowhere in this history.
if [[ -n "$(git -C "$MONO" status --porcelain)" ]]; then
  echo "the monorepo has uncommitted changes; commit or stash them first" >&2
  exit 1
fi

for prefix in "${PREFIXES[@]}"; do
  target="$DEST/ClearSkies-$prefix"
  split_branch="split/$prefix"

  echo "==> splitting $prefix from $BRANCH"
  # Deterministic: re-running over the same history produces the same commit
  # ids, which is what lets the merge below be an ordinary fast-forward rather
  # than a replay of unrelated histories.
  git -C "$MONO" subtree split -q --prefix="$prefix" --branch="$split_branch" "$BRANCH" >/dev/null
  head="$(git -C "$MONO" rev-parse "$split_branch")"

  if [[ ! -d "$target/.git" ]]; then
    echo "==> creating $target"
    git init -q -b master "$target"
    git -C "$target" remote add mono "$MONO"
    git -C "$target" fetch -q mono "$split_branch"
    git -C "$target" reset -q --hard "$head"
    echo "    created at $head"
    continue
  fi

  echo "==> syncing $target"
  if [[ -n "$(git -C "$target" status --porcelain)" ]]; then
    echo "    skipped: $target has uncommitted changes" >&2
    continue
  fi
  git -C "$target" remote get-url mono >/dev/null 2>&1 || git -C "$target" remote add mono "$MONO"
  git -C "$target" fetch -q mono "$split_branch"
  if git -C "$target" merge-base --is-ancestor "$head" HEAD; then
    echo "    already up to date"
  else
    # --no-ff keeps the sync visible as one commit saying what it brought over,
    # rather than fast-forwarding past the deploy repository's own root files.
    git -C "$target" merge --no-ff --no-edit -m "sync: $prefix from the monorepo ($BRANCH)" "$head"
    echo "    merged $head"
  fi
done

cat <<'NOTE'

Done. Neither repository has a remote other than `mono`, which points at this
working copy on disk. To publish one:

  gh repo create Vele189/ClearSkies-web --private --source=../ClearSkies-web --push
  gh repo create Vele189/ClearSkies-api --private --source=../ClearSkies-api --push

or, without gh, create the repository in the web interface and

  git -C ../ClearSkies-web remote add origin git@github.com:Vele189/ClearSkies-web.git
  git -C ../ClearSkies-web push -u origin master
NOTE
