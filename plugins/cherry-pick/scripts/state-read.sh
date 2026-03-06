#!/usr/bin/env bash
# state-read.sh - Safe state file reader for batch cherry-pick
# Usage: state-read.sh [jq-field]
# Examples:
#   state-read.sh                    # Print entire state
#   state-read.sh '.current_index'   # Print specific field
#   state-read.sh '.commits[0]'      # Print first commit

set -euo pipefail

STATE_FILE="$(git rev-parse --git-dir 2>/dev/null)/cherry-pick-batch.json"

if [ ! -f "$STATE_FILE" ]; then
    echo "ERROR: No batch cherry-pick state file found at $STATE_FILE" >&2
    echo "Run /cherry-pick:batch first to create a plan." >&2
    exit 1
fi

if ! jq empty "$STATE_FILE" 2>/dev/null; then
    echo "ERROR: State file is corrupted (invalid JSON): $STATE_FILE" >&2
    exit 2
fi

if [ $# -eq 0 ]; then
    jq '.' "$STATE_FILE"
else
    jq -r "$1" "$STATE_FILE"
fi
