# /pxf:build

Build and deploy PXF components inside a Cloudberry dev container: server (Java/Gradle), CLI (Go), FDW (C), or auto-detect changed components from git diff.

## Usage

```
/pxf:build [server|cli|fdw|all]
```

**Arguments:**
- `server` — Build the PXF server (Java/Gradle)
- `cli` — Build the PXF CLI (Go)
- `fdw` — Build the PXF FDW extension (C)
- `all` — Build all three components
- *(no argument)* — Auto-detect which components changed using `git diff` and build only those

## Instructions

You are executing the `/pxf:build` command. Follow these steps precisely:

### Step 1: Detect Cloudberry Dev Container

```bash
docker ps --filter "status=running" --format "{{.ID}} {{.Names}} {{.Image}}" | grep "docker.hashdata.dev/hashdata-releng"
```

If no container is found, tell the user:

> No running Cloudberry dev container detected (image prefix: docker.hashdata.dev/hashdata-releng). Please start the container first.

Stop here if no container is found. Extract `CONTAINER_ID` from the first match.

Locate the PXF source path (same logic as `/pxf:setup` Step 3). Store as `PXF_SRC`.

Also locate the FDW directory. Store as `FDW_DIR`.

Prepare the environment:
```bash
ENV_SCRIPT="source ~/.bashrc"
```

### Step 2: Determine Components to Build

**If an argument is provided** (`server`, `cli`, `fdw`, or `all`):
Use the specified component(s) directly.

**If no argument is provided** — auto-detect from git diff:

```bash
docker exec $CONTAINER_ID bash -c "
  cd $PXF_SRC
  git diff --name-only HEAD
  git diff --name-only --cached HEAD
  git diff --name-only HEAD~1..HEAD 2>/dev/null || true
"
```

Analyze the changed file paths to determine which components need building:

| Changed path pattern      | Component |
|--------------------------|-----------|
| `server/`                | server    |
| `cli/`                   | cli       |
| `fdw/`                   | fdw       |
| `gpcontrib/pxf_fdw/`     | fdw       |
| `build.gradle`, `Makefile` (root) | all |

If no changes are detected:

> No changes detected in PXF source. Specify a component to build: `/pxf:build server|cli|fdw|all`

Stop and wait for user input.

Show the user what will be built:

```
## Build Plan

Detected changes in: server, cli
Components to build: server, cli

Proceed?
```

Wait for user confirmation before building.

### Step 3: Build Components

Build the determined components in order: server, cli, fdw.

#### Build Server (Java/Gradle)

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/server
  make install
"
```

Record the exit code and build duration.

If the build fails, show the error and ask the user:

> Server build failed. Retry, skip, or show full log?

- **Retry**: Re-run the build
- **Skip**: Mark as failed, continue to next component
- **Show log**: Display the full output, then ask again

#### Build CLI (Go)

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/cli
  make install
"
```

Record the exit code and build duration. Follow the same retry/skip flow on failure.

#### Build FDW (C)

```bash
docker exec $CONTAINER_ID bash -c "
  source /workspace/dist/database/greenplum_path.sh
  $ENV_SCRIPT
  cd $FDW_DIR
  make && make install
"
```

Record the exit code and build duration. Follow the same retry/skip flow on failure.

### Step 4: Restart PXF Service

After all builds complete, restart PXF to pick up changes:

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  pxf stop 2>/dev/null || true
  pxf start
"
```

If PXF was not previously initialized (e.g., `pxf start` fails with "not initialized"), run:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  pxf init
  pxf start
"
```

Verify PXF is running:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  pxf status
"
```

If PXF fails to start and only non-server components were built, this is acceptable. Note it in the summary.

### Step 5: Output Build Summary

```
## PXF Build Summary

Container: <CONTAINER_NAME> (<CONTAINER_ID>)
Detection: <auto-detect | manual>

### Build Results
| Component | Status  | Duration |
|-----------|---------|----------|
| Server    | success | 45s      |
| CLI       | success | 12s      |
| FDW       | skipped | —        |

### Service
PXF Status: running (restarted)

Build complete. Run `/pxf:test` to verify.
```

### Important Notes

- All commands execute inside the detected Cloudberry dev container via `docker exec`
- Auto-detect mode uses `git diff` to minimize build time — only changed components are rebuilt
- The greenplum_path.sh source is required for FDW builds
- PXF service is always restarted after builds to pick up new binaries
- If only FDW was built and PXF is not initialized, skip the restart
- Build failures in one component do not block building other components
- Keep output concise — show build status and errors, not full compilation logs
