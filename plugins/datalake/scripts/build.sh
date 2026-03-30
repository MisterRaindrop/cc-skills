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
  --verbose    Stream build output to stdout instead of log file
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
USE_LOG=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --coverage) COVERAGE=true; shift ;;
        --jobs) JOBS="$2"; shift 2 ;;
        --verbose) USE_LOG=false; shift ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1. Run '$0 --help' for usage." ;;
    esac
done

# --- Docker exec wrapper ---
dexec() {
    if [ "${USE_LOG:-false}" = "true" ] && [ -n "${LOG_FILE:-}" ]; then
        docker exec -u gpadmin "$CONTAINER_NAME" bash -c "$*" >> "$LOG_FILE" 2>&1
    else
        docker exec -u gpadmin "$CONTAINER_NAME" bash -c "$*"
    fi
}

# --- Log file setup ---
if [ "$USE_LOG" = "true" ]; then
    LOG_DIR="${UMBRELLA_ROOT}/logs"
    mkdir -p "$LOG_DIR"
    COVERAGE_SUFFIX=""
    [ "$COVERAGE" = "true" ] && COVERAGE_SUFFIX="-coverage"
    LOG_FILE="${LOG_DIR}/build-${TARGET}${COVERAGE_SUFFIX}-$(date '+%Y%m%d-%H%M%S').log"
    log "Build output -> $LOG_FILE"
fi

# --- Determine parallel jobs ---
if [ -z "$JOBS" ]; then
    # nproc detection must not go to log file
    JOBS=$(docker exec -u gpadmin "$CONTAINER_NAME" bash -c "nproc 2>/dev/null || echo 4")
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
    # Always check to stdout, not log file
    has_coverage=$(docker exec -u gpadmin "$CONTAINER_NAME" bash -c "grep -c 'enable_coverage.*yes' ${DOCKER_DB_PATH}/src/Makefile.global 2>/dev/null || echo 0")

    if [ "$has_coverage" = "0" ]; then
        die "Database not configured with --enable-coverage. Run 'build-database.sh --coverage' first."
    fi
    log "Coverage enabled in database configure."
}

do_clean() {
    log "Cleaning all components..."
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "cd ${AGENT_DIR} && make clean 2>/dev/null || true"
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "cd ${PROXY_DIR} && make clean 2>/dev/null || true"
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "cd ${FDW_DIR} && make clean 2>/dev/null || true"
    log "Clean complete."
}

do_status() {
    log "Build status:"
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "
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

set +e
case "$TARGET" in
    all)
        build_agent && build_proxy && build_fdw
        ;;
    fdw)    build_fdw ;;
    agent)  build_agent ;;
    proxy)  build_proxy ;;
    clean)  do_clean ;;
    status) do_status ;;
    *)      die "Unknown target: ${TARGET}. Run '$0 --help' for usage." ;;
esac
BUILD_RC=$?
set -e

if [ "$TARGET" != "status" ] && [ "$TARGET" != "clean" ]; then
    if [ $BUILD_RC -eq 0 ]; then
        if [ "$COVERAGE" = true ]; then
            log "Verifying coverage instrumentation..."
            dexec "
GCNO=\$(find ${FDW_DIR}/src -name '*.gcno' | wc -l)
echo \"Coverage: \${GCNO} .gcno files generated\"
"
        fi
        log "BUILD SUCCESS"
        log "Target:    ${TARGET}"
        log "Instance:  ${INSTANCE_NAME}"
        log "Coverage:  ${COVERAGE}"
        [ "$USE_LOG" = "true" ] && log "Log file:  ${LOG_FILE}"
    else
        log "BUILD FAILED (exit code: ${BUILD_RC})"
        if [ "$USE_LOG" = "true" ]; then
            log "Last 30 lines of build log:"
            echo "---"
            tail -30 "$LOG_FILE"
            echo "---"
            log "Full log: ${LOG_FILE}"
        fi
        exit $BUILD_RC
    fi
fi
