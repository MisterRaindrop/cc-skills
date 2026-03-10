# /singlecluster:deploy

Smart one-click deployment for the Singlecluster environment (Hive/HDFS/Spark/MinIO/Polaris). Handles prerequisites, container orchestration, service startup, health verification, and Polaris initialization.

## Usage

```
/singlecluster:deploy [--skip-build] [--skip-polaris-init] [--timeout <seconds>]
```

**Options:**
- `--skip-build`: Skip image build even if images are missing (fail instead)
- `--skip-polaris-init`: Skip Polaris catalog/namespace initialization
- `--timeout`: Health check timeout in seconds (default: 120)

## Instructions

You are executing the `/singlecluster:deploy` command. Follow these steps precisely:

**Important:** The singlecluster directory is located at:
```
/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
```

All `docker compose` commands MUST be executed from this directory.

### Step 1: Check Prerequisites

Verify Docker and Docker Compose are available:

```bash
# Check Docker daemon is running
docker info > /dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "ERROR: Docker daemon is not running. Please start Docker first."
  exit 1
fi

# Check Docker Compose
docker compose version > /dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "ERROR: Docker Compose is not available."
  exit 1
fi

echo "Docker and Docker Compose: OK"
```

Check and create the external network if missing:

```bash
if ! docker network inspect share-enterprise-ci > /dev/null 2>&1; then
  echo "Creating external network: share-enterprise-ci"
  docker network create share-enterprise-ci
else
  echo "Network share-enterprise-ci: OK"
fi
```

If any prerequisite fails, report the exact error and stop.

### Step 2: Check Existing Containers

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

# Check if containers are already running
RUNNING=$(docker compose ps --format json 2>/dev/null | grep -c '"running"' || true)
if [ "$RUNNING" -gt 0 ]; then
  docker compose ps
  echo ""
  echo "Containers are already running."
fi
```

If containers are running, ask the user:

> Singlecluster containers are already running. Would you like to:
> 1. **Keep** them and only re-check health
> 2. **Restart** them (down + up)
> 3. **Abort** deployment

- **Keep**: Skip to Step 6 (health checks)
- **Restart**: Run `docker compose down` first, then continue from Step 3
- **Abort**: Stop execution

### Step 3: Check Docker Images

```bash
# Check for required images
LAKEHOUSE_IMG=$(docker images -q lakehouse-allinone:latest 2>/dev/null)
POLARIS_IMG=$(docker images -q apache-polaris:1.3.0-local 2>/dev/null)

echo "lakehouse-allinone:latest  -> ${LAKEHOUSE_IMG:-(NOT FOUND)}"
echo "apache-polaris:1.3.0-local -> ${POLARIS_IMG:-(NOT FOUND)}"
```

If either image is missing:
- Tell the user which image(s) are missing
- If `--skip-build` was specified, report the error and stop
- Otherwise, ask the user if they want to build the missing image(s)
- Build using the Dockerfiles present in the singlecluster directory:

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

# Build lakehouse image if missing
if [ -z "$LAKEHOUSE_IMG" ]; then
  echo "Building lakehouse-allinone:latest..."
  docker build -t lakehouse-allinone:latest -f Dockerfile.lakehouse .
fi

# Build polaris image if missing
if [ -z "$POLARIS_IMG" ]; then
  echo "Building apache-polaris:1.3.0-local..."
  docker build -t apache-polaris:1.3.0-local -f Dockerfile.polaris .
fi
```

Note: Adjust the Dockerfile names based on what actually exists in the directory. Read the directory listing to find the correct Dockerfile names before building.

### Step 4: Start Containers

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

docker compose up -d
```

Verify containers are up:

```bash
docker compose ps
```

If any container failed to start, check logs and report:

```bash
docker compose logs --tail=30
```

### Step 5: Start Services Inside Lakehouse Container

The lakehouse container uses `command: ["tail","-f","/dev/null"]` so services must be started manually:

```bash
echo "Starting all services inside lakehouse container..."
docker exec lakehouse /opt/start-all.sh
```

Wait a few seconds for services to initialize:

```bash
sleep 5
echo "Services started. Beginning health checks..."
```

### Step 6: Health Check Polling

Run health checks with timeout and retry. Use the health-check script:

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

bash ../../../../../../github/cc-skills/plugins/singlecluster/scripts/health-check.sh
```

Alternatively, check each service individually with retries (max 120 seconds total, 10-second intervals):

```bash
TIMEOUT=${TIMEOUT:-120}
INTERVAL=10
ELAPSED=0

check_service() {
  local name="$1"
  local cmd="$2"
  while [ $ELAPSED -lt $TIMEOUT ]; do
    if eval "$cmd" > /dev/null 2>&1; then
      echo "[OK]   $name"
      return 0
    fi
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
  done
  echo "[FAIL] $name (timeout after ${TIMEOUT}s)"
  return 1
}

FAILED=0

# PostgreSQL
check_service "PostgreSQL" "docker exec lakehouse pg_isready -h localhost" || FAILED=$((FAILED+1))

# HDFS NameNode
check_service "HDFS NameNode" "docker exec lakehouse hdfs dfsadmin -report 2>&1 | grep -q 'Live datanodes'" || FAILED=$((FAILED+1))

# MinIO
check_service "MinIO (port 9100)" "docker exec lakehouse bash -c 'curl -sf http://localhost:9100/minio/health/live'" || FAILED=$((FAILED+1))

# Hive Metastore
check_service "Hive Metastore (port 9083)" "docker exec lakehouse bash -c 'nc -z localhost 9083'" || FAILED=$((FAILED+1))

# HiveServer2
check_service "HiveServer2 (port 10000)" "docker exec lakehouse bash -c 'nc -z localhost 10000'" || FAILED=$((FAILED+1))

# Spark Master
check_service "Spark Master (port 7077)" "docker exec lakehouse bash -c 'nc -z localhost 7077'" || FAILED=$((FAILED+1))

# Polaris
check_service "Polaris (/q/health)" "curl -sf http://localhost:8181/q/health" || FAILED=$((FAILED+1))

if [ $FAILED -gt 0 ]; then
  echo ""
  echo "WARNING: $FAILED service(s) failed health check."
fi
```

If any service fails health check after timeout, warn the user and suggest running `/singlecluster:fix`.

### Step 7: Initialize Polaris

Skip this step if `--skip-polaris-init` was specified.

Check if Polaris CLI script exists and use it to set up the default catalog and namespace:

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

# Check if polaris_cli.sh exists
if [ -f polaris_cli.sh ]; then
  echo "Initializing Polaris default catalog and namespace..."
  bash polaris_cli.sh
else
  echo "polaris_cli.sh not found, skipping Polaris initialization."
  echo "You may need to initialize Polaris manually."
fi
```

If Polaris initialization fails, warn but do not abort -- the cluster is still usable.

### Step 8: Output Service Endpoint Summary

Display a summary table of all service endpoints:

```
============================================================
  Singlecluster Deployment Complete
============================================================

  Service            Endpoint                    Status
  ---------          --------                    ------
  PostgreSQL         localhost:5432              OK
  HDFS NameNode      http://localhost:9870       OK
  HDFS DataNode      http://localhost:9864       OK
  MinIO Console      http://localhost:9101       OK
  MinIO API          http://localhost:9100       OK
  Hive Metastore     thrift://localhost:9083     OK
  HiveServer2        jdbc:hive2://localhost:10000 OK
  Spark Master       spark://localhost:7077      OK
  Spark Web UI       http://localhost:8080       OK
  Polaris Catalog    http://localhost:8181       OK

============================================================
  Tip: Run /singlecluster:status for detailed health info
       Run /singlecluster:fix if any service shows issues
============================================================
```

Populate the Status column with actual health check results from Step 6.

### Important Notes

- All `docker compose` commands must be run from the singlecluster directory
- The lakehouse container requires manual service start via `docker exec lakehouse /opt/start-all.sh`
- Health checks should be retried with back-off, not just checked once
- If a build is needed, warn the user it may take significant time
- Network `share-enterprise-ci` must exist before `docker compose up`
- Do NOT run `docker compose down` without asking the user first
