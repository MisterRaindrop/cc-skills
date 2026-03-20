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

### Step 1: Run the Script

```bash
"${CLAUDE_SKILL_DIR}/../scripts/docker-down.sh" $ARGUMENTS
```

### Step 2: Report Result

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
