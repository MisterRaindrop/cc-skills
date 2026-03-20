#!/bin/bash
set -euo pipefail

# Parse surefire test results from XML reports
# Usage: parse-results.sh [surefire-reports-dir]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$("${SCRIPT_DIR}/detect-pxf-repo.sh" 2>/dev/null)" || REPO_DIR=""

usage() {
    cat <<EOF
Usage: $0 [DIR] [OPTIONS]

Parse and display JUnit/Surefire XML test reports.

Arguments:
  DIR    Path to surefire-reports directory (default: searches common locations)

Options:
  --json           Output results as JSON
  --failures-only  Only show failed/errored tests
  -h, --help       Show this help

Searches these locations by default:
  - automation/target/surefire-reports/
  - automation/test_artifacts/*/
EOF
    exit 0
}

# Parse args
REPORT_DIR=""
JSON_OUTPUT=false
FAILURES_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json) JSON_OUTPUT=true; shift ;;
        --failures-only) FAILURES_ONLY=true; shift ;;
        -h|--help) usage ;;
        -*) echo "Unknown option: $1"; usage ;;
        *)
            REPORT_DIR="$1"; shift
            ;;
    esac
done

# Find report directories
find_report_dirs() {
    local dirs=()

    if [ -n "${REPORT_DIR}" ]; then
        [ -d "${REPORT_DIR}" ] || { echo "Directory not found: ${REPORT_DIR}"; exit 1; }
        dirs+=("${REPORT_DIR}")
    elif [ -n "${REPO_DIR}" ]; then
        # Check common locations relative to detected repo
        local surefire="${REPO_DIR}/automation/target/surefire-reports"
        if [ -d "${surefire}" ]; then
            dirs+=("${surefire}")
        fi

        # Check test_artifacts subdirectories
        local artifacts="${REPO_DIR}/automation/test_artifacts"
        if [ -d "${artifacts}" ]; then
            for d in "${artifacts}"/*/; do
                [ -d "$d" ] && dirs+=("$d")
            done
        fi
    fi

    if [ ${#dirs[@]} -eq 0 ]; then
        echo "No test report directories found."
        echo "Run tests first or specify a directory: $0 /path/to/surefire-reports"
        exit 1
    fi

    printf '%s\n' "${dirs[@]}"
}

# Extract attributes from a testsuite XML tag
parse_testsuite_attrs() {
    local xml_file="$1"
    # Extract the <testsuite ...> opening tag (may span multiple lines)
    local tag
    tag=$(head -5 "$xml_file" | tr '\n' ' ' | grep -oE '<testsuite[^>]*>' | head -1)
    [ -z "$tag" ] && return

    local name tests failures errors skipped time
    name=$(echo "$tag" | grep -oE 'name="[^"]*"' | head -1 | sed 's/name="//;s/"//')
    tests=$(echo "$tag" | grep -oE 'tests="[0-9]*"' | head -1 | sed 's/tests="//;s/"//')
    failures=$(echo "$tag" | grep -oE 'failures="[0-9]*"' | head -1 | sed 's/failures="//;s/"//')
    errors=$(echo "$tag" | grep -oE 'errors="[0-9]*"' | head -1 | sed 's/errors="//;s/"//')
    skipped=$(echo "$tag" | grep -oE 'skipped="[0-9]*"' | head -1 | sed 's/skipped="//;s/"//')
    time=$(echo "$tag" | grep -oE 'time="[0-9.]*"' | head -1 | sed 's/time="//;s/"//')

    echo "${name:-unknown}|${tests:-0}|${failures:-0}|${errors:-0}|${skipped:-0}|${time:-0}"
}

# Extract failure details from XML (compatible with macOS awk)
parse_failures() {
    local xml_file="$1"
    local classname="" testname=""

    while IFS= read -r line; do
        # Track current testcase
        if echo "$line" | grep -q '<testcase '; then
            classname=$(echo "$line" | sed -n 's/.*classname="\([^"]*\)".*/\1/p')
            testname=$(echo "$line" | sed -n 's/.*name="\([^"]*\)".*/\1/p')
        fi
        # Detect failure or error
        if echo "$line" | grep -qE '<failure |<error '; then
            if [ -n "$classname" ] && [ -n "$testname" ]; then
                local message
                message=$(echo "$line" | sed -n 's/.*message="\([^"]*\)".*/\1/p')
                # Truncate long messages
                if [ ${#message} -gt 200 ]; then
                    message="${message:0:200}..."
                fi
                printf "  FAIL: %s#%s\n" "$classname" "$testname"
                [ -n "$message" ] && printf "        %s\n" "$message"
            fi
        fi
    done < "$xml_file"
}

# Main
TOTAL_TESTS=0
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_ERROR=0
TOTAL_SKIP=0

# Collect all suite results
declare -a SUITE_RESULTS=()
declare -a FAILURE_DETAILS=()

while IFS= read -r dir; do
    for xml in "${dir}"/TEST-*.xml; do
        [ -f "$xml" ] || continue

        result=$(parse_testsuite_attrs "$xml")
        [ -z "$result" ] && continue

        IFS='|' read -r name tests failures errors skipped time <<< "$result"

        TOTAL_TESTS=$((TOTAL_TESTS + tests))
        TOTAL_FAIL=$((TOTAL_FAIL + failures))
        TOTAL_ERROR=$((TOTAL_ERROR + errors))
        TOTAL_SKIP=$((TOTAL_SKIP + skipped))

        failed=$((failures + errors))
        passed=$((tests - failed - skipped))
        TOTAL_PASS=$((TOTAL_PASS + passed))

        # Only collect suite if it has results or failures
        if [ "$tests" -gt 0 ]; then
            SUITE_RESULTS+=("${name}|${tests}|${passed}|${failed}|${skipped}|${time}")
        fi

        # Collect failure details
        if [ "$failed" -gt 0 ]; then
            detail=$(parse_failures "$xml")
            if [ -n "$detail" ]; then
                FAILURE_DETAILS+=("$detail")
            fi
        fi
    done
done < <(find_report_dirs)

# JSON output
if [ "${JSON_OUTPUT}" = true ]; then
    cat <<EOF
{
  "total": ${TOTAL_TESTS},
  "passed": ${TOTAL_PASS},
  "failed": $((TOTAL_FAIL + TOTAL_ERROR)),
  "skipped": ${TOTAL_SKIP},
  "failures": ${TOTAL_FAIL},
  "errors": ${TOTAL_ERROR}
}
EOF
    exit $(( (TOTAL_FAIL + TOTAL_ERROR) > 0 ? 1 : 0 ))
fi

# Text output
TOTAL_FAILED=$((TOTAL_FAIL + TOTAL_ERROR))

echo ""
echo "=========================================="
echo "  PXF Test Results"
echo "=========================================="
echo ""
printf "  Total:   %d\n" "${TOTAL_TESTS}"
printf "  Passed:  %d\n" "${TOTAL_PASS}"
printf "  Failed:  %d\n" "${TOTAL_FAILED}"
printf "  Skipped: %d\n" "${TOTAL_SKIP}"
echo ""

# Suite breakdown (skip if --failures-only and suite passed)
if [ ${#SUITE_RESULTS[@]} -gt 0 ]; then
    echo "------------------------------------------"
    printf "%-50s %5s %5s %5s %5s %8s\n" "Suite" "Total" "Pass" "Fail" "Skip" "Time(s)"
    echo "------------------------------------------"

    for entry in "${SUITE_RESULTS[@]}"; do
        IFS='|' read -r name tests passed failed skipped time <<< "$entry"
        if [ "${FAILURES_ONLY}" = true ] && [ "$failed" -eq 0 ]; then
            continue
        fi
        # Truncate long suite names
        display_name="$name"
        if [ ${#display_name} -gt 50 ]; then
            display_name="...${display_name: -47}"
        fi
        printf "%-50s %5d %5d %5d %5d %8s\n" "$display_name" "$tests" "$passed" "$failed" "$skipped" "$time"
    done
    echo "------------------------------------------"
fi

# Failure details
if [ ${#FAILURE_DETAILS[@]} -gt 0 ]; then
    echo ""
    echo "=========================================="
    echo "  Failure Details"
    echo "=========================================="
    for detail in "${FAILURE_DETAILS[@]}"; do
        echo "$detail"
    done
    echo ""
fi

# Exit code: 1 if any failures
exit $(( TOTAL_FAILED > 0 ? 1 : 0 ))
