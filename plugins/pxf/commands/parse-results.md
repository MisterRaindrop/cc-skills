# /pxf:parse-results

Parse and display PXF test results from surefire XML reports.

## Usage

```
/pxf:parse-results [DIR] [--json] [--failures-only]
```

**Arguments:**
- `DIR` — Path to surefire-reports directory (auto-detected by default)

**Options:**
- `--json` — Output results as JSON
- `--failures-only` — Only show failed/errored test suites

## Instructions

You are executing the `/pxf:parse-results` command. Follow these steps precisely:

### Step 1: Locate PXF Repository

Find the cloudberry-pxf repo root directory containing `dev/parse-results.sh`.

Search strategy:
1. Current working directory or its parents
2. Common paths: `~/workspace/cloudberry-pxf`, `~/github/cloudberry-pxf`

If not found, ask the user for the path. Store as `PXF_REPO`.

### Step 2: Run the Parser

```bash
"$PXF_REPO/dev/parse-results.sh" $ARGUMENTS
```

The script automatically searches these locations:
- `automation/target/surefire-reports/`
- `automation/test_artifacts/*/`

### Step 3: Present Results

The script outputs a formatted table. Relay the output to the user.

For failures, offer to:
1. Read the failing test source code
2. Check PXF logs for related errors
3. Re-run the specific failing test with `/pxf:test`

### Output Formats

**Text (default):**
```
==========================================
  PXF Test Results
==========================================

  Total:   42
  Passed:  40
  Failed:  2
  Skipped: 0

Suite                            Total  Pass  Fail  Skip  Time(s)
-----------------------------------------------------------------
org.example.FooTest                 10    9     1     0     3.2
org.example.BarTest                 32   31     1     0     8.1

Failure Details:
  FAIL: org.example.FooTest#testBar
        expected 42 but got 0
```

**JSON (`--json`):**
```json
{
  "total": 42,
  "passed": 40,
  "failed": 2,
  "skipped": 0,
  "failures": 1,
  "errors": 1
}
```

### Important Notes

- Exit code is 0 if all tests passed, 1 if any failures exist
- The parser reads JUnit/Surefire XML format (`TEST-*.xml`)
- Compatible with macOS and Linux (uses POSIX-compatible tools)
- Reports may be inside the Docker container — the volume mount makes them accessible from the host
