# /pxf:test

Run PXF tests inside a Cloudberry dev container: unit tests (server + CLI), FDW installcheck, integration tests, or all.

## Usage

```
/pxf:test [--type unit|integration|fdw|all] [--group <group>] [--test <TestName>] [--protocol <protocol>]
```

**Options:**
- `--type <type>`: Test type to run (default: `unit`)
  - `unit` — Server (Gradle) and CLI (Go) unit tests
  - `fdw` — FDW regression tests via `make installcheck`
  - `integration` — Maven-based integration tests in automation/
  - `all` — Run unit, fdw, and integration sequentially
- `--group <group>`: Test group/category filter (e.g., `HdfsSmokeTest`, `Hive`)
- `--test <TestName>`: Specific test class or test name to run
- `--protocol <protocol>`: Protocol filter for integration tests (e.g., `hdfs`, `s3`, `jdbc`)

## Instructions

You are executing the `/pxf:test` command. Follow these steps precisely:

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

### Step 2: Parse Arguments

Determine the test type from user arguments. Default to `unit` if `--type` is not specified.

If `--type all` is specified, run `unit`, `fdw`, and `integration` sequentially.

### Step 3: Execute Tests by Type

#### Type: `unit`

**Server unit tests (Java/Gradle):**

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/server
  make test
"
```

If `--test` is provided, run a specific test:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/server
  ./gradlew test --tests '*<TestName>*'
"
```

**CLI unit tests (Go):**

```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/cli
  make test
"
```

If `--test` is provided, run a specific test:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/cli
  go test ./... -run '<TestName>'
"
```

#### Type: `fdw`

Requires Greenplum to be running inside the container.

```bash
docker exec $CONTAINER_ID bash -c "
  source /workspace/dist/database/greenplum_path.sh
  $ENV_SCRIPT
  cd $FDW_DIR
  make installcheck
"
```

If the test fails, show the diff from `regression.diffs` if it exists:
```bash
docker exec $CONTAINER_ID bash -c "
  if [ -f '$FDW_DIR/regression.diffs' ]; then
    cat '$FDW_DIR/regression.diffs'
  fi
"
```

#### Type: `integration`

Integration tests require:
- PXF service running (`pxf status`)
- Greenplum database running
- External data sources configured (HDFS, Hive, S3, etc.)

Pre-flight checks:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  pxf status
  psql -d postgres -c 'SELECT 1;'
"
```

If PXF is not running or GPDB is unreachable, tell the user:

> Integration tests require both PXF and Greenplum to be running. Run `/pxf:setup` first.

Run integration tests:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/automation
  make GROUP=<group> TEST=<TestName> PROTOCOL=<protocol>
"
```

Omit `GROUP=`, `TEST=`, or `PROTOCOL=` if the corresponding option was not provided.

If no options are provided, run all integration tests:
```bash
docker exec $CONTAINER_ID bash -c "
  $ENV_SCRIPT
  cd $PXF_SRC/automation
  make
"
```

#### Type: `all`

Run sequentially: `unit` then `fdw` then `integration`. Continue to the next type even if the previous one has failures. Collect results from all types.

### Step 4: Output Results Summary

After all tests complete, display a summary:

```
## PXF Test Results

Container: <CONTAINER_NAME> (<CONTAINER_ID>)
Test Type: <type>

### Results
| Component    | Tests | Passed | Failed | Skipped | Status  |
|-------------|-------|--------|--------|---------|---------|
| Server Unit | 142   | 140    | 2      | 0       | FAILED  |
| CLI Unit    | 38    | 38     | 0      | 0       | PASSED  |
| FDW         | 12    | 12     | 0      | 0       | PASSED  |
| Integration | —     | —      | —      | —       | SKIPPED |

### Failures (if any)
- Server: TestClassName.testMethod — assertion error at line 45
- ...

Overall: FAILED (2 failures)
```

Parse the test output to extract counts where possible. If exact counts cannot be parsed, report the exit code and show relevant error output.

### Important Notes

- All commands execute inside the detected Cloudberry dev container via `docker exec`
- Unit tests can run without a running database
- FDW tests require a running Greenplum instance
- Integration tests require both PXF and Greenplum running, plus configured external data sources
- When `--type all` is used, failures in one type do not block subsequent types
- For integration test failures, check `$PXF_SRC/automation/target/surefire-reports/` for detailed reports
- Show the most relevant failure output directly; do not dump entire logs unless the user requests it
