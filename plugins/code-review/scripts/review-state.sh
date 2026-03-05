#!/usr/bin/env bash
# review-state.sh - State file operations for code review
# Usage:
#   review-state.sh read [jq-field]         # Read state (or specific field)
#   review-state.sh write '<json>'          # Initialize state file (full JSON)
#   review-state.sh update '<jq-expr>'      # Update state atomically
#   review-state.sh exists                  # Check if state file exists (exit 0/1)
#   review-state.sh delete                  # Remove state file
#
# State file: .git/code-review-state.json

set -euo pipefail

GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)" || {
    echo "ERROR: Not a git repository" >&2
    exit 1
}

STATE_FILE="$GIT_DIR/code-review-state.json"
ACTION="${1:?ERROR: No action specified. Use: read|write|update|exists|delete}"
shift || true

case "$ACTION" in
    read)
        if [ ! -f "$STATE_FILE" ]; then
            echo "ERROR: No review state file found at $STATE_FILE" >&2
            exit 1
        fi
        if ! jq empty "$STATE_FILE" 2>/dev/null; then
            echo "ERROR: State file is corrupted (invalid JSON)" >&2
            exit 2
        fi
        if [ $# -eq 0 ]; then
            jq '.' "$STATE_FILE"
        else
            jq -r "$1" "$STATE_FILE"
        fi
        ;;
    write)
        JSON="${1:?ERROR: No JSON content provided}"
        # Validate JSON
        if ! echo "$JSON" | jq empty 2>/dev/null; then
            echo "ERROR: Invalid JSON provided" >&2
            exit 2
        fi
        echo "$JSON" | jq '.' > "$STATE_FILE"
        echo "State file written: $STATE_FILE" >&2
        ;;
    update)
        if [ ! -f "$STATE_FILE" ]; then
            echo "ERROR: No review state file found" >&2
            exit 1
        fi
        if ! jq empty "$STATE_FILE" 2>/dev/null; then
            echo "ERROR: State file is corrupted" >&2
            exit 2
        fi
        JQ_EXPR="${1:?ERROR: No jq expression provided}"
        TMP_FILE="$STATE_FILE.tmp.$$"
        if ! jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            "(.updated_at = \$now) | $JQ_EXPR" "$STATE_FILE" > "$TMP_FILE" 2>/dev/null; then
            rm -f "$TMP_FILE"
            echo "ERROR: jq expression failed: $JQ_EXPR" >&2
            exit 3
        fi
        if ! jq empty "$TMP_FILE" 2>/dev/null; then
            rm -f "$TMP_FILE"
            echo "ERROR: jq expression produced invalid JSON" >&2
            exit 4
        fi
        mv "$TMP_FILE" "$STATE_FILE"
        ;;
    exists)
        [ -f "$STATE_FILE" ] && exit 0 || exit 1
        ;;
    delete)
        rm -f "$STATE_FILE"
        echo "State file removed" >&2
        ;;
    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        echo "Usage: review-state.sh [read|write|update|exists|delete] [args...]" >&2
        exit 1
        ;;
esac
