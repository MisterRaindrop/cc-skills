# /datalake:test

Run datalake_fdw automated tests: smoke, feature, performance, or individual test categories.

## Usage

```
/datalake:test [smoke|feature|performance|all|<category>]
```

**Arguments:**
- `smoke` — Run smoke tests (quick sanity checks)
- `feature` — Run feature tests
- `performance` — Run performance tests
- `all` — Run all test suites via `scripts/test/run_all_tests.sh`
- `<category>` — Run a specific test category (e.g., `s3`, `iceberg`, `hdfs`, `hive`, `orc`, `parquet`, `avro`)
- *(no argument)* — Default to `smoke`

## Instructions

You are executing the `/datalake:test` command. Follow these steps precisely:

**Important paths:**
```
DB_ROOT=/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella2/hashdata-lightning-umbrella/database
AUTOMATION_DIR=$DB_ROOT/contrib/datalake_fdw/automation
FDW_DIR=$DB_ROOT/contrib/datalake_fdw
```

### Key Reference Information

**Automation Makefile targets:**
- `make check-services` — Verify required services are running
- `make smoke-test` — Smoke tests (depends on check-services)
- `make feature-test` — Feature tests
- `make performance-test` — Performance tests
- `make clean` — Clean test artifacts

**Test categories** (located in `$AUTOMATION_DIR/sqlrepo/smoke/<category>/`):
Each category has its own Makefile using pg_regress installcheck.

**Configuration:**
- `$AUTOMATION_DIR/config/test_config.env` — Centralized test config
- PGHOST: localhost, PGPORT: 5432, PGDATABASE: postgres, PGUSER: gpadmin
- Hive: lakehouse:9083 (metastore), lakehouse:10000 (HS2)
- MinIO: lakehouse:9100 (admin/password)
- HDFS: lakehouse:8020
- Spark: lakehouse:7077
- Polaris: polaris:8181

**Key scripts:**
- `$AUTOMATION_DIR/scripts/setup/check_services.sh` — Service health check
- `$AUTOMATION_DIR/scripts/test/run_smoke_tests.sh` — Smoke test runner
- `$AUTOMATION_DIR/scripts/utils/common_functions.sh` — Shared utilities

**FDW built-in regression tests** (via `make installcheck` in `$FDW_DIR`):
- setup, hive_connecter_*, orc_read, parquet_read, avro_read, iceberg_test, etc.

---

### Step 1: Pre-flight Checks

Verify the test environment is ready:

```bash
cd $AUTOMATION_DIR

# Check services
bash scripts/setup/check_services.sh
```

If services are not running, tell the user:

> Required services are not running. Please start the environment first with `/datalake:singlecluster deploy`.

Also verify that datalake_fdw is built and installed:
```bash
ls $(pg_config --pkglibdir)/datalake_fdw.so 2>/dev/null
```

If not found:
> datalake_fdw is not installed. Run `/datalake:build` first.

### Step 2: Parse Arguments

Determine the test type. Default to `smoke` if no argument.

### Step 3: Execute Tests

#### Type: `smoke`

```bash
cd $AUTOMATION_DIR
make smoke-test
```

This runs `check-services` first, then `scripts/test/run_smoke_tests.sh`.

#### Type: `feature`

```bash
cd $AUTOMATION_DIR
make feature-test
```

#### Type: `performance`

```bash
cd $AUTOMATION_DIR
make performance-test
```

#### Type: `all`

```bash
cd $AUTOMATION_DIR
# If run_all_tests.sh exists, use it
if [ -f scripts/test/run_all_tests.sh ]; then
  bash scripts/test/run_all_tests.sh
else
  # Otherwise run sequentially
  make smoke-test
  make feature-test
  make performance-test
fi
```

Continue to the next suite even if the previous one fails. Collect results from all suites.

#### Type: `<category>` (specific category)

For a specific test category like `s3`, `iceberg`, `hdfs`, `hive`:

```bash
cd $AUTOMATION_DIR/sqlrepo/smoke/<category>
make installcheck
```

If the category directory doesn't exist, check if it's a FDW regression test instead:
```bash
cd $FDW_DIR
make installcheck REGRESS="<category>"
```

#### FDW Regression Tests

To run the full built-in regression suite:
```bash
cd $FDW_DIR
make installcheck
```

If tests fail, show the regression diffs:
```bash
if [ -f regression.diffs ]; then
  cat regression.diffs
fi
```

### Step 4: Output Results Summary

After tests complete, parse output and display:

```
## Datalake FDW Test Results

Test Type: smoke
Automation Dir: $AUTOMATION_DIR

| Category    | Tests | Passed | Failed | Status  |
|-------------|-------|--------|--------|---------|
| s3          | 2     | 2      | 0      | PASSED  |
| iceberg     | 3     | 2      | 1      | FAILED  |
| hdfs        | 4     | 4      | 0      | PASSED  |
| hive        | 5     | 5      | 0      | PASSED  |

Overall: FAILED (1 failure)
```

If exact counts cannot be parsed from the output, report the exit code and show relevant error output.

For failures, automatically show the `regression.diffs` content:
```bash
find $AUTOMATION_DIR -name "regression.diffs" -exec echo "=== {} ===" \; -exec cat {} \;
```

### Important Notes

- All tests require the singlecluster environment running (`/datalake:singlecluster deploy`)
- datalake_fdw must be compiled and installed before running tests
- Smoke tests use pg_regress installcheck (connects to running database)
- PGPORT defaults to 5432 from test_config.env — some Makefiles may use 7000 instead
- Test reports are saved to `$AUTOMATION_DIR/reports/`
- When `all` is used, failures in one suite do not block subsequent suites
- Show the most relevant failure output directly; do not dump entire logs unless the user requests it
- Clean up previous test artifacts with `make clean` in $AUTOMATION_DIR if needed
