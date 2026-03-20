#!/usr/bin/env bash
# detect-pxf-repo.sh - Find the cloudberry-pxf repo root
# Searches CWD parents and common locations, verifies Makefile + ci/ exist.
# Exit 0 + prints repo path if found, exit 1 if not found.

set -euo pipefail

check_dir() {
    if [ -d "$1/ci/docker/pxf-cbdb-dev" ] && [ -f "$1/Makefile" ]; then
        echo "$1"
        return 0
    fi
    return 1
}

# If PXF_REPO is set, use it directly
if [ -n "${PXF_REPO:-}" ] && check_dir "${PXF_REPO}"; then
    exit 0
fi

# Walk up from CWD
dir="$(pwd)"
while [ "$dir" != "/" ]; do
    if check_dir "$dir"; then
        exit 0
    fi
    dir="$(dirname "$dir")"
done

# Strategy 2: check common locations
for candidate in \
    "$HOME/workspace/cloudberry-pxf" \
    "$HOME/github/cloudberry-pxf" \
    "/workspace/cloudberry-pxf" \
    "/home/gpadmin/workspace/cloudberry-pxf"; do
    if [ -d "$candidate" ] && check_dir "$candidate"; then
        exit 0
    fi
done

echo "NOT_FOUND" >&2
exit 1
