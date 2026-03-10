#!/usr/bin/env bash
#
# health-check.sh - Singlecluster service health checker
#
# Description:
#   Checks the health of all services in the Singlecluster environment:
#   PostgreSQL, HDFS, MinIO, Hive Metastore, HiveServer2, Spark Master, Polaris.
#   Outputs per-service status with clear OK/FAIL indicators.
#
# Usage:
#   bash health-check.sh [--json]
#
# Options:
#   --json    Output results in JSON format
#
# Exit codes:
#   0  All services healthy
#   1  One or more services unhealthy
#   2  Critical error (e.g., Docker not available, container not running)

set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────────────────────

LAKEHOUSE_CONTAINER="lakehouse"
POLARIS_CONTAINER="polaris"
JSON_OUTPUT=false
FAILED_COUNT=0
TOTAL_COUNT=0
RESULTS=()

# ─── Argument parsing ──────────────────────────────────────────────────────────

for arg in "$@"; do
  case "$arg" in
    --json) JSON_OUTPUT=true ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done

# ─── Helper functions ──────────────────────────────────────────────────────────

check_docker() {
  if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running."
    exit 2
  fi
}

check_container_running() {
  local container="$1"
  local state
  state=$(docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
  if [ "$state" != "running" ]; then
    echo "ERROR: Container '$container' is not running (state: $state)."
    return 1
  fi
  return 0
}

record_result() {
  local service="$1"
  local status="$2"
  local detail="$3"
  TOTAL_COUNT=$((TOTAL_COUNT + 1))

  if [ "$status" = "FAIL" ]; then
    FAILED_COUNT=$((FAILED_COUNT + 1))
    local indicator="[FAIL]"
  else
    local indicator="[OK]  "
  fi

  RESULTS+=("$(printf "  %-22s %s  %s" "$service" "$indicator" "$detail")")

  if $JSON_OUTPUT; then
    echo "{\"service\":\"$service\",\"status\":\"$status\",\"detail\":\"$detail\"}"
  fi
}

# ─── Pre-flight checks ─────────────────────────────────────────────────────────

check_docker

if ! $JSON_OUTPUT; then
  echo "============================================================"
  echo "  Singlecluster Health Check"
  echo "============================================================"
  echo ""
fi

# ─── Check containers ──────────────────────────────────────────────────────────

LAKEHOUSE_OK=true
POLARIS_OK=true

if ! check_container_running "$LAKEHOUSE_CONTAINER" 2>/dev/null; then
  LAKEHOUSE_OK=false
  record_result "Lakehouse Container" "FAIL" "Container is not running"
else
  record_result "Lakehouse Container" "OK" "Running"
fi

if ! check_container_running "$POLARIS_CONTAINER" 2>/dev/null; then
  POLARIS_OK=false
  record_result "Polaris Container" "FAIL" "Container is not running"
else
  record_result "Polaris Container" "OK" "Running"
fi

# ─── Check services (only if lakehouse container is running) ────────────────────

if $LAKEHOUSE_OK; then

  # PostgreSQL
  if docker exec "$LAKEHOUSE_CONTAINER" pg_isready -h localhost > /dev/null 2>&1; then
    record_result "PostgreSQL" "OK" "pg_isready: accepting connections"
  else
    record_result "PostgreSQL" "FAIL" "pg_isready: not responding"
  fi

  # HDFS NameNode
  HDFS_REPORT=$(docker exec "$LAKEHOUSE_CONTAINER" hdfs dfsadmin -report 2>&1 || true)
  if echo "$HDFS_REPORT" | grep -q "Live datanodes"; then
    # Also check SafeMode
    SAFEMODE=$(docker exec "$LAKEHOUSE_CONTAINER" hdfs dfsadmin -safemode get 2>&1 || true)
    if echo "$SAFEMODE" | grep -q "Safe mode is ON"; then
      record_result "HDFS NameNode" "FAIL" "Running but in SafeMode"
    else
      record_result "HDFS NameNode" "OK" "Live datanodes found, SafeMode off"
    fi
  else
    record_result "HDFS NameNode" "FAIL" "No live datanodes or NameNode not running"
  fi

  # MinIO
  if docker exec "$LAKEHOUSE_CONTAINER" bash -c 'curl -sf http://localhost:9100/minio/health/live' > /dev/null 2>&1; then
    record_result "MinIO" "OK" "Health endpoint responding on port 9100"
  elif docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 9100' > /dev/null 2>&1; then
    record_result "MinIO" "OK" "Port 9100 open (health endpoint unreachable)"
  else
    record_result "MinIO" "FAIL" "Port 9100 not listening"
  fi

  # Hive Metastore
  if docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 9083' > /dev/null 2>&1; then
    record_result "Hive Metastore" "OK" "Port 9083 listening"
  else
    record_result "Hive Metastore" "FAIL" "Port 9083 not listening"
  fi

  # HiveServer2
  if docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 10000' > /dev/null 2>&1; then
    record_result "HiveServer2" "OK" "Port 10000 listening"
  else
    record_result "HiveServer2" "FAIL" "Port 10000 not listening"
  fi

  # Spark Master
  if docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 7077' > /dev/null 2>&1; then
    record_result "Spark Master" "OK" "Port 7077 listening"
  else
    record_result "Spark Master" "FAIL" "Port 7077 not listening"
  fi

fi

# ─── Check Polaris (separate container) ─────────────────────────────────────────

if $POLARIS_OK; then
  if curl -sf http://localhost:8181/q/health > /dev/null 2>&1; then
    record_result "Polaris" "OK" "/q/health responding"
  else
    record_result "Polaris" "FAIL" "/q/health not responding"
  fi
fi

# ─── Output results ────────────────────────────────────────────────────────────

if ! $JSON_OUTPUT; then
  echo "  Service                Status  Detail"
  echo "  -------                ------  ------"
  for result in "${RESULTS[@]}"; do
    echo "$result"
  done
  echo ""
  echo "------------------------------------------------------------"
  echo "  Total: $TOTAL_COUNT  Healthy: $((TOTAL_COUNT - FAILED_COUNT))  Failed: $FAILED_COUNT"
  echo "============================================================"
fi

# ─── Exit code ──────────────────────────────────────────────────────────────────

if [ "$FAILED_COUNT" -gt 0 ]; then
  exit 1
else
  exit 0
fi
