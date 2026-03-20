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

### Step 1: Run Tests

```bash
"${CLAUDE_SKILL_DIR}/../scripts/test.sh" $ARGUMENTS
```

The script:
1. Locates the cloudberry-pxf repo automatically
2. Dispatches to the correct test runner based on group
3. For automation tests: runs via `run_tests.sh` inside the container
4. For server/cli/fdw: runs the appropriate unit test command
5. Automatically calls `parse-results.sh` to display results

### Step 2: Present Results

The script already calls `parse-results.sh` for automation tests. For additional detail or if `--no-parse` was used, you can run:

```bash
"${CLAUDE_SKILL_DIR}/../scripts/parse-results.sh"
```

Present the results clearly:

```
## Test Results: <GROUP>

Total: 42  |  Passed: 40  |  Failed: 2  |  Skipped: 0

### Failures
- org.example.FooTest#testBar — expected 42 but got 0
- org.example.BazTest#testQux — NullPointerException at line 99
```

### Step 3: On Failure, Offer Next Steps

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

### Examples

```bash
/pxf:test                    # Run smoke tests (default)
/pxf:test hdfs               # Run HDFS tests
/pxf:test smoke TEST=HdfsSmokeTest          # Specific test class
/pxf:test hdfs TEST=HdfsReadableTextTest#testTextFormatSimple  # Specific method
/pxf:test server             # Server unit tests
```
