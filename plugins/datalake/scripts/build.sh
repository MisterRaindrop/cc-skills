#!/usr/bin/env bash
# build.sh - Build datalake components inside Docker container
# Usage: build.sh [TARGET] [OPTIONS]
# All commands execute inside the development container via docker exec.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[build][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [TARGET] [OPTIONS]

Build datalake components inside Docker container.

Targets:
  all          Build agent + proxy + fdw in order (default)
  fdw          Build datalake_fdw only (C/C++ PGXS + CMake agent_cli)
  agent        Build datalake_agent only (Java Maven)
  proxy        Build datalake_proxy only (C PGXS)
  clean        Clean all components
  status       Show build status (binary timestamps, coverage state)

Options:
  --coverage   Build datalake components with coverage flags (database must already be configured with --enable-coverage via build_database)
  --jobs N     Parallel build jobs (default: auto-detect inside container)
  -h, --help   Show this help
EOF
    exit 0
}

# --- Detect repo and container ---
DB_ROOT="$("${SCRIPT_DIR}/detect-datalake-repo.sh")" || die "Database repo not found. cd into it or set DATALAKE_DB_ROOT."
UMBRELLA_ROOT="$(dirname "$DB_ROOT")"
INSTANCE_NAME="$(basename "$DB_ROOT")"
DOCKER_DB_PATH="/workspace/${INSTANCE_NAME}"

eval "$("${SCRIPT_DIR}/detect-container.sh" "$UMBRELLA_ROOT")" || die "Development container not found."
# CONTAINER_NAME is now set

log "DB_ROOT (host): $DB_ROOT"
log "Docker path:    $DOCKER_DB_PATH"
log "Container:      $CONTAINER_NAME"

# --- Parse arguments ---
TARGET="${1:-all}"
shift 2>/dev/null || true

if [ "$TARGET" = "-h" ] || [ "$TARGET" = "--help" ]; then
    usage
fi

COVERAGE=false
JOBS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --coverage) COVERAGE=true; shift ;;
        --jobs) JOBS="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1. Run '$0 --help' for usage." ;;
    esac
done

# --- Docker exec wrapper ---
# Ensure toolchain GCC and greenplum_path.sh are in PATH for all builds
DIST_DIR="/workspace/dist/${INSTANCE_NAME}"
DEXEC_ENV="export PATH=/usr/local/toolchain/bin:/usr/local/python/bin:/usr/local/perl/bin:\$PATH; export LD_LIBRARY_PATH=/usr/local/toolchain/lib64:/usr/local/python/lib:\${LD_LIBRARY_PATH:-}; source ${DIST_DIR}/greenplum_path.sh;"
dexec() {
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "${DEXEC_ENV} $*"
}

# --- Determine parallel jobs ---
if [ -z "$JOBS" ]; then
    JOBS=$(dexec "nproc 2>/dev/null || echo 4")
fi

# --- Component paths inside container ---
FDW_DIR="${DOCKER_DB_PATH}/contrib/datalake_fdw"
AGENT_DIR="${DOCKER_DB_PATH}/contrib/datalake_agent"
PROXY_DIR="${DOCKER_DB_PATH}/contrib/datalake_proxy"

# --- Build functions ---
build_agent() {
    log "Building datalake_agent (Java Maven)..."
    dexec "cd ${AGENT_DIR} && make clean && make && make install"
    log "datalake_agent: done"
}

build_proxy() {
    log "Building datalake_proxy (C PGXS)..."
    dexec "cd ${PROXY_DIR} && make clean && make && make install"
    log "datalake_proxy: done"
}

build_fdw() {
    log "Building datalake_fdw (C/C++ PGXS + CMake agent_cli)..."
    dexec "cd ${FDW_DIR} && make clean && make -j${JOBS} && make install"
    log "datalake_fdw: done"
}

check_coverage_configured() {
    log "Checking coverage configuration..."
    local has_coverage
    has_coverage=$(dexec "grep -c 'enable_coverage.*yes' ${DOCKER_DB_PATH}/src/Makefile.global 2>/dev/null || echo 0")

    if [ "$has_coverage" = "0" ]; then
        die "Database not configured with --enable-coverage. Run 'build-database.sh --coverage' first."
    fi
    log "Coverage enabled in database configure."
}

do_clean() {
    log "Cleaning all components..."
    dexec "cd ${AGENT_DIR} && make clean 2>/dev/null || true"
    dexec "cd ${PROXY_DIR} && make clean 2>/dev/null || true"
    dexec "cd ${FDW_DIR} && make clean 2>/dev/null || true"
    log "Clean complete."
}

do_status() {
    log "Build status:"
    dexec "
echo '=== Component Binaries ==='
echo 'datalake_fdw.so:'
ls -la \$(pg_config --pkglibdir)/datalake_fdw.so 2>/dev/null || echo '  NOT FOUND'
echo 'dlagent-1.0.0.jar:'
ls -la \$(pg_config --pkglibdir)/java/dlagent-1.0.0.jar 2>/dev/null || echo '  NOT FOUND'
echo 'datalake_proxy.so:'
ls -la \$(pg_config --pkglibdir)/datalake_proxy.so 2>/dev/null || echo '  NOT FOUND'
echo ''
echo '=== Coverage State ==='
FDW_GCNO=\$(find ${FDW_DIR}/src -name '*.gcno' 2>/dev/null | wc -l)
FDW_GCDA=\$(find ${FDW_DIR}/src -name '*.gcda' 2>/dev/null | wc -l)
PROXY_GCNO=\$(find ${PROXY_DIR} -name '*.gcno' 2>/dev/null | wc -l)
echo \"FDW .gcno files: \${FDW_GCNO}\"
echo \"FDW .gcda files: \${FDW_GCDA}\"
echo \"Proxy .gcno files: \${PROXY_GCNO}\"
COVERAGE_ENABLED=\$(grep -c 'enable_coverage.*yes' ${DOCKER_DB_PATH}/src/Makefile.global 2>/dev/null || echo 0)
[ \"\$COVERAGE_ENABLED\" -gt 0 ] && echo 'Coverage: ENABLED' || echo 'Coverage: DISABLED'
"
}

# --- Execute target ---
log "Target: ${TARGET} | Coverage: ${COVERAGE} | Jobs: ${JOBS}"

if [ "$COVERAGE" = true ] && [ "$TARGET" != "clean" ] && [ "$TARGET" != "status" ]; then
    check_coverage_configured
fi

case "$TARGET" in
    all)
        build_agent
        build_proxy
        build_fdw
        ;;
    fdw)    build_fdw ;;
    agent)  build_agent ;;
    proxy)  build_proxy ;;
    clean)  do_clean ;;
    status) do_status ;;
    *)      die "Unknown target: ${TARGET}. Run '$0 --help' for usage." ;;
esac

if [ "$TARGET" != "status" ] && [ "$TARGET" != "clean" ]; then
    if [ "$COVERAGE" = true ]; then
        log "Verifying coverage instrumentation..."
        dexec "
GCNO=\$(find ${FDW_DIR}/src -name '*.gcno' | wc -l)
echo \"Coverage: \${GCNO} .gcno files generated\"
"
    fi

    # --- Restart cluster if deployed ---
    DEPLOY_DIR="/workspace/deploy/${INSTANCE_NAME}"
    CLUSTER_EXISTS=$(dexec "test -f '${DEPLOY_DIR}/.port' && echo yes || echo no")

    if [ "$CLUSTER_EXISTS" = "yes" ]; then
        PORT=$(dexec "cat '${DEPLOY_DIR}/.port'")
        log "Restarting cluster (PGPORT=${PORT})..."
        dexec "
set -e
export COORDINATOR_DATA_DIRECTORY='${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1'
export MASTER_DATA_DIRECTORY=\$COORDINATOR_DATA_DIRECTORY
export PGPORT=${PORT}

gpstop -ari 2>&1 || true
gpstart -a 2>&1
" || {
            log "WARNING: Cluster restart failed. You may need to restart manually."
        }

        # Verify cluster is healthy
        log "Verifying cluster health..."
        if dexec "
export PGPORT=${PORT}
export COORDINATOR_DATA_DIRECTORY='${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1'
psql -d template1 -t -c 'SELECT count(*) FROM gp_segment_configuration WHERE status = \\\"u\\\"' 2>/dev/null
"; then
            log "Cluster restarted and verified successfully."
        else
            log "WARNING: Cluster restart verification failed. Check cluster status manually."
        fi
    else
        log "No deployed cluster found. Skipping restart."
    fi

    log "Build complete: ${TARGET}"

    if [ "$CLUSTER_EXISTS" = "yes" ]; then
        echo ""
        echo "To connect:"
        echo "  docker exec -u gpadmin -it ${CONTAINER_NAME} bash"
        echo "  source ${DIST_DIR}/greenplum_path.sh"
        echo "  source ${DEPLOY_DIR}/gpdemo-env.sh"
        echo "  psql -d template1"
    fi
fi
