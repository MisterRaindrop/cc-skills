# /pxf:test

Run PXF automation tests inside the pxf-cbdb-dev Docker container and display parsed results.

## Usage

```
/pxf:test [GROUP] [TEST=ClassName] [TEST=ClassName#method] [--no-parse] [--keep-data]
```

**Test groups:**

| Group | Description |
|-------|------------|
| `smoke` | Smoke tests (default) |
| `sanity` | Sanity tests |
| `hdfs` | HDFS read/write tests |
| `hive` | Hive integration tests |
| `hbase` | HBase integration tests |
| `hcatalog` | HCatalog tests |
| `hcfs` | HCFS tests |
| `jdbc` | JDBC connector tests |
| `profile` | Profile tests |
| `proxy` | Proxy/impersonation tests |
| `s3` | S3/MinIO tests |
| `features` | Feature tests |
| `gpdb` | GPDB integration tests |
| `gpdb_fdw` | GPDB FDW tests |
| `load` | Load/benchmark tests |
| `performance` | Performance tests |
| `server` | Server unit tests (gradlew) |
| `cli` | CLI unit tests (go test) |
| `fdw` | FDW installcheck |
| `pxf_extension` | PXF extension version tests |
| `all` | Run all test groups |

**Options:**
- `TEST=ClassName` — Run a specific test class
- `TEST=ClassName#method` — Run a specific test method
- `--no-parse` — Skip result parsing
- `--keep-data` — Keep test data on HDFS between runs

## Instructions

You are executing the `/pxf:test` command. Follow these steps precisely:

### Step 1: Locate PXF Repository

Find the cloudberry-pxf repo root directory containing `dev/test.sh`.

Search strategy:
1. Current working directory or its parents
2. Common paths: `~/workspace/cloudberry-pxf`, `~/github/cloudberry-pxf`

If not found, ask the user for the path. Store as `PXF_REPO`.

### Step 2: Verify Container is Running

```bash
docker ps --format '{{.Names}}' | grep -q '^pxf-cbdb-dev$'
```

If not running, tell the user to start it with `/pxf:docker-up`.

### Step 3: Run Tests

```bash
"$PXF_REPO/dev/test.sh" $ARGUMENTS
```

The script:
1. Dispatches to the correct test runner based on group
2. For automation tests: runs via `run_tests.sh` inside the container
3. For server/cli/fdw: runs the appropriate unit test command
4. Automatically calls `parse-results.sh` to display results

### Step 4: Report Results

The script already calls `parse-results.sh` for automation tests. For additional detail or if `--no-parse` was used, you can run:

```bash
"$PXF_REPO/dev/parse-results.sh"
```

Present the results clearly:

```
## Test Results: <GROUP>

Total: 42  |  Passed: 40  |  Failed: 2  |  Skipped: 0

### Failures
- org.example.FooTest#testBar — expected 42 but got 0
- org.example.BazTest#testQux — NullPointerException at line 99
```

### Step 5: On Failure, Offer Next Steps

If tests failed:
1. Show the failure details from surefire reports
2. Offer to read the relevant test source code
3. Offer to check PXF logs: `docker exec pxf-cbdb-dev cat /home/gpadmin/pxf-base/logs/pxf-service.log`
4. Suggest re-running a specific test: `/pxf:test <group> TEST=FailedTestClass#failedMethod`

### Important Notes

- All tests run inside the `pxf-cbdb-dev` container
- Automation tests require the full environment (Cloudberry + PXF + Hadoop stack)
- Server unit tests (`server` group) can run without the full stack
- Test reports are saved to `automation/test_artifacts/<group>/`
- Surefire XML reports are at `automation/target/surefire-reports/`
- The `run_tests.sh` script handles group-specific setup (e.g., Hive cleanup before hive tests, MinIO setup before s3 tests)

### Examples

```bash
# Run smoke tests (default)
/pxf:test

# Run HDFS tests
/pxf:test hdfs

# Run a specific test class
/pxf:test smoke TEST=HdfsSmokeTest

# Run a specific test method
/pxf:test hdfs TEST=HdfsReadableTextTest#testTextFormatSimple

# Run server unit tests
/pxf:test server
```
