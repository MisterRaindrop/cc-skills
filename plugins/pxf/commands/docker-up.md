# /pxf:docker-up

Start the PXF development Docker environment (pxf-cbdb-dev container with Cloudberry, Hadoop, Hive, HBase, MinIO).

## Usage

```
/pxf:docker-up [--skip-init]
```

**Options:**
- `--skip-init` — Start containers but skip the entrypoint initialization
- *(no argument)* — Full startup: build images, start containers, run entrypoint, verify health

## Instructions

You are executing the `/pxf:docker-up` command. Follow these steps precisely:

### Step 1: Locate PXF Repository

Find the cloudberry-pxf repo root directory. The repo must contain `dev/docker-up.sh`.

Search strategy:
1. Current working directory or its parents
2. Common paths: `~/workspace/cloudberry-pxf`, `~/github/cloudberry-pxf`

If not found, ask the user for the path.

Store the resolved path as `PXF_REPO`.

### Step 2: Run the Script

Execute the docker-up script:

```bash
"$PXF_REPO/dev/docker-up.sh" $ARGUMENTS
```

This script will:
1. Check if `pxf-cbdb-dev` container is already running
2. If not running, run `docker compose up -d --build` using `ci/docker/pxf-cbdb-dev/ubuntu/docker-compose.yml`
3. Execute `entrypoint.sh` inside the container (builds Cloudberry, PXF, starts Hadoop/Hive/HBase/MinIO)
4. Verify PXF health endpoint at `http://localhost:5888/actuator/health`

### Step 3: Report Result

If the script succeeds, show the connection info:

```
## Environment Ready

Container:  pxf-cbdb-dev
SSH:        ssh -p 2222 gpadmin@localhost (password: cbdb@123)
PXF:        http://localhost:5888/actuator/health
PGPORT:     7000 (inside container)

Run `/pxf:build` after code changes, `/pxf:test` to run tests.
```

If the script fails, show the error output and suggest:
- Check Docker is running: `docker info`
- Check logs: `docker logs pxf-cbdb-dev`
- Retry with `--skip-init` if the container is already partially set up

### Important Notes

- First startup takes 10-20 minutes (builds Cloudberry from source, sets up Hadoop stack)
- Subsequent startups are much faster if using `--skip-init`
- The container mounts the PXF repo at `/home/gpadmin/workspace/cloudberry-pxf`
- Docker Compose file: `ci/docker/pxf-cbdb-dev/ubuntu/docker-compose.yml`
- Entrypoint script: `ci/docker/pxf-cbdb-dev/ubuntu/script/entrypoint.sh`
