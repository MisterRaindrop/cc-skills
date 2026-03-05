#!/usr/bin/env bash
# run-codex-review.sh - Invoke Codex CLI for Team Beta review
# Usage:
#   run-codex-review.sh staged <prompt-file>
#   run-codex-review.sh commit <hash> <prompt-file>
#   run-codex-review.sh branch <base-branch> <prompt-file>
#
# The prompt-file should contain the full review prompt (roles, instructions, diff).
# Output: Codex review result to stdout

set -euo pipefail

# Verify codex is available
if ! command -v codex &>/dev/null; then
    echo "ERROR: Codex CLI not found. Install with: npm i -g @openai/codex" >&2
    exit 1
fi

MODE="${1:?ERROR: No mode specified}"
shift

case "$MODE" in
    staged)
        PROMPT_FILE="${1:?ERROR: No prompt file provided}"
        if [ ! -f "$PROMPT_FILE" ]; then
            echo "ERROR: Prompt file not found: $PROMPT_FILE" >&2
            exit 1
        fi
        PROMPT=$(cat "$PROMPT_FILE")
        codex --quiet --approval-mode full-auto "$PROMPT"
        ;;
    commit)
        HASH="${1:?ERROR: No commit hash provided}"
        PROMPT_FILE="${2:?ERROR: No prompt file provided}"
        if [ ! -f "$PROMPT_FILE" ]; then
            echo "ERROR: Prompt file not found: $PROMPT_FILE" >&2
            exit 1
        fi
        PROMPT=$(cat "$PROMPT_FILE")
        codex --quiet --approval-mode full-auto "$PROMPT"
        ;;
    branch)
        BASE_BRANCH="${1:?ERROR: No base branch provided}"
        PROMPT_FILE="${2:?ERROR: No prompt file provided}"
        if [ ! -f "$PROMPT_FILE" ]; then
            echo "ERROR: Prompt file not found: $PROMPT_FILE" >&2
            exit 1
        fi
        PROMPT=$(cat "$PROMPT_FILE")
        codex --quiet --approval-mode full-auto "$PROMPT"
        ;;
    *)
        echo "ERROR: Unknown mode: $MODE" >&2
        echo "Usage: run-codex-review.sh [staged|commit|branch] [args...] <prompt-file>" >&2
        exit 1
        ;;
esac
