#!/bin/bash
# A/B one query under two PGOPTIONS sets.
#
#   ab.sh <query.sql> "<opts A>" "<opts B>" [rounds=3] [out=./runs]
#   env: PGPORT PGDATABASE, WARMUP=1 (warm-up runs per side, not counted),
#        TIMEOUT=1800 (statement_timeout s), INTERVAL=1 (sampling s)
#
# Order per round alternates A,B / B,A / A,B ... so neither side always runs on
# the cache the other one just warmed.  A run counts only if it succeeded
# (psql rc 0, no ERROR); every successful run must return the same rows
# (order-free sha256 of the output).  Session-level options only: no config
# change, no restart.  The sampler refuses SQL that writes.
set -uo pipefail
[ $# -ge 3 ] || { sed -n 2,13p "$0"; exit 2; }
SQL=$1; OA=$2; OB=$3; R=${4:-3}; OUT=${5:-./runs}
WARMUP=${WARMUP:-1}; TIMEOUT=${TIMEOUT:-1800}; INTERVAL=${INTERVAL:-1}
HERE=$(cd "$(dirname "$0")" && pwd)
base=$(basename "$SQL" .sql)
mkdir -p "$OUT"

run() {   # tag opts
  python3 "$HERE/sampler.py" --tag "$1" --sql "$SQL" --opts "$2" --out "$OUT" \
    --timeout "$TIMEOUT" --interval "$INTERVAL" \
    --port "${PGPORT:-5432}" --db "${PGDATABASE:-postgres}" > /dev/null
  echo "$(head -1 "$OUT/$1/summary.txt" 2>/dev/null || echo "$1 status=NO_RESULT")"
}

{
  for w in $(seq 1 "$WARMUP"); do run "${base}_wA$w" "$OA"; run "${base}_wB$w" "$OB"; done
  for i in $(seq 1 "$R"); do
    if (( i % 2 )); then order="A B"; else order="B A"; fi
    for side in $order; do
      [ $side = A ] && o=$OA || o=$OB
      run "${base}_${side}${i}" "$o"
    done
  done
} | tee "$OUT/${base}_ab.log"

python3 - "$OUT" "$base" "$R" <<'EOF' | tee "$OUT/${base}_ab.txt"
import json, os, statistics, sys
out, base, R = sys.argv[1], sys.argv[2], int(sys.argv[3])
G = 2 ** 20
runs = {"A": [], "B": []}
shas, bad = set(), []
for side in "AB":
    for i in range(1, R + 1):
        p = os.path.join(out, f"{base}_{side}{i}", "result.json")
        if not os.path.exists(p):
            bad.append(f"{side}{i}: no result"); continue
        r = json.load(open(p))
        if r["status"] != "OK":
            bad.append(f"{side}{i}: {r['status']} {r['errors'][:1]}"); continue
        runs[side].append(r); shas.add(r["sha_sorted"])
for d in os.listdir(out):                         # warm-ups: not timed, but rows must match too
    p = os.path.join(out, d, "result.json")
    if d.startswith(f"{base}_w") and os.path.exists(p):
        r = json.load(open(p))
        if r["status"] == "OK":
            shas.add(r["sha_sorted"])
        else:
            bad.append(f"{d}: {r['status']} {r['errors'][:1]}")

print(f"{'side':<5}{'n_ok':>5}{'elapsed_s (each run)':>40}{'median':>9}{'spread':>8}"
      f"{'peak_GiB median':>17}")
stat = {}
for side in "AB":
    e = [r["elapsed_s"] for r in runs[side]]
    m = [r["peak_sum_rss_kb"] / G for r in runs[side]]
    if not e:
        print(f"{side:<5}{0:>5}"); continue
    med = statistics.median(e)
    spread = (max(e) - min(e)) / med if med else 0
    stat[side] = (med, spread, statistics.median(m))
    print(f"{side:<5}{len(e):>5}{' '.join(f'{x:.1f}' for x in e):>40}{med:>9.1f}"
          f"{spread:>7.0%}{statistics.median(m):>17.1f}")
if bad:
    print("FAILED runs (excluded):", *bad, sep="\n  ")
print(f"result sha256 (order-free) distinct over successful runs: {len(shas)}"
      + ("  OK" if len(shas) == 1 else "  MISMATCH: check ORDER BY / float output before comparing"))
if len(stat) == 2 and min(len(runs['A']), len(runs['B'])) >= 2:
    (ma, sa, pa), (mb, sb, pb) = stat["A"], stat["B"]
    d = (mb - ma) / ma
    noise = max(sa, sb)
    verdict = "difference exceeds within-side spread" if abs(d) > noise else "WITHIN NOISE: not a valid difference"
    print(f"B vs A: elapsed {d:+.1%} (within-side spread {noise:.0%}) -> {verdict}; "
          f"peak memory {pb - pa:+.1f} GiB")
else:
    print("need >= 2 successful runs per side for a verdict")
EOF
