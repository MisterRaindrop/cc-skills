#!/bin/bash
set -euo pipefail

# Build PXF inside the development Docker container
# Usage: build.sh [all|server|quick|pxf-hdfs|pxf-jdbc|...]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$("${SCRIPT_DIR}/detect-pxf-repo.sh")" || { echo "ERROR: cloudberry-pxf repo not found. cd into it or set PXF_REPO."; exit 1; }
CONTAINER_NAME="pxf-cbdb-dev"
WORK_DIR="/home/gpadmin/workspace/cloudberry-pxf"

log() { echo "[build][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [TARGET] [OPTIONS]

Build PXF inside the Docker container.

Targets:
  all          Full build: make all && make install (default)
  server       Server only: ./gradlew stage -x test && make install-server
  quick        Quick install: make install-server (skip compilation)
  pxf-hdfs     Single module: ./gradlew :pxf-hdfs:build -x test && make install-server
  pxf-jdbc     Single module: ./gradlew :pxf-jdbc:build -x test && make install-server
  pxf-hive     Single module: ./gradlew :pxf-hive:build -x test && make install-server
  pxf-hbase    Single module: ./gradlew :pxf-hbase:build -x test && make install-server
  pxf-json     Single module: ./gradlew :pxf-json:build -x test && make install-server
  pxf-s3       Single module: ./gradlew :pxf-s3:build -x test && make install-server
  extensions   Extensions only: make extensions && make install
  test         Unit tests: make test

Options:
  --no-restart  Skip PXF restart after build
  -h, --help    Show this help
EOF
    exit 0
}

# Parse args early so --help works without Docker
TARGET="${1:-all}"
shift 2>/dev/null || true

if [ "${TARGET}" = "-h" ] || [ "${TARGET}" = "--help" ]; then
    usage
fi

# Ensure container is running
docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$" || \
    die "Container '${CONTAINER_NAME}' is not running. Run 'docker-up.sh' first."

# Run a command inside the container as gpadmin
dexec() {
    docker exec -u gpadmin -w "${WORK_DIR}" "${CONTAINER_NAME}" bash -lc "$*"
}

NO_RESTART=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-restart) NO_RESTART=true; shift ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

# Source env prefix for all builds (Java, paths, etc.)
ENV_PREFIX="source ci/docker/pxf-cbdb-dev/ubuntu/script/pxf-env.sh 2>/dev/null || true; export JAVA_HOME=\${JAVA_BUILD};"

log "Building target: ${TARGET}"

case "${TARGET}" in
    all)
        log "Full build: make all && make install"
        dexec "${ENV_PREFIX} make all && make install"
        ;;
    server)
        log "Server build: gradlew stage && make install-server"
        dexec "${ENV_PREFIX} cd server && ./gradlew stage -x test && cd .. && make install-server"
        ;;
    quick)
        log "Quick install: make install-server (no compilation)"
        dexec "${ENV_PREFIX} make install-server"
        ;;
    extensions)
        log "Extensions build: make extensions && make install"
        dexec "${ENV_PREFIX} make extensions && make install"
        ;;
    test)
        log "Running unit tests: make test"
        dexec "${ENV_PREFIX} make test"
        exit $?
        ;;
    pxf-*)
        MODULE="${TARGET}"
        log "Single module build: ${MODULE}"
        dexec "${ENV_PREFIX} cd server && ./gradlew :${MODULE}:build -x test && cd .. && make install-server"
        ;;
    *)
        die "Unknown target: ${TARGET}. Run '$0 --help' for usage."
        ;;
esac

# Restart PXF to pick up changes
if [ "${NO_RESTART}" = false ]; then
    log "Restarting PXF..."
    dexec "export JAVA_HOME=\${JAVA_BUILD:-/usr/lib/jvm/java-11-openjdk-\$(dpkg --print-architecture)}; pxf restart" || \
        log "WARN: PXF restart failed (may not be initialized yet)"
fi

log "Build complete: ${TARGET}"
