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

# Ordering the first commits proves nothing on its own: the file could be added
# honestly and rewritten the day after the scores came in. So every commit that
# touches it and is not an ancestor of the first scoring commit must say why, in
# a `Methodology-Revision:` trailer, which is what section 13.1 means by
# deliberate tuning being visible in history. Merges are skipped, since each
# commit a merge brings in is listed on its own; --full-history keeps a change
# that was later reverted from hiding behind the revert.
#
# The trailer is read by git itself (%(trailers)), so it has to be a real
# trailer in the last paragraph of the message, not the phrase somewhere in the
# body. Captured whole rather than piped, for the same SIGPIPE reason as above.
revisions="$(git log --full-history --no-merges \
    --format='%H %(trailers:key=Methodology-Revision,valueonly,separator=%x20)' \
    HEAD --not "$scoring_commit"^@ -- "$SITES")"

unexplained=()
while read -r commit reason; do
    [[ -z "$commit" ]] && continue
    if [[ -z "$reason" ]]; then
        unexplained+=("$commit")
    fi
done <<< "$revisions"

if (( ${#unexplained[@]} > 0 )); then
    echo "FAIL: $SITES was changed after scoring existed, without a Methodology-Revision: trailer:"
    for commit in "${unexplained[@]}"; do
        echo "  $(git show -s --format='%h %s' "$commit")"
    done
    echo "A post-registration edit is a methodology revision and has to say so in its commit."
    exit 1
fi

if [[ -n "$revisions" ]]; then
    echo "ok: $SITES revised after scoring only in commits that declare it:"
    while read -r commit reason; do
        echo "  ${commit:0:7} Methodology-Revision: $reason"
    done <<< "$revisions"
else
    echo "ok: $SITES unchanged since scoring began in $scoring_commit"
fi
