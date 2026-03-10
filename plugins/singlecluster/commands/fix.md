# /singlecluster:fix

Auto-diagnose and fix common Singlecluster issues. Detects faults across all services and applies targeted fixes with interactive confirmation.

## Usage

```
/singlecluster:fix [--auto] [--service <name>]
```

**Options:**
- `--auto`: Apply all fixes without asking for confirmation (use with caution)
- `--service`: Only diagnose and fix a specific service (postgres, hdfs, minio, hive-metastore, hiveserver2, spark, polaris)

## Instructions

You are executing the `/singlecluster:fix` command. Follow these steps precisely:

**Important:** The singlecluster directory is located at:
```
/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
```

### Step 1: Run Full Diagnostics

First, run the diagnose script or perform inline diagnostics to identify all issues:

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

bash /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/github/cc-skills/plugins/singlecluster/scripts/diagnose.sh
```

Alternatively, check each fault condition inline. Collect all detected issues into a list before attempting any fixes.

### Step 2: Detect All Faults

Run through the complete fault detection table. For each check, record whether a fault is detected:

#### 2.1 Container Exited

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

# Check container states
LAKEHOUSE_STATE=$(docker inspect lakehouse --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
POLARIS_STATE=$(docker inspect polaris --format '{{.State.Status}}' 2>/dev/null || echo "not_found")

echo "lakehouse: $LAKEHOUSE_STATE"
echo "polaris: $POLARIS_STATE"
```

#### 2.2 PostgreSQL Down

```bash
docker exec lakehouse pg_isready -h localhost 2>/dev/null
```

#### 2.3 HDFS SafeMode

```bash
SAFEMODE=$(docker exec lakehouse hdfs dfsadmin -safemode get 2>&1)
echo "$SAFEMODE"
# Fault if output contains "Safe mode is ON"
```

#### 2.4 HDFS Not Formatted

```bash
# Check if HDFS VERSION file exists
docker exec lakehouse test -f /tmp/hadoop-root/dfs/name/current/VERSION 2>/dev/null
echo "Exit code: $?"
# Fault if exit code is non-zero
```

#### 2.5 MinIO Down

```bash
docker exec lakehouse bash -c 'nc -z localhost 9100' 2>/dev/null
```

#### 2.6 Hive Metastore Down

```bash
docker exec lakehouse bash -c 'nc -z localhost 9083' 2>/dev/null
```

#### 2.7 HiveServer2 Down

```bash
docker exec lakehouse bash -c 'nc -z localhost 10000' 2>/dev/null
```

#### 2.8 Spark Master Down

```bash
docker exec lakehouse bash -c 'nc -z localhost 7077' 2>/dev/null
```

#### 2.9 Polaris Unresponsive

```bash
curl -sf http://localhost:8181/q/health > /dev/null 2>&1
```

#### 2.10 Port Conflict

```bash
# Only check if docker compose up failed previously
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

docker compose up -d 2>&1 | grep -i "port is already allocated"
# If port conflict detected, identify the conflicting process
lsof -i :9083 -i :10000 -i :7077 -i :8181 -i :9100 -i :5432 2>/dev/null | grep LISTEN
```

### Step 3: Present Diagnostic Report

Display all detected faults in a table:

```
============================================================
  Singlecluster Diagnostic Report
============================================================

  #   Fault                     Status    Suggested Fix
  --  -----                     ------    -------------
  1   Container exited          [FAIL]    docker compose up -d
  2   PostgreSQL down           [OK]      --
  3   HDFS SafeMode             [FAIL]    hdfs dfsadmin -safemode leave
  4   HDFS not formatted        [OK]      --
  5   MinIO down                [OK]      --
  6   Hive Metastore down       [OK]      --
  7   HiveServer2 down          [FAIL]    restart hiveserver2
  8   Spark Master down         [OK]      --
  9   Polaris unresponsive      [OK]      --
  10  Port conflict             [OK]      --

  Issues found: 2
============================================================
```

If no issues are found:

> All services are healthy. No fixes needed.

Stop execution.

### Step 4: Apply Fixes Interactively

For each detected fault, present the fix and ask for confirmation (unless `--auto` was specified):

#### Fix: Container Exited

> **Fault:** Container `<name>` has exited.
> **Fix:** Run `docker compose up -d` to restart containers.
> Proceed? (yes/no)

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

docker compose up -d

# If lakehouse was restarted, services need to be started again
docker exec lakehouse /opt/start-all.sh
sleep 5
```

#### Fix: PostgreSQL Down

> **Fault:** PostgreSQL is not responding to pg_isready.
> **Fix:** Start PostgreSQL via pg_ctlcluster.
> Proceed? (yes/no)

```bash
docker exec lakehouse pg_ctlcluster 14 main start 2>/dev/null || \
docker exec lakehouse bash -c 'pg_ctl -D /var/lib/postgresql/data start' 2>/dev/null || \
docker exec lakehouse bash -c 'service postgresql start'
```

#### Fix: HDFS SafeMode

> **Fault:** HDFS is in Safe Mode. Write operations are blocked.
> **Fix:** Force leave Safe Mode.
> Proceed? (yes/no)

```bash
docker exec lakehouse hdfs dfsadmin -safemode leave
```

#### Fix: HDFS Not Formatted

> **Fault:** HDFS NameNode has not been formatted (no VERSION file found).
> **Fix:** Format the NameNode. WARNING: This will erase all HDFS data.
> Proceed? (yes/no)

```bash
docker exec lakehouse bash -c 'echo "Y" | hdfs namenode -format'
# Restart HDFS after formatting
docker exec lakehouse bash -c 'stop-dfs.sh; start-dfs.sh'
```

#### Fix: MinIO Down

> **Fault:** MinIO is not listening on port 9100.
> **Fix:** Restart MinIO server.
> Proceed? (yes/no)

```bash
docker exec -d lakehouse bash -c 'MINIO_ROOT_USER=admin MINIO_ROOT_PASSWORD=password minio server /data/minio --address :9100 --console-address :9101 &'
sleep 3
# Verify
docker exec lakehouse bash -c 'curl -sf http://localhost:9100/minio/health/live' && echo "MinIO: OK" || echo "MinIO: STILL FAILING"
```

Note: Read the docker-compose.yml or start-all.sh to determine the correct MinIO startup command and credentials before executing.

#### Fix: Hive Metastore Down

> **Fault:** Hive Metastore is not listening on port 9083.
> **Fix:** Restart Hive Metastore service.
> Proceed? (yes/no)

```bash
docker exec -d lakehouse bash -c 'hive --service metastore &'
sleep 5
docker exec lakehouse bash -c 'nc -z localhost 9083' && echo "Metastore: OK" || echo "Metastore: STILL FAILING"
```

#### Fix: HiveServer2 Down

> **Fault:** HiveServer2 is not listening on port 10000.
> **Fix:** Restart HiveServer2.
> Proceed? (yes/no)

```bash
docker exec -d lakehouse bash -c 'hive --service hiveserver2 &'
sleep 5
docker exec lakehouse bash -c 'nc -z localhost 10000' && echo "HiveServer2: OK" || echo "HiveServer2: STILL FAILING"
```

#### Fix: Spark Master Down

> **Fault:** Spark Master is not listening on port 7077.
> **Fix:** Start Spark Master.
> Proceed? (yes/no)

```bash
docker exec lakehouse bash -c '$SPARK_HOME/sbin/start-master.sh'
sleep 3
docker exec lakehouse bash -c 'nc -z localhost 7077' && echo "Spark Master: OK" || echo "Spark Master: STILL FAILING"
```

#### Fix: Polaris Unresponsive

> **Fault:** Polaris health endpoint is not responding.
> **Fix:** Restart the Polaris container.
> Proceed? (yes/no)

```bash
docker restart polaris
sleep 10
curl -sf http://localhost:8181/q/health && echo "Polaris: OK" || echo "Polaris: STILL FAILING"
```

#### Fix: Port Conflict

> **Fault:** Port(s) already in use by another process.
> **Detected conflicts:**
> `<lsof output>`
> **Fix:** Kill conflicting process(es) and retry docker compose up.
> Proceed? (yes/no)

```bash
# Kill the specific conflicting PID (show the user which process first)
# Example: kill <PID>
# Then retry
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
docker compose up -d
```

### Step 5: Post-Fix Verification

After all fixes have been applied, run a full health check:

```bash
bash /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/github/cc-skills/plugins/singlecluster/scripts/health-check.sh
```

Or run the inline health checks from `/singlecluster:status`.

Present the results:

```
============================================================
  Post-Fix Verification
============================================================

  Service            Before    After     Fix Applied
  -------            ------    -----     -----------
  PostgreSQL         [OK]      [OK]      --
  HDFS               [FAIL]    [OK]      safemode leave
  MinIO              [OK]      [OK]      --
  Hive Metastore     [OK]      [OK]      --
  HiveServer2        [FAIL]    [OK]      restart hiveserver2
  Spark Master       [OK]      [OK]      --
  Polaris            [OK]      [OK]      --

  Result: All issues resolved.
============================================================
```

If any service is still failing after fix, suggest:

> Some services are still unhealthy after fix attempts. You may need to:
> 1. Check container logs: `docker compose logs <service>`
> 2. Restart the entire cluster: `/singlecluster:down` then `/singlecluster:deploy`
> 3. Investigate manually inside the container: `docker exec -it lakehouse bash`

### Important Notes

- ALWAYS ask for confirmation before applying each fix (unless `--auto`)
- Fixes are applied in dependency order: containers first, then PostgreSQL, then HDFS, then higher-level services
- After fixing a container restart, remember to re-run `/opt/start-all.sh`
- HDFS format is destructive -- warn the user prominently
- Port conflict fixes involve killing processes -- show the user exactly what will be killed
- If a fix fails, do NOT retry automatically -- report the failure and move on
- The `--service` flag limits both detection and fixes to the specified service only
