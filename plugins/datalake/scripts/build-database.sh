#!/usr/bin/env bash
# build-database.sh - Compile the full database inside Docker container
# Usage: build-database.sh [OPTIONS]
# Handles configure + make + make install for the entire Greenplum/Cloudberry database.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[build-database][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Compile the full database inside Docker container (configure + make + install).

Options:
  --clean        Clean build: reconfigure from scratch
  --coverage     Enable gcov coverage instrumentation (--enable-coverage)
  --debug        Debug build with assertions (default)
  --release      Release build (optimized, no assertions)
  --jobs N       Parallel build jobs (default: auto-detect inside container)
  --verbose      Stream build output to stdout instead of log file
  -h, --help     Show this help
EOF
    exit 0
}

# --- Detect repo and container ---
DB_ROOT="$("${SCRIPT_DIR}/detect-datalake-repo.sh")" || die "Database repo not found. cd into it or set DATALAKE_DB_ROOT."
UMBRELLA_ROOT="$(dirname "$DB_ROOT")"
INSTANCE_NAME="$(basename "$DB_ROOT")"
DOCKER_DB_PATH="/workspace/${INSTANCE_NAME}"

eval "$("${SCRIPT_DIR}/detect-container.sh" "$UMBRELLA_ROOT")" || die "Development container not found."

log "Instance:    $INSTANCE_NAME"
log "Docker path: $DOCKER_DB_PATH"
log "Container:   $CONTAINER_NAME"

# --- Parse arguments ---
CLEAN=false
COVERAGE=false
BUILD_TYPE="debug"
JOBS=""
USE_LOG=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean) CLEAN=true; shift ;;
        --coverage) COVERAGE=true; shift ;;
        --debug) BUILD_TYPE="debug"; shift ;;
        --release) BUILD_TYPE="release"; shift ;;
        --jobs) JOBS="$2"; shift 2 ;;
        --verbose) USE_LOG=false; shift ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1. Run '$0 --help' for usage." ;;
    esac
done

# --- Log file setup ---
if [ "$USE_LOG" = "true" ]; then
    LOG_DIR="${UMBRELLA_ROOT}/logs"
    mkdir -p "$LOG_DIR"
    COVERAGE_SUFFIX=""
    [ "$COVERAGE" = "true" ] && COVERAGE_SUFFIX="-coverage"
    LOG_FILE="${LOG_DIR}/build-database-${BUILD_TYPE}${COVERAGE_SUFFIX}-$(date '+%Y%m%d-%H%M%S').log"
    log "Build output -> $LOG_FILE"
fi

# --- Docker exec wrapper ---
dexec() {
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "$*"
}

# --- Determine parallel jobs ---
if [ -z "$JOBS" ]; then
    JOBS=$(dexec "nproc 2>/dev/null || echo 4")
fi

# --- Paths inside container ---
INSTALL_DIR="/workspace/dist/${INSTANCE_NAME}"
THIRDPARTY_DIR="/workspace/dist/thirdparty-${INSTANCE_NAME}"

log "Build type: ${BUILD_TYPE} | Coverage: ${COVERAGE} | Clean: ${CLEAN} | Jobs: ${JOBS}"

# --- Build ---
BUILD_CMD="
set -e

export PATH=/usr/local/toolchain/bin:/usr/local/python/bin:/usr/local/perl/bin:\$PATH
export LD_LIBRARY_PATH=/usr/local/toolchain/lib64:/usr/local/python/lib:\${LD_LIBRARY_PATH:-}

# Load SCL environments if available
for scl in /opt/rh/rh-python38 /opt/rh/devtoolset-10 /opt/rh/rh-git227; do
    [ -f \"\${scl}/enable\" ] && source \"\${scl}/enable\" 2>/dev/null || true
done

cd ${DOCKER_DB_PATH}
source /workspace/scripts/functions/database-function.sh

# Step 1: Install dependencies if needed
if [ ! -d '${THIRDPARTY_DIR}/lib' ]; then
    echo '=== Installing dependencies ==='
    database-install-dependency '${DOCKER_DB_PATH}' '${THIRDPARTY_DIR}'
fi

# Step 2: Clean if requested
if [ '${CLEAN}' = 'true' ]; then
    echo '=== Cleaning ==='
    make clean 2>/dev/null || true
fi

# Step 3: Configure
echo '=== Configuring (${BUILD_TYPE}, coverage=${COVERAGE}) ==='
database-generate-build-number '${DOCKER_DB_PATH}' \"\${BUILD_NUMBER:-dev}\"

if [ '${COVERAGE}' = 'true' ]; then
    # Configure with coverage
    CONFIGURE_OPTS='--enable-coverage'
    if [ '${BUILD_TYPE}' = 'debug' ]; then
        CONFIGURE_OPTS=\"\${CONFIGURE_OPTS} --enable-debug --enable-cassert\"
    fi
    ./configure \${CONFIGURE_OPTS} \
        --with-perl --with-python --with-libxml --with-gssapi \
        --enable-mapreduce --enable-orafce --enable-tap-tests \
        --prefix='${INSTALL_DIR}' \
        CFLAGS='-O0 -g3' CXXFLAGS='-O0 -g3'
else
    database-config '${BUILD_TYPE}' all '${DOCKER_DB_PATH}' '${DOCKER_DB_PATH}' '${INSTALL_DIR}' '${THIRDPARTY_DIR}'
fi

# Step 4: Build and install
echo '=== Building with ${JOBS} jobs ==='
make -j${JOBS}
make install

echo ''
echo '=== Database build complete ==='
echo \"Install dir: ${INSTALL_DIR}\"
if [ '${COVERAGE}' = 'true' ]; then
    GCNO=\$(find ${DOCKER_DB_PATH}/src -name '*.gcno' 2>/dev/null | wc -l)
    echo \"Coverage .gcno files: \${GCNO}\"
fi
"

set +e
if [ "$USE_LOG" = "true" ]; then
    dexec "$BUILD_CMD" > "$LOG_FILE" 2>&1
else
    dexec "$BUILD_CMD"
fi
BUILD_RC=$?
set -e

# --- Summary ---
if [ $BUILD_RC -eq 0 ]; then
    log "BUILD SUCCESS"
    log "Instance:   ${INSTANCE_NAME}"
    log "Build type: ${BUILD_TYPE}"
    log "Coverage:   ${COVERAGE}"
    log "Install:    ${INSTALL_DIR}"
    [ "$USE_LOG" = "true" ] && log "Log file:   ${LOG_FILE}"
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
