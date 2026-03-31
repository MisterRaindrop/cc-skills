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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean) CLEAN=true; shift ;;
        --coverage) COVERAGE=true; shift ;;
        --debug) BUILD_TYPE="debug"; shift ;;
        --release) BUILD_TYPE="release"; shift ;;
        --jobs) JOBS="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1. Run '$0 --help' for usage." ;;
    esac
done

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
dexec "
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
        --with-thirdparty='${THIRDPARTY_DIR}' \
        --prefix='${INSTALL_DIR}' \
        CFLAGS='-O0 -g3' CXXFLAGS='-O0 -g3'
else
    database-config '${BUILD_TYPE}' all '${DOCKER_DB_PATH}' '${DOCKER_DB_PATH}' '${INSTALL_DIR}' '${THIRDPARTY_DIR}'
fi

# Step 4: Build and install
echo '=== Building with ${JOBS} jobs ==='
BUILD_LOG=/tmp/database-build-\$\$.log
if ! make -j${JOBS} 2>&1 | tee \${BUILD_LOG}; then
    echo ''
    echo '=== BUILD FAILED - Error summary ==='
    grep -E '(: error:|undefined reference|fatal error:|make\\[.*\\]: \\*\\*\\*)' \${BUILD_LOG} | tail -30
    echo '=== Full log: '\${BUILD_LOG}' ==='
    exit 2
fi
make install

echo ''
echo '=== Database build complete ==='
echo \"Install dir: ${INSTALL_DIR}\"
if [ '${COVERAGE}' = 'true' ]; then
    GCNO=\$(find ${DOCKER_DB_PATH}/src -name '*.gcno' 2>/dev/null | wc -l)
    echo \"Coverage .gcno files: \${GCNO}\"
fi
"

# --- Restart cluster if deployed ---
DEPLOY_DIR="/workspace/deploy/${INSTANCE_NAME}"
CLUSTER_EXISTS=$(dexec "test -f '${DEPLOY_DIR}/.port' && echo yes || echo no")

if [ "$CLUSTER_EXISTS" = "yes" ]; then
    PORT=$(dexec "cat '${DEPLOY_DIR}/.port'")
    log "Restarting cluster (PGPORT=${PORT})..."
    dexec "
set -e
export PATH=/usr/local/toolchain/bin:/usr/local/python/bin:/usr/local/perl/bin:\$PATH
export LD_LIBRARY_PATH=/usr/local/toolchain/lib64:/usr/local/python/lib:\${LD_LIBRARY_PATH:-}
source '${INSTALL_DIR}/greenplum_path.sh'
export COORDINATOR_DATA_DIRECTORY='${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1'
export MASTER_DATA_DIRECTORY=\$COORDINATOR_DATA_DIRECTORY
export PGPORT=${PORT}

gpstop -ai 2>&1 || true
gpstart -a 2>&1
" || {
        log "WARNING: Cluster restart failed. You may need to restart manually."
    }

    # Verify cluster is healthy
    log "Verifying cluster health..."
    if dexec "
source '${INSTALL_DIR}/greenplum_path.sh'
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

log "Database build complete: ${INSTANCE_NAME}"

if [ "$CLUSTER_EXISTS" = "yes" ]; then
    echo ""
    echo "To connect:"
    echo "  docker exec -u gpadmin -it ${CONTAINER_NAME} bash"
    echo "  source ${INSTALL_DIR}/greenplum_path.sh"
    echo "  source ${DEPLOY_DIR}/gpdemo-env.sh"
    echo "  psql -d template1"
fi
