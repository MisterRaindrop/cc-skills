#!/usr/bin/env bash
# test.sh - Run datalake_fdw tests inside Docker container
# Usage: test.sh [TYPE]
# All commands execute inside the development container via docker exec.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[test][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [TYPE]

Run datalake_fdw tests inside Docker container.

Types:
  smoke        Run smoke tests (default)
  feature      Run feature tests
  all          Run all test suites
  regress      Run FDW built-in regression tests (make installcheck)
  <category>   Run a specific test category (s3, iceberg, hdfs, hive, orc, parquet, avro)

Options:
  -h, --help   Show this help
EOF
    exit 0
}

# --- Detect repo and container ---
DB_ROOT="$("${SCRIPT_DIR}/detect-datalake-repo.sh")" || die "Database repo not found."
UMBRELLA_ROOT="$(dirname "$DB_ROOT")"
INSTANCE_NAME="$(basename "$DB_ROOT")"
DOCKER_DB_PATH="/workspace/${INSTANCE_NAME}"

eval "$("${SCRIPT_DIR}/detect-container.sh" "$UMBRELLA_ROOT")" || die "Development container not found."

log "Docker path: $DOCKER_DB_PATH"
log "Container:   $CONTAINER_NAME"

# --- Parse arguments ---
TYPE="${1:-smoke}"
if [ "$TYPE" = "-h" ] || [ "$TYPE" = "--help" ]; then
    usage
fi

# --- Docker exec wrapper ---
DIST_DIR="/workspace/dist/${INSTANCE_NAME}"
DEPLOY_DIR="/workspace/deploy/${INSTANCE_NAME}"
DEXEC_ENV="export PATH=/usr/local/toolchain/bin:/usr/local/python/bin:/usr/local/perl/bin:\$PATH; export LD_LIBRARY_PATH=/usr/local/toolchain/lib64:/usr/local/python/lib:\${LD_LIBRARY_PATH:-}; source ${DIST_DIR}/greenplum_path.sh; export PGPORT=\$(cat ${DEPLOY_DIR}/.port 2>/dev/null || echo 5432); export COORDINATOR_DATA_DIRECTORY=${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1;"
dexec() {
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "${DEXEC_ENV} $*"
}

# --- Paths inside container ---
FDW_DIR="${DOCKER_DB_PATH}/contrib/datalake_fdw"
AUTOMATION_DIR="${FDW_DIR}/automation"

# --- Pre-flight checks ---
log "Pre-flight: checking datalake_fdw is installed..."
dexec "ls \$(pg_config --pkglibdir)/datalake_fdw.so >/dev/null 2>&1" || die "datalake_fdw.so not found. Run build.sh first."

# --- Execute tests ---
log "Test type: ${TYPE}"

case "$TYPE" in
    smoke)
        dexec "cd ${AUTOMATION_DIR} && make smoke-test"
        ;;
    feature)
        dexec "cd ${AUTOMATION_DIR} && make feature-test"
        ;;
    all)
        dexec "cd ${AUTOMATION_DIR} && if [ -f scripts/test/run_all_tests.sh ]; then bash scripts/test/run_all_tests.sh; else make smoke-test; make feature-test; fi"
        ;;
    regress)
        dexec "cd ${FDW_DIR} && make installcheck" || {
            log "Regression tests failed. Showing diffs:"
            dexec "cat ${FDW_DIR}/regression.diffs 2>/dev/null || echo 'No regression.diffs found'"
            exit 1
        }
        ;;
    *)
        # Try as a specific category under smoke
        dexec "
if [ -d ${AUTOMATION_DIR}/sqlrepo/smoke/${TYPE} ]; then
    cd ${AUTOMATION_DIR}/sqlrepo/smoke/${TYPE} && make installcheck
elif [ -d ${AUTOMATION_DIR}/sqlrepo/feature/${TYPE} ]; then
    cd ${AUTOMATION_DIR}/sqlrepo/feature/${TYPE} && make installcheck
else
    cd ${FDW_DIR} && make installcheck REGRESS='${TYPE}'
fi
" || {
            log "Tests failed for category: ${TYPE}. Showing diffs:"
            dexec "find ${AUTOMATION_DIR} ${FDW_DIR} -name 'regression.diffs' -exec echo '=== {} ===' \; -exec cat {} \; 2>/dev/null || echo 'No regression.diffs found'"
            exit 1
        }
        ;;
esac

log "Tests complete: ${TYPE}"
