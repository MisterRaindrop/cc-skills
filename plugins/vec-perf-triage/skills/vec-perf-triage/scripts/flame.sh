#!/bin/bash
# Profiles of one QE process (pick the pid and the window from sampler curves).
#
#   flame.sh cpu      <pid> <sec> [out]   on-CPU stacks, 99 Hz
#   flame.sh offcpu   <pid> <sec> [out]   off-CPU TIME by stack (bcc offcputime; needs root/BPF)
#   flame.sh switches <pid> <sec> [out]   context-switch COUNT by stack (perf sched_switch);
#                                         a count, not blocked time: 1000 short waits outrank
#                                         one 30 s wait.  Fallback when bcc is missing.
#   flame.sh faults   <pid> <sec> [out]   page faults by stack = FIRST TOUCH of new pages,
#                                         not necessarily the allocator (a pool allocates,
#                                         the scan touches)
#   flame.sh memattr  <pid> <sec> [out] [nqe]
#                                         page faults (1 sample / FAULT_PERIOD=16 pages)
#                                         + RssAnon before/after, then opattr.py: share and
#                                         MB per operator and function (x nqe for the slice).
#                                         Run ONLY while the QE's memory grows.
#   flame.sh topdown  <pid> <sec> [groups=TopDownL1]
#                                         perf stat metric groups in ONE window; lists the
#                                         groups this CPU supports if the name is unknown
#   flame.sh diff     <a.folded> <b.folded> [out]   differential flame graph, red = more in b
#
# Output: <out>.folded (collapsed stacks) and <out>.svg when Brendan Gregg's
# FlameGraph scripts are in $FLAMEGRAPH; without them <out>.perfscript (raw text).
# Overhead: cpu ~1-2%; switches/faults depend on the event rate; offcpu (BPF) low.
# Unwinding: CALLGRAPH=dwarf (default) works without frame pointers (postgres/arrow
# builds usually have none: with "fp", most frames show as [unknown]); cost: bigger
# perf.data and slower perf script.  CALLGRAPH=fp for long windows.
# Permissions: tracepoints (switches) and BPF (offcpu) usually need root; run with
# SUDO=sudo (prefixes perf / offcputime) instead of loosening tracefs or perf_event_paranoid.
set -euo pipefail
[ $# -ge 1 ] || { sed -n 2,29p "$0"; exit 2; }
MODE=$1; shift
FG=${FLAMEGRAPH:-$HOME/FlameGraph}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT           # fresh perf.data: a stale root-owned one records 0 samples
have_fg() { [ -x "$FG/flamegraph.pl" ] && [ -x "$FG/stackcollapse-perf.pl" ]; }
P="${SUDO:+$SUDO }perf"
alive() { kill -0 "$1" 2>/dev/null || { echo "pid $1 is gone" >&2; exit 1; }; }

perf_mode() {   # event-args...
  PID=$1; SEC=$2; OUT=$3; shift 3
  alive "$PID"
  $P record "$@" --call-graph "${CALLGRAPH:-dwarf}" -p "$PID" -o "$TMP/perf.data" -- sleep "$SEC" 2> "$TMP/rec.err" || {
    cat "$TMP/rec.err" >&2
    grep -qi "permission" "$TMP/rec.err" && echo "hint: rerun with SUDO=sudo" >&2
    exit 1; }
  if have_fg; then
    $P script -i "$TMP/perf.data" | "$FG/stackcollapse-perf.pl" > "$OUT.folded"
    "$FG/flamegraph.pl" --title "$MODE pid $PID ${SEC}s" "$OUT.folded" > "$OUT.svg"
    echo "wrote $OUT.folded $OUT.svg"
  else
    $P script -i "$TMP/perf.data" > "$OUT.perfscript"
    echo "FlameGraph scripts not in $FG: wrote raw $OUT.perfscript (collapse it elsewhere)"
  fi
}

case $MODE in
  cpu)      perf_mode "$1" "$2" "${3:-./cpu_$1}" -F 99 ;;
  switches) perf_mode "$1" "$2" "${3:-./switches_$1}" -e sched:sched_switch ;;
  faults)   perf_mode "$1" "$2" "${3:-./faults_$1}" -e page-faults ;;
  memattr)
    PID=$1; SEC=$2; OUT=${3:-./memattr_$1}; NQE=${4:-0}; alive "$PID"
    kb() { awk -v k="^$1:" '$0 ~ k {print $2; f=1} END {if (!f) print 0}' "$2" 2>/dev/null || echo 0; }
    snap() { echo "$(kb RssAnon /proc/$PID/status) $(kb AnonHugePages /proc/$PID/smaps_rollup)"; }
    CG=${CALLGRAPH:-dwarf}; [ "$CG" = dwarf ] && CG=dwarf,16384
    read -r A HA < <(snap); T=$(date +%s)
    $P record -e page-faults -c "${FAULT_PERIOD:-16}" --call-graph "$CG" \
      -p "$PID" -o "$TMP/perf.data" -- sleep "$SEC" 2> "$TMP/rec.err" || {
      cat "$TMP/rec.err" >&2
      grep -qi "permission" "$TMP/rec.err" && echo "hint: rerun with SUDO=sudo" >&2
      exit 1; }
    read -r B HB < <(snap)
    [ "$B" -gt 0 ] || { B=$A; HB=$HA; echo "pid $PID exited during the window: delta unknown" >&2; }
    D=$(( (B - A) / 1024 )); DH=$(( (HB - HA) / 1024 ))
    echo "pid=$PID t0=$T sec=$SEC RssAnon ${A}kB -> ${B}kB delta=${D}MB AnonHugePages delta=${DH}MB" | tee "$OUT.window"
    $P script -i "$TMP/perf.data" > "$OUT.perfscript" 2>/dev/null
    python3 "$(dirname "$0")/opattr.py" "$OUT.perfscript" "$D" --thp-mb "$DH" \
      --period "${FAULT_PERIOD:-16}" --qe "$NQE" | tee "$OUT.opattr.txt"
    ;;
  offcpu)
    PID=$1; SEC=$2; OUT=${3:-./offcpu_$1}; alive "$PID"
    T=$(command -v offcputime-bpfcc || command -v offcputime || ls /usr/share/bcc/tools/offcputime 2>/dev/null || true)
    [ -n "$T" ] || { echo "bcc offcputime not installed; use 'switches' (counts only)" >&2; exit 1; }
    ${SUDO:-} "$T" -df -p "$PID" "$SEC" > "$OUT.folded" ||    # folded, value = microseconds blocked
      { echo "offcputime failed (root? kernel headers for BPF?); fall back to 'switches'" >&2; exit 1; }
    if [ -x "$FG/flamegraph.pl" ]; then
      "$FG/flamegraph.pl" --color=io --countname=us --title "off-CPU pid $PID ${SEC}s" "$OUT.folded" > "$OUT.svg"
    fi
    echo "wrote $OUT.folded $( [ -x "$FG/flamegraph.pl" ] && echo "$OUT.svg")"
    ;;
  topdown)
    PID=$1; SEC=$2; MG=${3:-TopDownL1}; alive "$PID"
    if ! perf list metricgroups 2>/dev/null | grep -qw "${MG%%,*}"; then
      echo "metric group ${MG%%,*} not known here; supported groups:" >&2
      perf list metricgroups 2>/dev/null | sed -n '1,40p' >&2
      echo "x86: try 'perf stat --topdown'; anywhere: cycles,instructions,cache-misses,branch-misses" >&2
      exit 1
    fi
    $P stat -M "$MG" -p "$PID" -- sleep "$SEC"           # one window for all groups
    ;;
  diff)
    A=$1; B=$2; OUT=${3:-./diff}
    [ -x "$FG/difffolded.pl" ] || { echo "needs $FG/difffolded.pl" >&2; exit 1; }
    "$FG/difffolded.pl" "$A" "$B" > "$OUT.folded"
    "$FG/flamegraph.pl" --title "diff: red = more in $(basename "$B")" "$OUT.folded" > "$OUT.svg"
    echo "wrote $OUT.svg"
    ;;
  *) sed -n 2,29p "$0"; exit 2 ;;
esac
