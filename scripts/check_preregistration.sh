#!/usr/bin/env bash
# Enforces docs/methodology.md section 13.1.
#
# The validation set must be committed BEFORE any scoring code exists, so that
# validation targets cannot be reverse-engineered from the score. This check is
# crude and defeatable by anyone determined to defeat it. Its job is to make
# casual post-hoc tuning impossible and deliberate tuning visible in git history.
#
# Requires full history: actions/checkout with fetch-depth: 0.

set -euo pipefail

SITES="docs/validation/sites.yml"
SCORING="scoring/"

first_commit_adding() {
    # Deliberately not `git log ... | head -1`. Once head has the line it wants
    # it closes the pipe, git takes SIGPIPE, and `set -o pipefail` above turns
    # that into exit 141 and a red build. That stayed invisible for as long as
    # only one commit had ever added a file under the path, since git then had
    # nothing left to write: the first follow-up commit under scoring/ was
    # always going to be the one that broke it. Reading the whole list and
    # taking its first line has no pipe to break.
    local commits
    commits="$(git log --diff-filter=A --format=%H --reverse -- "$1")"
    printf '%s\n' "${commits%%$'\n'*}"
}

scoring_commit="$(first_commit_adding "$SCORING")"

if [[ -z "$scoring_commit" ]]; then
    echo "ok: no scoring code yet, nothing to check"
    exit 0
fi

sites_commit="$(first_commit_adding "$SITES")"

if [[ -z "$sites_commit" ]]; then
    echo "FAIL: $SCORING exists but $SITES was never committed."
    echo "The validation set must be pre-registered before scoring code."
    exit 1
fi

if [[ "$sites_commit" == "$scoring_commit" ]]; then
    echo "FAIL: $SITES and $SCORING were added in the same commit ($sites_commit)."
    echo "Pre-registration means a separate, earlier commit."
    exit 1
fi

if ! git merge-base --is-ancestor "$sites_commit" "$scoring_commit"; then
    echo "FAIL: $SITES ($sites_commit) is not an ancestor of $SCORING ($scoring_commit)."
    echo "The validation set must be committed first."
    exit 1
fi

echo "ok: validation set pre-registered in $sites_commit, before scoring in $scoring_commit"
