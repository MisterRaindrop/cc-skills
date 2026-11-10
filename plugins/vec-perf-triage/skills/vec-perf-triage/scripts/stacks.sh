#!/bin/bash
# Repeated stack snapshots of every QD/QE of one session, to decide whether a
# query is hung (no progress) and to draw its wait graph.
#
#   stacks.sh <gp_session_id> [snapshots=3] [gap_s=10] [out_dir=./stacks]
#   env: PGPORT PGDATABASE (coordinator; used to find THIS cluster's postmasters),
#        JOBS=8 (gdb processes at once)
#
# INTRUSIVE: gdb stops each process while it reads the stacks (about 1 s, longer
# while symbols load).  That can change the waits you are looking at, and a
# timing-sensitive peer (interconnect timeouts) may see the pause.  Cost on a 32-segment
# aarch64 host (33 processes, JOBS=8): ~15 s wall and ~12 CPU-minutes per snapshot,
# almost all of it gdb loading symbols.  Use it on a
# query that is already stuck, not as a profiler; prefer one snapshot first.
# Run as the database OS user on the host of the segments.
#
# Per snapshot: <label>.<pid>.bt (all threads), .err (gdb stderr), cpu.txt,
# ss.txt; main.txt = main thread top-6 frames counted per slice; threads.txt =
# top frame of every thread counted per slice.  At the end: progress.txt =
# CPU ticks and main-thread stack change per slice between first and last snapshot.
set -uo pipefail
shopt -s nullglob
[ $# -ge 1 ] || { sed -n 2,19p "$0"; exit 2; }
CON=$1; N=${2:-3}; GAP=${3:-10}; BASE=${4:-./stacks}; JOBS=${JOBS:-8}
[[ $CON =~ ^[0-9]+$ ]] || { echo "gp_session_id must be a number: $CON" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$BASE/con$CON.$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUT"
python3 "$HERE/qe_pids.py" --con "$CON" > "$OUT/qe.txt" || exit 1
[ -s "$OUT/qe.txt" ] || { echo "no process of con$CON in this cluster on this host" >&2; exit 1; }
echo "$(wc -l < "$OUT/qe.txt") processes of con$CON; $N snapshot(s), ${GAP}s apart, $JOBS gdb at once"

grab() {   # pid label
  gdb -p "$1" -batch -ex "set debuginfod enabled off" -ex "set pagination off" \
      -ex "thread apply all bt 30" > "$S/$2.$1.bt" 2> "$S/$2.$1.err"
}
export -f grab

sig_main='/^Thread 1 /{t=1;next} /^Thread /{t=0}
  t && /^#[0-5] /{fn=$2; for(i=1;i<=NF;i++) if($i=="in"){fn=$(i+1);break}
                  out = out (out==""?"":" <- ") fn}
  END{print (out==""?"<unreadable>":out)}'
sig_threads='/^#0 /{fn=$2; for(i=1;i<=NF;i++) if($i=="in"){fn=$(i+1);break}; print fn}'

for k in $(seq 1 "$N"); do
  export S=$OUT/snap$k; mkdir -p "$S"
  while read -r pid label cmd; do
    f=$(cat "/proc/$pid/stat" 2>/dev/null) || continue
    f=${f##*) }; set -- $f; echo "$pid $label $(( ${12} + ${13} ))"   # utime+stime ticks
  done < "$OUT/qe.txt" > "$S/cpu.txt"
  awk '{print $1, $2}' "$OUT/qe.txt" | xargs -P "$JOBS" -L 1 bash -c 'grab "$0" "$1"'
  for f in "$S"/*.bt; do
    l=$(basename "$f" | cut -d. -f1)
    echo -e "$l\t$(awk "$sig_main" "$f")"
  done | sort | uniq -c | sort -k2,2 -k1,1nr > "$S/main.txt"
  for f in "$S"/*.bt; do
    l=$(basename "$f" | cut -d. -f1)
    awk "$sig_threads" "$f" | sed "s/^/$l\t/"
  done | sort | uniq -c | sort -k2,2 -k1,1nr > "$S/threads.txt"
  pids=$(awk '{print $1}' "$OUT/qe.txt" | paste -sd'|')
  ss -uanp 2>/dev/null | grep -E "pid=($pids)," | awk '$2>0||$3>0' > "$S/ss.txt"
  echo "== snapshot $k: main thread per slice"; cat "$S/main.txt"
  echo "   sockets with Recv-Q/Send-Q > 0: $(wc -l < "$S/ss.txt")  (full list: $S/ss.txt)"
  [ "$k" -lt "$N" ] && sleep "$GAP"
done

# Progress between the first and the last snapshot.  Hung = no CPU AND the same
# stacks AND socket queues that do not drain.  One snapshot alone proves nothing.
F=$OUT/snap1; L=$OUT/snap$N
{
  echo "slice  cpu_ticks_delta(sum)  main_stack_changed"
  join <(sort "$F/cpu.txt") <(sort "$L/cpu.txt") | awk '{d[$2]+=$5-$3} END{for(s in d) print s, d[s]}' |
  sort | while read -r s d; do
    a=$(grep -P "\t" "$F/main.txt" | awk -v s="$s" '$2==s' | md5sum)
    b=$(grep -P "\t" "$L/main.txt" | awk -v s="$s" '$2==s' | md5sum)
    [ "$a" = "$b" ] && ch=no || ch=yes
    echo "$s  $d  $ch"
  done
} | column -t | tee "$OUT/progress.txt"
echo "sockets with Recv-Q/Send-Q > 0, first/last snapshot: $(wc -l < "$F/ss.txt") / $(wc -l < "$L/ss.txt")" |
  tee -a "$OUT/progress.txt"
gdb_err=$(cat "$OUT"/snap*/*.err | grep -vc "^warning\|^$" || true)
echo "gdb error lines (see *.err): $gdb_err"
echo "saved in $OUT"
