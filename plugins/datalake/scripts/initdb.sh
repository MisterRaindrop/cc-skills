#!/usr/bin/env bash
# initdb.sh - Deploy a gpdemo cluster for the current worktree
# Usage: initdb.sh [OPTIONS]
# Only handles cluster deployment (gpdemo). Does NOT compile — use build-database.sh for that.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[initdb][$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Deploy a gpdemo cluster for the current worktree inside Docker.
Instance name is derived from the worktree directory name.

Prerequisites: database must be compiled first (use build-database.sh).

Options:
  --port PORT      PGPORT base (default: auto-assign next available in 7000-7900 range)
  --clean          Stop existing cluster and redeploy from scratch
  -h, --help       Show this help
EOF
    exit 0
}

# --- Detect repo and container ---
DB_ROOT="$("${SCRIPT_DIR}/detect-datalake-repo.sh")" || die "Database repo not found."
UMBRELLA_ROOT="$(dirname "$DB_ROOT")"
INSTANCE_NAME="$(basename "$DB_ROOT")"
DOCKER_DB_PATH="/workspace/${INSTANCE_NAME}"

eval "$("${SCRIPT_DIR}/detect-container.sh" "$UMBRELLA_ROOT")" || die "Development container not found."

log "Instance:    $INSTANCE_NAME"
log "Docker path: $DOCKER_DB_PATH"
log "Container:   $CONTAINER_NAME"

# --- Parse arguments ---
PORT=""
CLEAN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --clean) CLEAN=true; shift ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

# --- Docker exec wrapper ---
dexec() {
    docker exec -u gpadmin "$CONTAINER_NAME" bash -c "$*"
}

# --- Paths inside container ---
INSTALL_DIR="/workspace/dist/${INSTANCE_NAME}"
DEPLOY_DIR="/workspace/deploy/${INSTANCE_NAME}"
THIRDPARTY_DIR="/workspace/dist/thirdparty-${INSTANCE_NAME}"

# --- Verify binaries exist ---
dexec "test -f '${INSTALL_DIR}/greenplum_path.sh'" || die "No binaries at ${INSTALL_DIR}. Run build-database.sh first."

# --- Port allocation (filesystem-based) ---
if [ -z "$PORT" ]; then
    log "Auto-assigning port..."
    PORT=$(dexec "
shopt -s nullglob
used_ports=()
for pf in /workspace/deploy/*/.port; do
    [ -f \"\$pf\" ] && used_ports+=(\$(cat \"\$pf\"))
done
for p in \$(seq 7000 100 7900); do
    found=false
    for u in \"\${used_ports[@]:-}\"; do
        [ \"\$p\" = \"\$u\" ] && found=true && break
    done
    if [ \"\$found\" = false ]; then
        echo \$p
        exit 0
    fi
done
echo 'ERROR: No free port in 7000-7900 range' >&2
exit 1
")
fi

log "PORT_BASE: $PORT"

# --- Clean existing deployment ---
if [ "$CLEAN" = true ]; then
    log "Cleaning existing deployment..."
    dexec "
if [ -d '${DEPLOY_DIR}' ]; then
    export PATH=/usr/local/toolchain/bin:/usr/local/python/bin:/usr/local/perl/bin:\$PATH
    export LD_LIBRARY_PATH=/usr/local/toolchain/lib64:/usr/local/python/lib:\${LD_LIBRARY_PATH:-}
    if [ -f '${INSTALL_DIR}/greenplum_path.sh' ]; then
        source '${INSTALL_DIR}/greenplum_path.sh'
        export COORDINATOR_DATA_DIRECTORY='${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1'
        export MASTER_DATA_DIRECTORY='\$COORDINATOR_DATA_DIRECTORY'
        gpstop -ai 2>/dev/null || true
    fi
    rm -rf '${DEPLOY_DIR}'
fi
"
fi

# --- Deploy gpdemo cluster ---
log "Deploying gpdemo cluster with PORT_BASE=${PORT}..."
dexec "
export PATH=/usr/local/toolchain/bin:/usr/local/python/bin:/usr/local/perl/bin:\$PATH
export LD_LIBRARY_PATH=/usr/local/toolchain/lib64:/usr/local/python/lib:\${LD_LIBRARY_PATH:-}
source '${INSTALL_DIR}/greenplum_path.sh'
export LD_LIBRARY_PATH=\"\${LD_LIBRARY_PATH:-}:${THIRDPARTY_DIR}/lib:${THIRDPARTY_DIR}/lib64\"

export PORT_BASE=${PORT}
export COORDINATOR_DATADIR='${DEPLOY_DIR}'
export STATEMENT_MEM=250MB

mkdir -p '${DEPLOY_DIR}'
cd '${DEPLOY_DIR}'

# Clean any previous gpdemo state
gpdemo -d >/dev/null 2>&1 || true

echo '--- Starting gpdemo ---'
gpdemo

# Record port for other scripts to discover
echo '${PORT}' > '${DEPLOY_DIR}/.port'
"

# --- Verify ---
log "Verifying cluster..."
dexec "
source '${INSTALL_DIR}/greenplum_path.sh'
export PGPORT=${PORT}
export COORDINATOR_DATA_DIRECTORY='${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1'
psql -d template1 -c 'select version();'
"

log "Cluster deployed successfully."
echo ""
echo "=== Instance: ${INSTANCE_NAME} ==="
echo "PGPORT:     ${PORT}"
echo "Deploy Dir: ${DEPLOY_DIR}"
echo "Data Dir:   ${DEPLOY_DIR}/datadirs/qddir/demoDataDir-1"
echo ""
echo "To connect:"
echo "  docker exec -u gpadmin -it ${CONTAINER_NAME} bash"
echo "  source ${INSTALL_DIR}/greenplum_path.sh"
echo "  source ${DEPLOY_DIR}/gpdemo-env.sh"
echo "  psql -d template1"
