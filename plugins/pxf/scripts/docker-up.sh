#!/bin/bash
set -euo pipefail

# Start PXF development Docker environment
# Usage: docker-up.sh [--skip-init]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$("${SCRIPT_DIR}/detect-pxf-repo.sh")" || { echo "ERROR: cloudberry-pxf repo not found. cd into it or set PXF_REPO."; exit 1; }
COMPOSE_FILE="${REPO_DIR}/ci/docker/pxf-cbdb-dev/ubuntu/docker-compose.yml"
CONTAINER_NAME="pxf-cbdb-dev"
ENTRYPOINT_SCRIPT="/home/gpadmin/workspace/cloudberry-pxf/ci/docker/pxf-cbdb-dev/ubuntu/script/entrypoint.sh"

log() { echo "[docker-up][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Start the PXF development Docker environment.

Options:
  --skip-init   Skip entrypoint initialization (container already set up)
  -h, --help    Show this help

What it does:
  1. Builds and starts Docker containers (singlecluster + pxf-cbdb-dev)
  2. Runs entrypoint.sh inside the container to set up the full environment
     (Cloudberry, PXF, Hadoop, Hive, HBase, MinIO)
  3. Verifies PXF health endpoint
EOF
    exit 0
}

# Parse args
SKIP_INIT=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-init) SKIP_INIT=true; shift ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

# Check prerequisites
command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
command -v docker compose >/dev/null 2>&1 && COMPOSE_CMD="docker compose" || {
    command -v docker-compose >/dev/null 2>&1 && COMPOSE_CMD="docker-compose" || die "docker compose not found"
}

# Check if container is already running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "Container '${CONTAINER_NAME}' is already running"

    if [ "${SKIP_INIT}" = true ]; then
        log "Skipping init as requested"
        exit 0
    fi

    # Check if PXF is already healthy
    if docker exec "${CONTAINER_NAME}" curl -sf http://localhost:5888/actuator/health >/dev/null 2>&1; then
        log "PXF is already healthy - environment is ready"
        exit 0
    fi

    log "Container running but PXF not healthy, running entrypoint..."
    docker exec -u gpadmin "${CONTAINER_NAME}" bash -l "${ENTRYPOINT_SCRIPT}"
    exit $?
fi

# Start containers
log "Starting Docker containers..."
${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d --build

# Wait for container to be ready
log "Waiting for container '${CONTAINER_NAME}' to be ready..."
for i in $(seq 1 30); do
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        die "Container '${CONTAINER_NAME}' did not start within 60 seconds"
    fi
    sleep 2
done

if [ "${SKIP_INIT}" = true ]; then
    log "Container started. Skipping init as requested."
    exit 0
fi

# Run entrypoint initialization
log "Running entrypoint initialization (this may take 10-20 minutes on first run)..."
docker exec -u gpadmin "${CONTAINER_NAME}" bash -l "${ENTRYPOINT_SCRIPT}"

# Verify PXF health
log "Verifying PXF health..."
for i in $(seq 1 15); do
    if docker exec "${CONTAINER_NAME}" curl -sf http://localhost:5888/actuator/health >/dev/null 2>&1; then
        log "PXF is healthy - environment is ready!"
        echo ""
        echo "  Container:  ${CONTAINER_NAME}"
        echo "  SSH:        ssh -p 2222 gpadmin@localhost (password: cbdb@123)"
        echo "  PXF:        http://localhost:5888/actuator/health (via docker exec)"
        echo "  PGPORT:     7000 (inside container)"
        echo ""
        exit 0
    fi
    sleep 2
done

die "PXF health check failed after entrypoint completed"
