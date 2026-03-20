# /pxf:docker-down

Stop the PXF development Docker environment.

## Usage

```
/pxf:docker-down [--clean] [--status]
```

**Options:**
- *(no argument)* — Stop containers, preserve state for fast restart
- `--clean` — Remove containers and volumes completely (next start requires full init)
- `--status` — Show current container status and exit

## Instructions

You are executing the `/pxf:docker-down` command. Follow these steps precisely:

### Step 1: Locate PXF Repository

Find the cloudberry-pxf repo root directory containing `dev/docker-down.sh`.

Search strategy:
1. Current working directory or its parents
2. Common paths: `~/workspace/cloudberry-pxf`, `~/github/cloudberry-pxf`

If not found, ask the user for the path. Store as `PXF_REPO`.

### Step 2: Run the Script

```bash
"$PXF_REPO/dev/docker-down.sh" $ARGUMENTS
```

### Step 3: Report Result

**For `--status`:**
Show the docker compose status output.

**For stop (default):**
```
## Containers Stopped

State preserved. Restart quickly with `/pxf:docker-up --skip-init`.
```

**For `--clean`:**
```
## Environment Removed

Containers and volumes deleted. Next `/pxf:docker-up` will do a full initialization.
```

### Important Notes

- Default stop preserves container state — restart is fast with `--skip-init`
- `--clean` removes everything — next startup will rebuild from scratch
- Docker Compose file: `ci/docker/pxf-cbdb-dev/ubuntu/docker-compose.yml`
