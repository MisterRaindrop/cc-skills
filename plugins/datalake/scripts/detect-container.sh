#!/usr/bin/env bash
# detect-container.sh - Detect lakehouse singlecluster container
# Usage: detect-container.sh
# Searches for running containers named "lakehouse"
# Exit 0 + prints container ID and name if found, exit 1 if not found

set -euo pipefail

if ! command -v docker &>/dev/null; then
    echo "ERROR: docker command not found" >&2
    exit 1
fi

# Search for running lakehouse container
CONTAINER_INFO=$(docker ps --filter "status=running" --format "{{.ID}} {{.Names}} {{.Image}}" 2>/dev/null | grep "lakehouse" || true)

if [ -z "$CONTAINER_INFO" ]; then
    echo "NOT_FOUND: No running lakehouse container detected" >&2
    exit 1
fi

# Extract container ID and name from the first matching container
CONTAINER_ID=$(echo "$CONTAINER_INFO" | head -1 | awk '{print $1}')
CONTAINER_NAME=$(echo "$CONTAINER_INFO" | head -1 | awk '{print $2}')
CONTAINER_IMAGE=$(echo "$CONTAINER_INFO" | head -1 | awk '{print $3}')

echo "CONTAINER_ID=$CONTAINER_ID"
echo "CONTAINER_NAME=$CONTAINER_NAME"
echo "CONTAINER_IMAGE=$CONTAINER_IMAGE"
exit 0
