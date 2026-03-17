# /datalake:coverage

Collect, analyze, and report code coverage for datalake_fdw using lcov/gcov.

## Usage

```
/datalake:coverage [collect|report|analyze|reset|loop]
```

**Arguments:**
- `collect` — Capture gcov coverage data and produce lcov summary
- `report` — Generate HTML coverage report from collected data
- `analyze` — Parse uncovered code, group by file, suggest test directions
- `reset` — Delete all `.gcda` files to start fresh
- `loop` — Automated iteration: collect → analyze → generate tests → run → collect (until target %)
- *(no argument)* — Default to `collect`

## Instructions

You are executing the `/datalake:coverage` command. Follow these steps precisely:

**Important paths:**
```
DB_ROOT=/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella2/hashdata-lightning-umbrella/database
FDW_DIR=$DB_ROOT/contrib/datalake_fdw
FDW_SRC=$FDW_DIR/src
```

### Key Reference Information

**Prerequisites:**
- datalake_fdw must be compiled with `--enable-coverage` (use `/datalake:build coverage`)
- Tests must have been run to generate `.gcda` files
- `lcov` and `genhtml` must be available on the system

**Source → SQL Mapping Table:**

| Source File | SQL Operation | Backend |
|---|---|---|
| `datalake_fdw.c` | SELECT/INSERT/UPDATE/DELETE/EXPLAIN/ANALYZE | All |
| `provider/parquet/*` | Read/write parquet format tables | Parquet |
| `provider/orc/*` | Read/write ORC format tables | ORC |
| `provider/avro/*` | Read/write Avro format tables | Avro |
| `provider/archive/*` | Read/write text/CSV tables | Text/CSV |
| `provider/iceberg/*` | Iceberg table read/write | Iceberg |
| `provider/hudi/*` | Hudi table read | Hudi |
| `dlproxy/filters.c` | WHERE clause pushdown | All |
| `am_iceberg/*` | CREATE/DROP ICEBERG TABLE, DML, VACUUM | Iceberg AM |
| `iceberg_*_fdw/*` | FOREIGN CATALOG/VOLUME management | Iceberg |
| `common/partition_selector.c` | Partition pruning | Hive |

**Known Unreachable Code:**

| Category | Reason |
|---|---|
| `dlproxy/libchurl.c` error paths | Requires network fault injection |
| Kerberos authentication paths | Requires KDC setup |
| Hudi complex merge paths | Requires specific data state |
| DLProxy protocol paths | Requires DLProxy service |

**Excluded Files** (third-party, not meaningful for coverage):
- `provider/common/roaring.c`
- `provider/common/mdb.c`
- `provider/common/midl.c`

---

### Subcommand: `collect`

#### Step 1: Verify Coverage Build

```bash
# Check for .gcno files (produced at compile time with --coverage)
GCNO_COUNT=$(find $FDW_SRC -name "*.gcno" | wc -l)
echo "Found $GCNO_COUNT .gcno files"

if [ "$GCNO_COUNT" -eq 0 ]; then
  echo "No .gcno files found. Build with coverage first: /datalake:build coverage"
  exit 1
fi

# Check for .gcda files (produced at runtime after tests)
GCDA_COUNT=$(find $FDW_SRC -name "*.gcda" | wc -l)
echo "Found $GCDA_COUNT .gcda files"

if [ "$GCDA_COUNT" -eq 0 ]; then
  echo "No .gcda files found. Run tests first: /datalake:test smoke"
fi
```

#### Step 2: Capture Coverage Data

```bash
cd $FDW_DIR

# Capture baseline (all zeros — what was compiled)
lcov --capture --initial -d src -o lcov_base.info --gcov-tool gcov --no-external -q

# Capture test coverage (actual execution)
lcov --capture -d src -o lcov_test.info --gcov-tool gcov --no-external -q

# Combine baseline + test
lcov -a lcov_base.info -a lcov_test.info -o lcov_combined.info

# Remove third-party/uninteresting files
lcov --remove lcov_combined.info \
  '*/provider/common/roaring.c' \
  '*/provider/common/mdb.c' \
  '*/provider/common/midl.c' \
  -o lcov_filtered.info

# Show summary
lcov --summary lcov_filtered.info
```

#### Step 3: Display Summary

Parse the lcov summary output and display:

```
## Datalake FDW Coverage Summary

| Metric     | Hit    | Total  | Coverage |
|------------|--------|--------|----------|
| Lines      | 3500   | 12000  | 29.2%    |
| Functions  | 150    | 400    | 37.5%    |
| Branches   | 800    | 3000   | 26.7%    |

Coverage data: $FDW_DIR/lcov_filtered.info
```

---

### Subcommand: `report`

Generate an HTML coverage report:

```bash
cd $FDW_DIR
genhtml lcov_filtered.info \
  -o coverage-html \
  --title "datalake_fdw" \
  --legend \
  -q
```

Tell the user:
```
HTML coverage report generated at:
  $FDW_DIR/coverage-html/index.html

Open in browser: open $FDW_DIR/coverage-html/index.html
```

---

### Subcommand: `analyze`

#### Step 1: Extract Uncovered Functions

Parse the lcov info file for uncovered functions:

```bash
cd $FDW_DIR
# Extract functions with zero hits
grep 'FNDA:0,' lcov_filtered.info | sed 's/FNDA:0,//' | sort
```

#### Step 2: Group by Source File

For each source file in the lcov data:
```bash
# Per-file coverage summary
lcov --summary lcov_filtered.info --list-full-path 2>&1 | grep -E '^\s+.*\.c'
```

#### Step 3: Analyze and Report

Display a detailed analysis:

```
## Datalake FDW Coverage Analysis

### Low Coverage Files (< 20%)

| File | Lines Hit | Total | Coverage | Testability |
|------|-----------|-------|----------|-------------|
| dlproxy/libchurl.c | 10 | 200 | 5.0% | Low (network errors) |
| provider/hudi/hudi_merged_logfile_record_reader.c | 20 | 150 | 13.3% | Medium |

### Uncovered Functions (Likely Testable)

| Function | File | Suggested SQL |
|----------|------|--------------|
| datalake_fdw_ExplainForeignScan | datalake_fdw.c | EXPLAIN SELECT * FROM ... |
| parquet_write_init | provider/parquet/write/parquetWrite.c | INSERT INTO ... (parquet) |

### Coverage by Component

| Component | Lines | Coverage | Priority |
|-----------|-------|----------|----------|
| datalake_fdw core | 500/1200 | 41.7% | High |
| Parquet provider | 200/800 | 25.0% | High |
| ORC provider | 150/600 | 25.0% | Medium |
| Iceberg provider | 100/500 | 20.0% | High |
| DLProxy | 50/400 | 12.5% | Low |
| Hudi provider | 30/300 | 10.0% | Low |
| Archive provider | 80/200 | 40.0% | Medium |
| AM Iceberg | 100/400 | 25.0% | High |
```

Use the source→SQL mapping table to suggest specific SQL operations that would increase coverage.

---

### Subcommand: `reset`

Delete all `.gcda` (runtime coverage data) files to start fresh:

```bash
find $FDW_SRC -name "*.gcda" -delete
echo "Deleted all .gcda files. Run tests again to generate fresh coverage data."
```

Also check for proxy coverage:
```bash
find $DB_ROOT/contrib/datalake_proxy -name "*.gcda" -delete
```

---

### Subcommand: `loop`

Automated coverage improvement cycle. This is an interactive loop:

#### Iteration 1: Baseline

1. **Collect**: Run `/datalake:coverage collect`
2. **Analyze**: Run `/datalake:coverage analyze`
3. **Identify**: Find the highest-impact uncovered functions (testable + high line count)
4. **Generate**: Write SQL test files targeting those functions
5. **Test**: Run the new tests with `/datalake:test`
6. **Measure**: Collect coverage again and compare delta

#### Loop Logic

```
ITERATION=1
TARGET_COVERAGE=80

while true:
  1. Collect coverage → current_coverage
  2. If current_coverage >= TARGET_COVERAGE: break, report success
  3. Analyze uncovered code
  4. Identify top 3-5 uncovered functions that are testable
  5. Generate SQL test cases for those functions
  6. Save tests to $AUTOMATION_DIR/sqlrepo/smoke/coverage_iter_$ITERATION/
  7. Run the new tests
  8. Reset coverage: delete .gcda
  9. Run ALL tests (to get cumulative coverage)
  10. Collect coverage again → new_coverage
  11. Report delta: new_coverage - current_coverage
  12. ITERATION++
  13. If delta < 1%: warn user, suggest manual inspection
```

At each iteration, show progress:

```
## Coverage Loop - Iteration 3

Previous: 35.2%  →  Current: 42.8%  (+7.6%)
Target: 80%

New tests added this iteration:
- smoke/coverage_iter_3/iceberg_write_test.sql (covers iceberg_write.c)
- smoke/coverage_iter_3/explain_test.sql (covers datalake_fdw.c:ExplainForeignScan)

Continue to next iteration? [Y/n]
```

Ask user for confirmation between iterations. Stop if:
- Target reached
- Coverage delta < 1% for two consecutive iterations
- User requests stop

### Important Notes

- Coverage requires `--enable-coverage` build flag — use `/datalake:build coverage`
- datalake_agent is Java — gcov/lcov does not apply to it
- datalake_proxy has only 1 source file — minimal coverage data
- The `lcov --no-external` flag filters out system headers
- Excluded files (roaring.c, mdb.c, midl.c) are third-party code embedded in the project
- The `loop` subcommand is experimental — it may need manual guidance for complex test scenarios
- Coverage data is cumulative: run all tests before collecting for accurate results
- Use `reset` to start fresh if coverage data is stale or corrupted
- Reference: `src/Makefile.global.in:1103-1154` has existing coverage make targets
