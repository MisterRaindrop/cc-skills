#!/usr/bin/env bash
#
# diagnose.sh - Singlecluster fault detection and fix suggestion
#
# Description:
#   Runs diagnostics against all Singlecluster services and outputs
#   detected problems with suggested fixes. Uses the fault table:
#     Container exited, PostgreSQL down, HDFS SafeMode, HDFS not formatted,
#     MinIO down, Hive Metastore down, HiveServer2 down, Spark Master down,
#     Polaris unresponsive, Port conflict.
#
# Usage:
#   bash diagnose.sh [--json] [--service <name>]
#
# Options:
#   --json               Output results in JSON format
#   --service <name>     Only diagnose a specific service
#
# Exit codes:
#   0  No issues detected
#   1  One or more issues detected
#   2  Critical error (e.g., Docker not available)

set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────────────────────

LAKEHOUSE_CONTAINER="lakehouse"
POLARIS_CONTAINER="polaris"
SINGLECLUSTER_DIR="/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster"
JSON_OUTPUT=false
TARGET_SERVICE=""
ISSUES_FOUND=0
ISSUE_NUM=0

# ─── Argument parsing ──────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    --service)
      TARGET_SERVICE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

# ─── Helper functions ──────────────────────────────────────────────────────────

check_docker() {
  if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running." >&2
    exit 2
  fi
}

should_check() {
  local service="$1"
  if [ -z "$TARGET_SERVICE" ]; then
    return 0
  fi
  if [ "$TARGET_SERVICE" = "$service" ]; then
    return 0
  fi
  return 1
}

report_issue() {
  local fault="$1"
  local detection="$2"
  local fix="$3"

  ISSUE_NUM=$((ISSUE_NUM + 1))
  ISSUES_FOUND=$((ISSUES_FOUND + 1))

  if $JSON_OUTPUT; then
    echo "{\"id\":$ISSUE_NUM,\"fault\":\"$fault\",\"detection\":\"$detection\",\"fix\":\"$fix\"}"
  else
    printf "  %-3s %-30s %-40s\n" "$ISSUE_NUM." "$fault" "$fix"
    printf "      Detection: %s\n" "$detection"
    echo ""
  fi
}

report_ok() {
  local check="$1"
  if ! $JSON_OUTPUT; then
    printf "  [OK]   %s\n" "$check"
  fi
}

# ─── Pre-flight ─────────────────────────────────────────────────────────────────

check_docker

if ! $JSON_OUTPUT; then
  echo "============================================================"
  echo "  Singlecluster Diagnostic Report"
  echo "============================================================"
  echo ""
fi

# ─── Fault 1: Container Exited ─────────────────────────────────────────────────

if should_check "container"; then
  LAKEHOUSE_STATE=$(docker inspect "$LAKEHOUSE_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
  POLARIS_STATE=$(docker inspect "$POLARIS_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")

  if [ "$LAKEHOUSE_STATE" != "running" ]; then
    report_issue \
      "Lakehouse container exited" \
      "docker inspect: state=$LAKEHOUSE_STATE" \
      "cd $SINGLECLUSTER_DIR && docker compose up -d"
  else
    report_ok "Lakehouse container running"
  fi

  if [ "$POLARIS_STATE" != "running" ]; then
    report_issue \
      "Polaris container exited" \
      "docker inspect: state=$POLARIS_STATE" \
      "cd $SINGLECLUSTER_DIR && docker compose up -d"
  else
    report_ok "Polaris container running"
  fi
fi

# ─── Check remaining services only if lakehouse is running ──────────────────────

LAKEHOUSE_RUNNING=false
if [ "$(docker inspect "$LAKEHOUSE_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")" = "running" ]; then
  LAKEHOUSE_RUNNING=true
fi

if $LAKEHOUSE_RUNNING; then

  # ─── Fault 2: PostgreSQL Down ───────────────────────────────────────────────

  if should_check "postgres"; then
    if ! docker exec "$LAKEHOUSE_CONTAINER" pg_isready -h localhost > /dev/null 2>&1; then
      report_issue \
        "PostgreSQL down" \
        "pg_isready: not accepting connections" \
        "docker exec lakehouse pg_ctlcluster 14 main start"
    else
      report_ok "PostgreSQL responding"
    fi
  fi

  # ─── Fault 3: HDFS SafeMode ────────────────────────────────────────────────

  if should_check "hdfs"; then
    SAFEMODE_OUT=$(docker exec "$LAKEHOUSE_CONTAINER" hdfs dfsadmin -safemode get 2>&1 || true)
    if echo "$SAFEMODE_OUT" | grep -q "Safe mode is ON"; then
      report_issue \
        "HDFS SafeMode ON" \
        "hdfs dfsadmin -safemode get: Safe mode is ON" \
        "docker exec lakehouse hdfs dfsadmin -safemode leave"
    else
      report_ok "HDFS SafeMode off"
    fi

    # ─── Fault 4: HDFS Not Formatted ───────────────────────────────────────────

    if ! docker exec "$LAKEHOUSE_CONTAINER" test -f /tmp/hadoop-root/dfs/name/current/VERSION 2>/dev/null; then
      report_issue \
        "HDFS not formatted" \
        "No VERSION file at /tmp/hadoop-root/dfs/name/current/" \
        "docker exec lakehouse bash -c 'echo Y | hdfs namenode -format'"
    else
      report_ok "HDFS formatted (VERSION file exists)"
    fi
  fi

  # ─── Fault 5: MinIO Down ───────────────────────────────────────────────────

  if should_check "minio"; then
    if ! docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 9100' > /dev/null 2>&1; then
      report_issue \
        "MinIO down" \
        "Port 9100 not listening" \
        "Restart MinIO server inside lakehouse container"
    else
      report_ok "MinIO port 9100 listening"
    fi
  fi

  # ─── Fault 6: Hive Metastore Down ──────────────────────────────────────────

  if should_check "hive-metastore"; then
    if ! docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 9083' > /dev/null 2>&1; then
      report_issue \
        "Hive Metastore down" \
        "Port 9083 not listening" \
        "docker exec -d lakehouse bash -c 'hive --service metastore &'"
    else
      report_ok "Hive Metastore port 9083 listening"
    fi
  fi

  # ─── Fault 7: HiveServer2 Down ─────────────────────────────────────────────

  if should_check "hiveserver2"; then
    if ! docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 10000' > /dev/null 2>&1; then
      report_issue \
        "HiveServer2 down" \
        "Port 10000 not listening" \
        "docker exec -d lakehouse bash -c 'hive --service hiveserver2 &'"
    else
      report_ok "HiveServer2 port 10000 listening"
    fi
  fi

  # ─── Fault 8: Spark Master Down ────────────────────────────────────────────

  if should_check "spark"; then
    if ! docker exec "$LAKEHOUSE_CONTAINER" bash -c 'nc -z localhost 7077' > /dev/null 2>&1; then
      report_issue \
        "Spark Master down" \
        "Port 7077 not listening" \
        "docker exec lakehouse \$SPARK_HOME/sbin/start-master.sh"
    else
      report_ok "Spark Master port 7077 listening"
    fi
  fi

fi

# ─── Fault 9: Polaris Unresponsive ──────────────────────────────────────────────

POLARIS_RUNNING=false
if [ "$(docker inspect "$POLARIS_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")" = "running" ]; then
  POLARIS_RUNNING=true
fi

if $POLARIS_RUNNING && should_check "polaris"; then
  if ! curl -sf http://localhost:8181/q/health > /dev/null 2>&1; then
    report_issue \
      "Polaris unresponsive" \
      "/q/health endpoint not returning 200" \
      "docker restart polaris"
  else
    report_ok "Polaris /q/health responding"
  fi
fi

# ─── Fault 10: Port Conflict ───────────────────────────────────────────────────

if should_check "ports"; then
  CONFLICT_PORTS=(5432 9083 9100 10000 7077 8181)
  PORT_CONFLICTS=""

  for port in "${CONFLICT_PORTS[@]}"; do
    LISTENERS=$(lsof -i :"$port" -sTCP:LISTEN 2>/dev/null | grep -v "^COMMAND" || true)
    if [ -n "$LISTENERS" ]; then
      # Check if the listener is NOT our docker container
      if ! echo "$LISTENERS" | grep -q "com.docke\|docker"; then
        PORT_CONFLICTS="${PORT_CONFLICTS}Port $port: $LISTENERS\n"
      fi
    fi
  done

  if [ -n "$PORT_CONFLICTS" ]; then
    report_issue \
      "Port conflict detected" \
      "Non-Docker processes listening on cluster ports" \
      "Kill conflicting processes: lsof -i :<port> then kill <PID>"
  else
    report_ok "No port conflicts detected"
  fi
fi

# ─── Summary ────────────────────────────────────────────────────────────────────

if ! $JSON_OUTPUT; then
  echo "------------------------------------------------------------"
  if [ "$ISSUES_FOUND" -eq 0 ]; then
    echo "  No issues detected. All checked services are healthy."
  else
    echo "  Issues found: $ISSUES_FOUND"
    echo "  Run /singlecluster:fix to apply suggested fixes."
  fi
  echo "============================================================"
fi

# ─── Exit code ──────────────────────────────────────────────────────────────────

if [ "$ISSUES_FOUND" -gt 0 ]; then
  exit 1
else
  exit 0
fi
