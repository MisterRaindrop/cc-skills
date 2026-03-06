#!/usr/bin/env bash
# detect-already-applied.sh - Check if a commit is already cherry-picked
# Usage: detect-already-applied.sh <commit-hash> [target-branch]
# Exit codes:
#   0 = already applied
#   1 = not yet applied
#   2 = error
#
# Uses two methods:
#   1. Search for "cherry picked from commit <hash>" trailer in log
#   2. Patch-id comparison (catches cherry-picks without -x flag)

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "ERROR: Missing commit hash argument." >&2
    echo "Usage: detect-already-applied.sh <commit-hash> [target-branch]" >&2
    exit 2
fi

COMMIT_HASH="$1"
TARGET_BRANCH="${2:-HEAD}"

# Resolve to full hash
FULL_HASH=$(git rev-parse "$COMMIT_HASH" 2>/dev/null) || {
    echo "ERROR: Cannot resolve commit: $COMMIT_HASH" >&2
    exit 2
}

# Method 1: Search for cherry-pick trailer
if git log "$TARGET_BRANCH" --grep="cherry picked from commit $FULL_HASH" --oneline 2>/dev/null | grep -q .; then
    echo "ALREADY_APPLIED: Found cherry-pick trailer referencing $FULL_HASH"
    exit 0
fi

# Also check short hash in trailer (some tools use short hash)
SHORT_HASH="${FULL_HASH:0:7}"
if git log "$TARGET_BRANCH" --grep="cherry picked from commit ${SHORT_HASH}" --oneline 2>/dev/null | grep -q .; then
    echo "ALREADY_APPLIED: Found cherry-pick trailer referencing short hash $SHORT_HASH"
    exit 0
fi

# Method 2: Patch-id comparison
SOURCE_PATCH_ID=$(git show "$FULL_HASH" 2>/dev/null | git patch-id --stable 2>/dev/null | awk '{print $1}') || {
    echo "NOT_APPLIED: Could not compute patch-id (possibly a merge commit)"
    exit 1
}

if [ -z "$SOURCE_PATCH_ID" ]; then
    echo "NOT_APPLIED: Empty patch-id (possibly an empty or merge commit)"
    exit 1
fi

# Compare patch-id against all commits on target branch
# Limit search to last 500 commits for performance
while IFS= read -r line; do
    TARGET_PATCH_ID=$(echo "$line" | git patch-id --stable 2>/dev/null | awk '{print $1}') || continue
    if [ "$SOURCE_PATCH_ID" = "$TARGET_PATCH_ID" ]; then
        MATCH_HASH=$(echo "$line" | git patch-id --stable 2>/dev/null | awk '{print $2}')
        echo "ALREADY_APPLIED: Matching patch-id found in commit $MATCH_HASH"
        exit 0
    fi
done < <(git log "$TARGET_BRANCH" -500 --format="%H" 2>/dev/null | while read -r h; do git show "$h" 2>/dev/null; echo "---END-OF-COMMIT---"; done)

echo "NOT_APPLIED"
exit 1
