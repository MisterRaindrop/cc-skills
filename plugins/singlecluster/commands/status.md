# /singlecluster:status

Comprehensive health check for all Singlecluster services. Reports container status, per-service health (process, port, functional validation), disk usage, and recent log errors.

## Usage

```
/singlecluster:status [--verbose] [--json]
```

**Options:**
- `--verbose`: Show extended diagnostics (full process lists, recent logs)
- `--json`: Output in JSON format for programmatic consumption

## Instructions

You are executing the `/singlecluster:status` command. Follow these steps precisely:

**Important:** The singlecluster directory is located at:
```
/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
```

### Step 1: Check Container Status

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

# Check if containers exist and their state
docker compose ps -a
```

If no containers are found:

> Singlecluster is not deployed. Run `/singlecluster:deploy` to start.

Stop execution.

If containers exist but are not running, note which ones are stopped and continue checking what is available.

### Step 2: Check Each Service

For each service, check three dimensions: **process**, **port**, and **functional validation**.

#### 2.1 PostgreSQL

```bash
# Process check
docker exec lakehouse pgrep -x postgres > /dev/null 2>&1 && echo "Process: OK" || echo "Process: FAIL"

# Port check
docker exec lakehouse bash -c 'nc -z localhost 5432' 2>/dev/null && echo "Port 5432: OK" || echo "Port 5432: FAIL"

# Functional check
docker exec lakehouse pg_isready -h localhost 2>/dev/null && echo "Functional: OK" || echo "Functional: FAIL"
```

#### 2.2 HDFS NameNode

```bash
# Process check
docker exec lakehouse pgrep -f NameNode > /dev/null 2>&1 && echo "Process: OK" || echo "Process: FAIL"

# Port check
docker exec lakehouse bash -c 'nc -z localhost 9870' 2>/dev/null && echo "Port 9870: OK" || echo "Port 9870: FAIL"

# Functional check
docker exec lakehouse hdfs dfsadmin -report 2>&1 | head -5

# Check SafeMode
docker exec lakehouse hdfs dfsadmin -safemode get 2>&1
```

#### 2.3 MinIO

```bash
# Process check
docker exec lakehouse pgrep -f minio > /dev/null 2>&1 && echo "Process: OK" || echo "Process: FAIL"

# Port check
docker exec lakehouse bash -c 'nc -z localhost 9100' 2>/dev/null && echo "Port 9100: OK" || echo "Port 9100: FAIL"

# Functional check
docker exec lakehouse bash -c 'curl -sf http://localhost:9100/minio/health/live' && echo "Functional: OK" || echo "Functional: FAIL"
```

#### 2.4 Hive Metastore

```bash
# Process check
docker exec lakehouse pgrep -f HiveMetaStore > /dev/null 2>&1 && echo "Process: OK" || echo "Process: FAIL"

# Port check
docker exec lakehouse bash -c 'nc -z localhost 9083' 2>/dev/null && echo "Port 9083: OK" || echo "Port 9083: FAIL"

# Functional check (try listing databases via beeline or hive CLI)
docker exec lakehouse bash -c 'hive --service metatool -listFSRoot 2>/dev/null' && echo "Functional: OK" || echo "Functional: SKIPPED"
```

#### 2.5 HiveServer2

```bash
# Process check
docker exec lakehouse pgrep -f HiveServer2 > /dev/null 2>&1 && echo "Process: OK" || echo "Process: FAIL"

# Port check
docker exec lakehouse bash -c 'nc -z localhost 10000' 2>/dev/null && echo "Port 10000: OK" || echo "Port 10000: FAIL"

# Functional check (simple JDBC connection test)
docker exec lakehouse bash -c 'beeline -u "jdbc:hive2://localhost:10000" -e "SELECT 1;" 2>/dev/null' && echo "Functional: OK" || echo "Functional: SKIPPED"
```

#### 2.6 Spark Master

```bash
# Process check
docker exec lakehouse pgrep -f spark.deploy.master.Master > /dev/null 2>&1 && echo "Process: OK" || echo "Process: FAIL"

# Port check
docker exec lakehouse bash -c 'nc -z localhost 7077' 2>/dev/null && echo "Port 7077: OK" || echo "Port 7077: FAIL"

# Web UI check
docker exec lakehouse bash -c 'curl -sf http://localhost:8080 > /dev/null' && echo "Web UI: OK" || echo "Web UI: FAIL"
```

#### 2.7 Polaris

```bash
# Container check
docker inspect polaris --format '{{.State.Status}}' 2>/dev/null || echo "Container: NOT FOUND"

# Functional check
curl -sf http://localhost:8181/q/health && echo "Health: OK" || echo "Health: FAIL"

# Detailed health (if verbose)
curl -sf http://localhost:8181/q/health | python3 -m json.tool 2>/dev/null
```

### Step 3: Output Status Table

Compile all results into a clear status table:

```
============================================================
  Singlecluster Status Report
============================================================

  Container       Image                        State       Uptime
  ---------       -----                        -----       ------
  lakehouse       lakehouse-allinone:latest     running     2h 15m
  polaris         apache-polaris:1.3.0-local    running     2h 15m

  Service            Process    Port      Functional    Overall
  -------            -------    ----      ----------    -------
  PostgreSQL         OK         5432 OK   pg_isready OK   [OK]
  HDFS NameNode      OK         9870 OK   report OK       [OK]
  MinIO              OK         9100 OK   health OK       [OK]
  Hive Metastore     OK         9083 OK   --              [OK]
  HiveServer2        OK         10000 OK  SELECT 1 OK     [OK]
  Spark Master       OK         7077 OK   web UI OK       [OK]
  Polaris            OK         8181 OK   /q/health OK    [OK]

============================================================
```

Use `[OK]` for healthy, `[WARN]` for degraded (partial checks pass), `[FAIL]` for down.

### Step 4: Disk Usage

```bash
# Container disk usage
docker system df

# Singlecluster data directory sizes
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
du -sh data/* 2>/dev/null || echo "No data directory found"
```

### Step 5: Recent Log Errors

Check for recent errors in service logs:

```bash
# Docker compose logs (last 50 lines, errors only)
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
docker compose logs --tail=50 2>/dev/null | grep -i -E 'error|exception|fatal|fail' | tail -20
```

If `--verbose` is specified, also show:

```bash
# Full process list inside lakehouse
docker exec lakehouse ps aux

# Java processes specifically
docker exec lakehouse jps -l 2>/dev/null

# Recent container events
docker events --since 1h --until now --filter container=lakehouse --format '{{.Time}} {{.Action}}' 2>/dev/null | tail -10
```

### Step 6: Summary and Recommendations

Based on the findings:

- If all services are healthy: Report "All services healthy."
- If any service is degraded or down: List affected services and suggest running `/singlecluster:fix`
- If containers are stopped: Suggest running `/singlecluster:deploy`

### Important Notes

- Non-destructive command -- only reads status, never modifies anything
- Functional checks may produce noisy output; focus on pass/fail
- HDFS SafeMode is a common issue after restart -- flag it prominently if detected
- Polaris is in a separate container; check it independently
- If `nc` (netcat) is not available in the container, fall back to `/dev/tcp` or `curl`
