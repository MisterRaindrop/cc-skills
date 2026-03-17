# /datalake:singlecluster

Manage the Datalake singlecluster Docker environment (lakehouse + Polaris): deploy, status check, teardown, logs, and diagnostics.

## Usage

```
/datalake:singlecluster [deploy|status|down|logs|fix]
```

**Arguments:**
- `deploy` — Smart startup: detect existing environment, start if needed, health check, Polaris init
- `status` — Service health check for all components
- `down` — `docker compose down` to stop all containers
- `logs` — Show recent container logs (`docker compose logs --tail=50`)
- `fix` — Diagnose and fix common problems (SafeMode, services not started, etc.)
- *(no argument)* — Default to `status`

## Instructions

You are executing the `/datalake:singlecluster` command. Follow these steps precisely:

**Important:** The singlecluster directory is located at:
```
/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella2/hashdata-lightning-umbrella/database/contrib/datalake_fdw/automation/docker/singlecluster
```

All `docker compose` commands MUST be executed from this directory. Store this as `SINGLECLUSTER_DIR`.

### Key Reference Information

**Containers:**
- `lakehouse` — All-in-one container (HDFS, Hive, MinIO, Spark, PostgreSQL). Uses `command: ["tail","-f","/dev/null"]` so services must be started manually via `docker exec lakehouse /opt/start-all.sh`.
- `polaris` — Apache Polaris Iceberg REST catalog. Also uses `command: ["tail","-f","/dev/null"]` so needs manual start.

**Service Port Map:**

| Service | Container Port | Host Port | Check Method |
|---------|---------------|-----------|--------------|
| HDFS NameNode | 8020 | — | `docker exec lakehouse hdfs dfsadmin -report` |
| HDFS NN Web UI | 9870 | 9870 | HTTP |
| Hive Metastore | 9083 | 9083 | `nc -z localhost 9083` |
| HiveServer2 | 10000 | 10000 | `nc -z localhost 10000` |
| MinIO API | 9100 | 9100 | `curl -sf http://localhost:9100/minio/health/live` |
| MinIO Console | 9200 | 9200 | HTTP |
| Spark Master | 7077 | 7077 | `nc -z localhost 7077` |
| Spark Web UI | 8080 | 8080 | HTTP |
| Polaris API | 8181 | 18181 | `curl -sf http://localhost:18182/q/health` |

**Network:** `share-enterprise-ci` (external, must exist before `docker compose up`)

**Credentials:**
- MinIO: `admin` / `password`
- Polaris: `root` / `s3cr3t`

**Polaris CLI:** `$SINGLECLUSTER_DIR/scripts/polaris_cli.sh`

---

### Subcommand: `deploy`

#### Step 1: Check Prerequisites

```bash
# Check Docker daemon
docker info > /dev/null 2>&1
```

If Docker is not running, tell the user and stop.

#### Step 2: Check and Create Network

```bash
if ! docker network inspect share-enterprise-ci > /dev/null 2>&1; then
  echo "Creating external network: share-enterprise-ci"
  docker network create share-enterprise-ci
else
  echo "Network share-enterprise-ci: already exists, skipping creation"
fi
```

#### Step 3: Check Existing Containers

```bash
cd $SINGLECLUSTER_DIR
docker compose ps --format json 2>/dev/null
```

Analyze the output:
- **Both `lakehouse` and `polaris` running**: Tell user "Singlecluster containers already running, skipping startup." Jump directly to Step 6 (health check).
- **Partially running**: Ask user whether to Restart (down + up) or Keep and re-check health.
- **None running**: Continue to Step 4.

#### Step 4: Start Containers

```bash
cd $SINGLECLUSTER_DIR
docker compose up -d
```

Verify containers started:
```bash
docker compose ps
```

If any container failed, check `docker compose logs --tail=30` and report.

#### Step 5: Start Services

The lakehouse container uses `tail -f /dev/null`, so services must be started manually:

```bash
echo "Starting all services inside lakehouse container..."
docker exec lakehouse /opt/start-all.sh
```

**Important:** `start-all.sh` tails logs at the end and will block. Run it detached or with timeout:
```bash
docker exec -d lakehouse /opt/start-all.sh
```

Wait for services to initialize:
```bash
sleep 15
```

For Polaris, it also uses `tail -f /dev/null`. Start Polaris server:
```bash
docker exec -d polaris /app/bin/polaris-service
```

Wait for Polaris to initialize:
```bash
sleep 10
```

#### Step 6: Health Check

Check each service with retries (max 120 seconds total, 10-second intervals):

```bash
# PostgreSQL
docker exec lakehouse pg_isready -h localhost

# HDFS NameNode
docker exec lakehouse hdfs dfsadmin -report 2>&1 | grep -q 'Live datanodes'

# HDFS SafeMode check
docker exec lakehouse hdfs dfsadmin -safemode get 2>&1 | grep -q 'Safe mode is OFF'

# MinIO
docker exec lakehouse bash -c 'curl -sf http://localhost:9100/minio/health/live'

# Hive Metastore
docker exec lakehouse bash -c 'nc -z localhost 9083'

# HiveServer2
docker exec lakehouse bash -c 'nc -z localhost 10000'

# Spark Master
docker exec lakehouse bash -c 'nc -z localhost 7077'

# Polaris
curl -sf http://localhost:18182/q/health
```

Display results as a table:
```
## Singlecluster Health Check

| Service         | Status | Detail                              |
|-----------------|--------|-------------------------------------|
| PostgreSQL      | OK     | pg_isready: accepting connections   |
| HDFS NameNode   | OK     | Live datanodes found, SafeMode off  |
| MinIO           | OK     | Health endpoint on port 9100        |
| Hive Metastore  | OK     | Port 9083 listening                 |
| HiveServer2     | OK     | Port 10000 listening                |
| Spark Master    | OK     | Port 7077 listening                 |
| Polaris         | OK     | /q/health responding                |
```

If any service fails, warn and suggest `/datalake:singlecluster fix`.

#### Step 7: Initialize Polaris

If Polaris is healthy, run initialization:

```bash
cd $SINGLECLUSTER_DIR
API_HOST=http://localhost:18181 bash scripts/polaris_cli.sh create-namespace
```

This creates the default catalog (`polaris_default_catalog`) and namespace (`public`).

If Polaris init fails, warn but do not abort — the cluster is still usable.

#### Step 8: Output Summary

```
## Singlecluster Deployment Complete

| Service         | Endpoint                      | Status |
|-----------------|-------------------------------|--------|
| PostgreSQL      | localhost:5432                | OK     |
| HDFS NameNode   | http://localhost:9870         | OK     |
| MinIO API       | http://localhost:9100         | OK     |
| MinIO Console   | http://localhost:9200         | OK     |
| Hive Metastore  | thrift://localhost:9083       | OK     |
| HiveServer2     | jdbc:hive2://localhost:10000  | OK     |
| Spark Master    | spark://localhost:7077        | OK     |
| Spark Web UI    | http://localhost:8080         | OK     |
| Polaris API     | http://localhost:18181        | OK     |

Tip: Run `/datalake:singlecluster status` for health checks
     Run `/datalake:singlecluster fix` if any service shows issues
```

---

### Subcommand: `status`

Run health checks only (same as deploy Step 6). Do NOT start or stop anything.

```bash
cd $SINGLECLUSTER_DIR
docker compose ps
```

Then check each service as described in deploy Step 6 and display the health table.

---

### Subcommand: `down`

```bash
cd $SINGLECLUSTER_DIR
docker compose down
```

Confirm success with `docker compose ps`.

---

### Subcommand: `logs`

```bash
cd $SINGLECLUSTER_DIR
docker compose logs --tail=50
```

If the user specifies a service name (e.g., `logs lakehouse`), show only that service's logs:
```bash
docker compose logs --tail=50 lakehouse
```

---

### Subcommand: `fix`

Diagnose and fix common issues:

#### Issue 1: HDFS SafeMode
```bash
SAFEMODE=$(docker exec lakehouse hdfs dfsadmin -safemode get 2>&1)
if echo "$SAFEMODE" | grep -q "Safe mode is ON"; then
  echo "HDFS is in SafeMode. Forcing leave..."
  docker exec lakehouse hdfs dfsadmin -safemode leave
fi
```

#### Issue 2: Services Not Started
If services are not running inside lakehouse (ports not listening):
```bash
docker exec -d lakehouse /opt/start-all.sh
sleep 15
```

#### Issue 3: Polaris Not Responding
Check if Polaris process is running:
```bash
docker exec polaris ps aux | grep polaris
```

If not running, start it:
```bash
docker exec -d polaris /app/bin/polaris-service
sleep 10
```

#### Issue 4: Network Missing
```bash
if ! docker network inspect share-enterprise-ci > /dev/null 2>&1; then
  docker network create share-enterprise-ci
fi
```

After applying fixes, re-run health checks and display results.

### Important Notes

- All `docker compose` commands must be run from `$SINGLECLUSTER_DIR`
- The lakehouse container requires manual service start via `docker exec lakehouse /opt/start-all.sh`
- The polaris container also requires manual start of the Polaris service
- `start-all.sh` ends with `tail -f` which will block — always run with `-d` flag
- Health checks should be retried with back-off, not just checked once
- Network `share-enterprise-ci` must exist before `docker compose up`
- Do NOT run `docker compose down` without the user explicitly requesting it
- Polaris host port is 18181 (not 8181), health check port is 18182
