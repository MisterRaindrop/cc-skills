#!/usr/bin/env bash
# validate-no-conflicts.sh - Verify no conflict markers or unmerged files remain
# Usage: validate-no-conflicts.sh
# Exit codes:
#   0 = clean (no conflicts)
#   1 = conflicts remain
#   2 = error

set -euo pipefail

ERRORS=0

# Check 1: Unmerged files in index
UNMERGED=$(git diff --name-only --diff-filter=U 2>/dev/null)
if [ -n "$UNMERGED" ]; then
    echo "CONFLICT: Unmerged files found:" >&2
    echo "$UNMERGED" | while read -r f; do echo "  - $f" >&2; done
    ERRORS=$((ERRORS + 1))
fi

# Check 2: Conflict markers in staged files
STAGED=$(git diff --cached --name-only 2>/dev/null)
if [ -n "$STAGED" ]; then
    while IFS= read -r file; do
        if [ -f "$file" ] && grep -qnE '^(<{7}|={7}|>{7})' "$file" 2>/dev/null; then
            echo "CONFLICT: Conflict markers found in: $file" >&2
            grep -nE '^(<{7}|={7}|>{7})' "$file" | head -5 | while read -r line; do
                echo "  $line" >&2
            done
            ERRORS=$((ERRORS + 1))
        fi
    done <<< "$STAGED"
fi

# Check 3: Also check tracked modified files (not yet staged)
MODIFIED=$(git diff --name-only 2>/dev/null)
if [ -n "$MODIFIED" ]; then
    while IFS= read -r file; do
        if [ -f "$file" ] && grep -qnE '^(<{7}|={7}|>{7})' "$file" 2>/dev/null; then
            echo "CONFLICT: Conflict markers in unstaged file: $file" >&2
            ERRORS=$((ERRORS + 1))
        fi
    done <<< "$MODIFIED"
fi

# Check 4: git diff --check for whitespace issues and conflict markers
if ! git diff --check HEAD 2>/dev/null; then
    echo "WARNING: git diff --check found issues (may include whitespace)" >&2
    # Don't increment ERRORS for whitespace-only issues
fi

if [ "$ERRORS" -gt 0 ]; then
    echo "VALIDATION FAILED: $ERRORS conflict issue(s) found."
    exit 1
fi

echo "CLEAN: No conflicts detected."
exit 0
