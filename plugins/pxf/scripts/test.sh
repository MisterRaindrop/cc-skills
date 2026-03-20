#!/bin/bash
set -euo pipefail

# Run PXF automation tests inside the Docker container
# Usage: test.sh [GROUP] [OPTIONS]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$("${SCRIPT_DIR}/detect-pxf-repo.sh")" || { echo "ERROR: cloudberry-pxf repo not found. cd into it or set PXF_REPO."; exit 1; }
CONTAINER_NAME="pxf-cbdb-dev"
RUN_TESTS_SCRIPT="ci/docker/pxf-cbdb-dev/ubuntu/script/run_tests.sh"

log() { echo "[test][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [GROUP] [OPTIONS]

Run PXF automation tests inside the Docker container.

Groups:
  smoke          Smoke tests (default)
  sanity         Sanity tests
  hdfs           HDFS tests
  hive           Hive tests
  hbase          HBase tests
  hcatalog       HCatalog tests
  hcfs           HCFS tests
  jdbc           JDBC tests
  profile        Profile tests
  proxy          Proxy tests
  s3             S3/MinIO tests
  features       Feature tests
  gpdb           GPDB tests
  gpdb_fdw       GPDB FDW tests
  load           Load/benchmark tests
  performance    Performance tests
  server         Server unit tests (gradlew)
  cli            CLI tests
  fdw            FDW installcheck
  pxf_extension  PXF extension version tests
  all            Run all test groups

Options:
  TEST=ClassName          Run specific test class
  TEST=ClassName#method   Run specific test method
  --no-parse              Skip result parsing
  --keep-data             Keep test data on HDFS between runs
  -h, --help              Show this help

Examples:
  $0                           # Run smoke tests
  $0 hdfs                      # Run HDFS test group
  $0 smoke TEST=HdfsSmokeTest  # Run specific test class
  $0 hdfs TEST=HdfsReadableTextTest#testTextFormatSimple
EOF
    exit 0
}

# Parse args early so --help works without Docker
GROUP="${1:-smoke}"
shift 2>/dev/null || true

if [ "${GROUP}" = "-h" ] || [ "${GROUP}" = "--help" ]; then
    usage
fi

# Ensure container is running
docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$" || \
    die "Container '${CONTAINER_NAME}' is not running. Run 'docker-up.sh' first."

TEST_FILTER=""
NO_PARSE=false
EXTRA_ENV=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        TEST=*) TEST_FILTER="${1#TEST=}"; shift ;;
        --no-parse) NO_PARSE=true; shift ;;
        --keep-data) EXTRA_ENV="${EXTRA_ENV} PXF_TEST_KEEP_DATA=true"; shift ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

# Run command inside container
dexec() {
    docker exec -u gpadmin "${CONTAINER_NAME}" bash -lc "$*"
}

log "Running test group: ${GROUP}"
[ -n "${TEST_FILTER}" ] && log "Test filter: ${TEST_FILTER}"

# Build the test command
TEST_ENV="export GROUP=${GROUP};"
[ -n "${TEST_FILTER}" ] && TEST_ENV="${TEST_ENV} export TEST=${TEST_FILTER};"
[ -n "${EXTRA_ENV}" ] && TEST_ENV="${TEST_ENV} export ${EXTRA_ENV};"

# Dispatch based on group
TEST_EXIT=0
case "${GROUP}" in
    all)
        log "Running all test groups via run_tests.sh..."
        dexec "${TEST_ENV} bash -l ${RUN_TESTS_SCRIPT}" || TEST_EXIT=$?
        ;;
    server)
        log "Running server unit tests..."
        dexec "cd /home/gpadmin/workspace/cloudberry-pxf/server && ./gradlew test" || TEST_EXIT=$?
        ;;
    cli)
        log "Running CLI tests..."
        dexec "cd /home/gpadmin/workspace/cloudberry-pxf/cli && make test" || TEST_EXIT=$?
        ;;
    fdw)
        log "Running FDW installcheck..."
        dexec "source /usr/local/cloudberry-db/cloudberry-env.sh 2>/dev/null || true; cd /home/gpadmin/workspace/cloudberry-pxf/fdw && make installcheck" || TEST_EXIT=$?
        ;;
    *)
        log "Running group '${GROUP}' via run_tests.sh..."
        dexec "${TEST_ENV} bash -l ${RUN_TESTS_SCRIPT} ${GROUP}" || TEST_EXIT=$?
        ;;
esac

# Parse results
if [ "${NO_PARSE}" = false ] && [ "${GROUP}" != "server" ] && [ "${GROUP}" != "cli" ] && [ "${GROUP}" != "fdw" ]; then
    log "Parsing test results..."

    # Try to find reports inside container and copy them out
    REPORT_DIR="${REPO_DIR}/automation/target/surefire-reports"
    ARTIFACTS_DIR="${REPO_DIR}/automation/test_artifacts/${GROUP}"

    if [ -d "${ARTIFACTS_DIR}" ]; then
        "${SCRIPT_DIR}/parse-results.sh" "${ARTIFACTS_DIR}" || true
    elif [ -d "${REPORT_DIR}" ]; then
        "${SCRIPT_DIR}/parse-results.sh" "${REPORT_DIR}" || true
    else
        log "No test reports found to parse"
    fi
fi

if [ ${TEST_EXIT} -ne 0 ]; then
    log "Tests finished with failures (exit code: ${TEST_EXIT})"
else
    log "Tests passed!"
fi

exit ${TEST_EXIT}
