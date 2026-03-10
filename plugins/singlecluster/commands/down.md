# /singlecluster:down

Full stop and cleanup of the Singlecluster environment. Stops containers, removes data, and optionally removes Docker images.

## Usage

```
/singlecluster:down [--keep-data] [--keep-images]
```

**Options:**
- `--keep-data`: Do not remove the `data/` directory (preserves HDFS, metastore-db, warehouse, logs)
- `--keep-images`: Do not remove Docker images (lakehouse-allinone, apache-polaris)

## Instructions

You are executing the `/singlecluster:down` command. Follow these steps precisely:

**Important:** The singlecluster directory is located at:
```
/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster
```

### Step 1: Pre-Flight Check

Verify the current state of the cluster:

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

docker compose ps -a 2>/dev/null || echo "No containers found"
```

If no containers are found and no data directory exists, report:

> Singlecluster is not deployed. Nothing to clean up.

Stop execution.

### Step 2: Confirm Teardown

Present a clear summary of what will be destroyed:

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

echo "=== Containers to stop ==="
docker compose ps -a 2>/dev/null

echo ""
echo "=== Data to remove ==="
du -sh data/* 2>/dev/null || echo "(no data directory)"

echo ""
echo "=== Images to remove ==="
docker images --format "{{.Repository}}:{{.Tag}}  {{.Size}}" | grep -E 'lakehouse-allinone|apache-polaris' || echo "(no matching images)"
```

Ask the user for confirmation:

> **WARNING: This will permanently destroy the following:**
> - Stop and remove containers: `lakehouse`, `polaris`
> - Delete all data: HDFS data, metastore-db, warehouse, logs
> - Remove Docker images: `lakehouse-allinone:latest`, `apache-polaris:1.3.0-local`
>
> This action is **irreversible**. Proceed? (yes/no)

Adjust the warning based on `--keep-data` and `--keep-images` flags:
- If `--keep-data`: omit the data deletion line
- If `--keep-images`: omit the image removal line

If the user does not confirm, abort immediately.

### Step 3: Stop and Remove Containers

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

echo "Stopping containers..."
docker compose down
echo "Containers stopped and removed."
```

Verify containers are gone:

```bash
docker ps -a --filter name=lakehouse --filter name=polaris --format '{{.Names}} {{.Status}}'
```

### Step 4: Remove Data Directory

Skip if `--keep-data` was specified.

```bash
cd /Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella/database-main/contrib/datalake_fdw/automation/docker/singlecluster

if [ -d data ]; then
  echo "Removing data directory..."
  rm -rf data/
  echo "Data directory removed."
else
  echo "No data directory found, skipping."
fi
```

### Step 5: Remove Docker Images

Skip if `--keep-images` was specified.

```bash
echo "Removing Docker images..."

docker rmi lakehouse-allinone:latest 2>/dev/null && echo "Removed: lakehouse-allinone:latest" || echo "Image not found: lakehouse-allinone:latest"

docker rmi apache-polaris:1.3.0-local 2>/dev/null && echo "Removed: apache-polaris:1.3.0-local" || echo "Image not found: apache-polaris:1.3.0-local"
```

### Step 6: Output Cleanup Confirmation

```
============================================================
  Singlecluster Teardown Complete
============================================================

  Action                          Status
  ------                          ------
  Containers stopped & removed    Done
  Data directory removed          Done / Skipped (--keep-data)
  Docker images removed           Done / Skipped (--keep-images)

============================================================
  Freed disk space: ~X.X GB
  To redeploy: /singlecluster:deploy
============================================================
```

Calculate freed disk space from the `du` and `docker images` output gathered in Step 2.

### Important Notes

- ALWAYS require explicit user confirmation before proceeding with teardown
- The `data/` directory may contain important data -- warn prominently
- Image removal saves significant disk space but means rebuild is needed on next deploy
- If `docker compose down` fails, try `docker compose down --remove-orphans`
- Do NOT remove the `share-enterprise-ci` network -- it may be used by other services
- Do NOT remove any files outside the `data/` directory (e.g., docker-compose.yml, scripts)
