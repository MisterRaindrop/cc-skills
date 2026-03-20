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

### Step 1: Run the Parser

```bash
"${CLAUDE_SKILL_DIR}/../scripts/parse-results.sh" $ARGUMENTS
```

The script automatically searches these locations (relative to the detected cloudberry-pxf repo):
- `automation/target/surefire-reports/`
- `automation/test_artifacts/*/`

### Step 2: Present Results

Relay the script output to the user.

For failures, offer to:
1. Read the failing test source code
2. Check PXF logs for related errors
3. Re-run the specific failing test with `/pxf:test`

### Important Notes

- Exit code is 0 if all tests passed, 1 if any failures exist
- The parser reads JUnit/Surefire XML format (`TEST-*.xml`)
- Compatible with macOS and Linux (uses POSIX-compatible tools)
- You can also pass an explicit directory path if the auto-detection doesn't find reports
