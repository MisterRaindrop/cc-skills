#!/usr/bin/env bash
# state-update.sh - Atomic state file updater for batch cherry-pick
# Usage: state-update.sh '<jq-expression>'
# Examples:
#   state-update.sh '.current_index = 3'
#   state-update.sh '.commits[0].status = "completed"'
#   state-update.sh '.stats.completed += 1'
#
# Uses tmp+mv pattern for atomic writes to prevent corruption.

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "ERROR: No jq expression provided." >&2
    echo "Usage: state-update.sh '<jq-expression>'" >&2
    exit 1
fi

GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)"
STATE_FILE="$GIT_DIR/cherry-pick-batch.json"

if [ ! -f "$STATE_FILE" ]; then
    echo "ERROR: No batch cherry-pick state file found at $STATE_FILE" >&2
    exit 1
fi

if ! jq empty "$STATE_FILE" 2>/dev/null; then
    echo "ERROR: State file is corrupted (invalid JSON): $STATE_FILE" >&2
    exit 2
fi

JQ_EXPR="$1"
TMP_FILE="$STATE_FILE.tmp.$$"

# Update the timestamp and apply the expression atomically
if ! jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "(.updated_at = \$now) | $JQ_EXPR" "$STATE_FILE" > "$TMP_FILE" 2>/dev/null; then
    rm -f "$TMP_FILE"
    echo "ERROR: jq expression failed: $JQ_EXPR" >&2
    exit 3
fi

# Validate the result is valid JSON
if ! jq empty "$TMP_FILE" 2>/dev/null; then
    rm -f "$TMP_FILE"
    echo "ERROR: jq expression produced invalid JSON" >&2
    exit 4
fi

# Atomic move
mv "$TMP_FILE" "$STATE_FILE"
