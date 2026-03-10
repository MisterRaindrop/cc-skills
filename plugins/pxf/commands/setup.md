# /pxf:setup

Full PXF environment setup inside a Cloudberry dev container: detect container, verify prerequisites, configure environment variables, build all components (server/cli/fdw), initialize PXF, and validate the installation.

## Usage

```
/pxf:setup
```

## Instructions

You are executing the `/pxf:setup` command. Follow these steps precisely:

### Step 1: Detect Cloudberry Dev Container

Run the detection script or equivalent logic to find a running Cloudberry dev container:

```bash
docker ps --filter "status=running" --format "{{.ID}} {{.Names}} {{.Image}}" | grep "docker.hashdata.dev/hashdata-releng"
```

If no container is found, tell the user:

> No running Cloudberry dev container detected (image prefix: docker.hashdata.dev/hashdata-releng). Please start the container first.

Stop here if no container is found.

Extract `CONTAINER_ID` and `CONTAINER_NAME` from the first match. All subsequent commands will be executed inside this container via `docker exec`.

### Step 2: Verify Container Environment

Check that essential tools are available inside the container:

```bash
docker exec $CONTAINER_ID bash -c "pg_config --version"
docker exec $CONTAINER_ID bash -c "java -version 2>&1 | head -1"
docker exec $CONTAINER_ID bash -c "go version"
```

If any tool is missing, report which ones are unavailable and stop. All three (pg_config, java, go) are required.

### Step 3: Locate PXF Source Path

Search for the PXF source directory inside the container:

```bash
docker exec $CONTAINER_ID bash -c "
  for dir in /workspace/cloudberry-pxf /workspace/pxf /home/gpadmin/cloudberry-pxf /home/gpadmin/pxf; do
    if [ -d \"\$dir\" ] && [ -f \"\$dir/server/build.gradle\" ]; then
      echo \"\$dir\"
      exit 0
    fi
  done
  echo 'NOT_FOUND'
  exit 1
"
```

If not found, ask the user to provide the PXF source path inside the container. Store the resolved path as `PXF_SRC`.

Verify the expected subdirectories exist:

```bash
docker exec $CONTAINER_ID bash -c "
  ls -d $PXF_SRC/server $PXF_SRC/cli $PXF_SRC/fdw 2>/dev/null || echo 'MISSING_DIRS'
"
```

Also locate the FDW path within the Cloudberry database source tree:

```bash
docker exec $CONTAINER_ID bash -c "
  for dir in /workspace/dist/database-main/gpcontrib/pxf_fdw /workspace/database-main/gpcontrib/pxf_fdw; do
    if [ -d \"\$dir\" ]; then
      echo \"\$dir\"
      exit 0
    fi
  done
  # Fallback: use fdw/ inside PXF source
  if [ -d '$PXF_SRC/fdw' ]; then
    echo '$PXF_SRC/fdw'
    exit 0
  fi
  echo 'NOT_FOUND'
  exit 1
"
```

Store the resolved FDW directory as `FDW_DIR`.

### Step 4: Check and Persist Environment Variables

For each of the following environment variables, check if it is already set inside the container. Only write variables that are missing. Never overwrite existing values.

```bash
docker exec $CONTAINER_ID bash -c "
  echo \"JAVA_HOME=\${JAVA_HOME:-UNSET}\"
  echo \"GOPATH=\${GOPATH:-UNSET}\"
  echo \"PXF_HOME=\${PXF_HOME:-UNSET}\"
  echo \"PXF_BASE=\${PXF_BASE:-UNSET}\"
"
```

For any variable that is `UNSET`, detect the correct value and append it to `~/.bashrc`:

**JAVA_HOME** — detect from Java:
```bash
docker exec $CONTAINER_ID bash -c "
  java -XshowSettings:property 2>&1 | grep 'java.home' | awk '{print \$NF}'
"
```
If that fails, fall back to:
```bash
docker exec $CONTAINER_ID bash -c "ls -d /usr/lib/jvm/java-*-openjdk-* 2>/dev/null | head -1"
```

**GOPATH** — default `$HOME/go`

**PXF_HOME** — default `/usr/local/pxf`

**PXF_BASE** — default `$PXF_HOME`

Append missing vars to `~/.bashrc`:
```bash
docker exec $CONTAINER_ID bash -c "
  # Only append if not already present in .bashrc
  grep -q 'export JAVA_HOME=' ~/.bashrc 2>/dev/null || echo 'export JAVA_HOME=<detected_value>' >> ~/.bashrc
  grep -q 'export GOPATH=' ~/.bashrc 2>/dev/null || echo 'export GOPATH=\$HOME/go' >> ~/.bashrc
  grep -q 'export PXF_HOME=' ~/.bashrc 2>/dev/null || echo 'export PXF_HOME=/usr/local/pxf' >> ~/.bashrc
  grep -q 'export PXF_BASE=' ~/.bashrc 2>/dev/null || echo 'export PXF_BASE=\$PXF_HOME' >> ~/.bashrc
"
```

Append PATH and greenplum_path.sh source if not already present:
```bash
docker exec $CONTAINER_ID bash -c "
  grep -q 'PXF_HOME/bin' ~/.bashrc 2>/dev/null || echo 'export PATH=\$PXF_HOME/bin:\$GOPATH/bin:\$PATH' >> ~/.bashrc
  grep -q 'greenplum_path.sh' ~/.bashrc 2>/dev/null || echo 'source /workspace/dist/database/greenplum_path.sh' >> ~/.bashrc
"
```

Build an `ENV_SCRIPT` string that sources `~/.bashrc` so all subsequent commands inherit the vars:
```bash
ENV_SCRIPT="source ~/.bashrc"
```

### Step 5: Build Server (Java/Gradle)

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/server
  make install
"
```

If the build fails, show the error output and ask the user:

> Server build failed. Would you like to see the full log, retry, or skip?

- **Retry**: Re-run the build
- **Skip**: Continue to next component (warn that PXF may not function)
- **Show log**: Display the full output, then ask again

### Step 6: Build CLI (Go)

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/cli
  make install
"
```

If the build fails, follow the same retry/skip flow as Step 5.

### Step 7: Build FDW (C)

```bash
docker exec $CONTAINER_ID bash -c "
  source /workspace/dist/database/greenplum_path.sh
  $ENV_SCRIPT
  cd $FDW_DIR
  make && make install
"
```

If the build fails, follow the same retry/skip flow as Step 5.

### Step 8: Initialize and Start PXF

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  pxf init
  pxf start
"
```

If `pxf init` or `pxf start` fails, show the error and ask the user how to proceed.

Verify PXF is running:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  pxf status
"
```

### Step 9: Validate Installation

Create the PXF FDW extension in the database:

```bash
docker exec $CONTAINER_ID bash -c "
  source /workspace/dist/database/greenplum_path.sh
  psql -d postgres -c 'CREATE EXTENSION IF NOT EXISTS pxf_fdw;'
"
```

If the extension creation fails, show the error. PXF setup is still partially complete.

### Step 10: Output Install Summary

Display a summary table:

```
## PXF Setup Complete

Container: <CONTAINER_NAME> (<CONTAINER_ID>)
PXF Source: <PXF_SRC>
FDW Source: <FDW_DIR>

### Environment Variables
| Variable    | Value                                    | Status       |
|-------------|------------------------------------------|--------------|
| JAVA_HOME   | /usr/lib/jvm/java-11-openjdk-amd64       | set          |
| GOPATH      | /root/go                                 | set          |
| PXF_HOME    | /usr/local/pxf                           | set          |
| PXF_BASE    | /usr/local/pxf                           | set          |
| PATH        | (includes $PXF_HOME/bin, $GOPATH/bin)    | updated      |
| GP source   | /workspace/dist/database/greenplum_path.sh | sourced    |

### Build Results
| Component | Status    |
|-----------|-----------|
| Server    | success   |
| CLI       | success   |
| FDW       | success   |

### Service
PXF Status: running
Extension:  pxf_fdw installed

Ready to use. Run `/pxf:test` to verify or `/pxf:build` after code changes.
```

### Important Notes

- All commands execute inside the detected Cloudberry dev container via `docker exec`
- Environment variables are persisted to `~/.bashrc` so they survive container restarts
- Existing env vars are NEVER overwritten — only missing ones are added
- The greenplum_path.sh source is critical for FDW builds and psql access
- If any build component is skipped, warn the user in the summary
