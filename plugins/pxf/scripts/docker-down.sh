#!/bin/bash
set -euo pipefail

# Stop PXF development Docker environment
# Usage: docker-down.sh [--clean]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$("${SCRIPT_DIR}/detect-pxf-repo.sh")" || { echo "ERROR: cloudberry-pxf repo not found. cd into it or set PXF_REPO."; exit 1; }
COMPOSE_FILE="${REPO_DIR}/ci/docker/pxf-cbdb-dev/ubuntu/docker-compose.yml"

log() { echo "[docker-down][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Stop the PXF development Docker environment.

Options:
  --clean    Remove containers and volumes (docker compose down -v)
  --status   Show current container status and exit
  -h, --help Show this help

Default behavior: stop containers (preserves state for fast restart)
EOF
    exit 0
}

# Detect compose command
command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
command -v docker compose >/dev/null 2>&1 && COMPOSE_CMD="docker compose" || {
    command -v docker-compose >/dev/null 2>&1 && COMPOSE_CMD="docker-compose" || die "docker compose not found"
}

# Parse args
ACTION="stop"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean) ACTION="clean"; shift ;;
        --status)
            echo "=== Docker Compose Status ==="
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" ps
            exit 0
            ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

case "${ACTION}" in
    stop)
        log "Stopping containers (state preserved)..."
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" stop
        log "Containers stopped. Use 'docker-up.sh --skip-init' to restart quickly."
        ;;
    clean)
        log "Removing containers and volumes..."
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" down -v
        log "Containers and volumes removed. Next start will require full initialization."
        ;;
esac
