#!/usr/bin/env bash
# detect-codex.sh - Detect codex CLI availability and version
# Usage: detect-codex.sh
# Exit 0 + prints version if available, exit 1 if not found

set -euo pipefail

if ! command -v codex &>/dev/null; then
    echo "NOT_FOUND" >&2
    exit 1
fi

VERSION=$(codex --version 2>/dev/null || echo "unknown")
echo "$VERSION"
exit 0
