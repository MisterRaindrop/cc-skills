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

### Step 1: Run the Script

Execute the docker-up script bundled with this plugin:

```bash
"${CLAUDE_SKILL_DIR}/../scripts/docker-up.sh" $ARGUMENTS
```

The script will automatically locate the cloudberry-pxf repo (searches CWD parents and common paths). It then:
1. Checks if `pxf-cbdb-dev` container is already running
2. If not running, runs `docker compose up -d --build`
3. Executes `entrypoint.sh` inside the container (builds Cloudberry, PXF, starts Hadoop/Hive/HBase/MinIO)
4. Verifies PXF health endpoint at `http://localhost:5888/actuator/health`

### Step 2: Report Result

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
- If repo not found, `cd` into the cloudberry-pxf directory first

### Important Notes

- First startup takes 10-20 minutes (builds Cloudberry from source, sets up Hadoop stack)
- Subsequent startups are much faster if using `--skip-init`
- The container mounts the PXF repo at `/home/gpadmin/workspace/cloudberry-pxf`
