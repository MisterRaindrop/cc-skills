#!/usr/bin/env bash
# collect-diff.sh - Collect diff for code review
# Usage:
#   collect-diff.sh staged              # Staged changes (default)
#   collect-diff.sh commit <hash>       # Specific commit(s)
#   collect-diff.sh branch <branch>     # Branch diff vs current
#   collect-diff.sh unstaged            # All uncommitted changes
#
# Output: diff content to stdout, metadata to stderr

set -euo pipefail

MODE="${1:-staged}"
shift || true

# Verify we're in a git repo
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)" || {
    echo "ERROR: Not a git repository" >&2
    exit 1
}

case "$MODE" in
    staged)
        DIFF=$(git diff --cached)
        if [ -z "$DIFF" ]; then
            # Fall back to unstaged changes
            DIFF=$(git diff)
            if [ -z "$DIFF" ]; then
                # Fall back to last commit
                DIFF=$(git diff HEAD~1..HEAD 2>/dev/null || echo "")
                if [ -z "$DIFF" ]; then
                    echo "ERROR: No changes found (staged, unstaged, or last commit)" >&2
                    exit 1
                fi
                echo "MODE: last-commit" >&2
            else
                echo "MODE: unstaged" >&2
            fi
        else
            echo "MODE: staged" >&2
        fi
        ;;
    commit)
        if [ $# -eq 0 ]; then
            echo "ERROR: No commit hash provided" >&2
            exit 1
        fi
        DIFF=""
        for HASH in "$@"; do
            # Validate commit exists
            if ! git cat-file -t "$HASH" &>/dev/null; then
                echo "ERROR: Commit not found: $HASH" >&2
                exit 1
            fi
            COMMIT_DIFF=$(git show "$HASH" --format="" --patch)
            DIFF="${DIFF}${COMMIT_DIFF}"$'\n'
        done
        echo "MODE: commit" >&2
        echo "COMMITS: $*" >&2
        ;;
    branch)
        BRANCH="${1:?ERROR: No branch name provided}"
        # Find merge base
        MERGE_BASE=$(git merge-base HEAD "$BRANCH" 2>/dev/null) || {
            echo "ERROR: Cannot find merge base between HEAD and $BRANCH" >&2
            exit 1
        }
        DIFF=$(git diff "$MERGE_BASE"..HEAD)
        if [ -z "$DIFF" ]; then
            echo "ERROR: No diff between current branch and $BRANCH" >&2
            exit 1
        fi
        echo "MODE: branch" >&2
        echo "BASE: $BRANCH" >&2
        echo "MERGE_BASE: $MERGE_BASE" >&2
        ;;
    unstaged)
        DIFF=$(git diff)
        if [ -z "$DIFF" ]; then
            echo "ERROR: No unstaged changes found" >&2
            exit 1
        fi
        echo "MODE: unstaged" >&2
        ;;
    *)
        echo "ERROR: Unknown mode: $MODE" >&2
        echo "Usage: collect-diff.sh [staged|commit|branch|unstaged] [args...]" >&2
        exit 1
        ;;
esac

# Output stats to stderr
FILE_COUNT=$(echo "$DIFF" | grep -c '^diff --git' || true)
ADD_COUNT=$(echo "$DIFF" | grep -c '^+[^+]' || true)
DEL_COUNT=$(echo "$DIFF" | grep -c '^-[^-]' || true)
echo "FILES: $FILE_COUNT" >&2
echo "ADDITIONS: $ADD_COUNT" >&2
echo "DELETIONS: $DEL_COUNT" >&2

# Output diff to stdout
echo "$DIFF"
