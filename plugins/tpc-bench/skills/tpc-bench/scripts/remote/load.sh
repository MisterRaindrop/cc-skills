#!/bin/bash
# load.sh <workdir> <cluster> <h|ds> <scale> [mkconfig options...]   (gpadmin, coordinator host)
# Generates + loads TPC data with proteus (schema sf<scale><am>_tpc<set>), then runs an explicit ANALYZE
# (proteus only analyzes inside the SQL step), records row counts, and removes the generated flat files
# (they live under this cluster's own segment data dirs).
set -uo pipefail
W=$1; NAME=$2; S=$3; SCALE=$4; shift 4
C=$W/clusters/$NAME; B=$W/bin; P=$W/proteus
set +u; source $C/cluster.env; set -u
log(){ echo "[$(date '+%F %T')] load $S sf$SCALE: $*"; }
TS=tpc-$S
export TERM=xterm
# never disturb other users: stock proteus kills EVERY gpfdist (stop_gpfdist.sh) and runs `pkill dbgen` / `pkill dsdgen`
# on the hosts as gpadmin (same uid as gpadmin inside docker containers). patch_proteus.sh scopes all three to
# tpcbench_ paths; refuse to run on an unpatched proteus. Foreign generators are then only a load-contention warning
# (whether the hosts are idle enough is nightly.py's idle gate).
for pt in pkill-only-tpcbench-generators gpfdist-port-override; do
  grep -q $pt $P/.tpcbench_patches 2>/dev/null || { log "ABORT: proteus not patched ($pt; run patch_proteus.sh)"; exit 3; }
done
HOSTS=$(python3 -c "import json;print(' '.join(json.load(open('$C/cluster.json'))['hosts']))")
others=$(for h in $HOSTS; do ssh -o BatchMode=yes $h "pgrep -a 'gpfdist|dbgen|dsdgen'" | grep -v "tpcbench_" | sed "s/^/$h: /"; done)
[ -n "$others" ] && { log "WARNING foreign gpfdist/dbgen/dsdgen running (not touched; they compete for CPU/IO):"; echo "$others" | head -5; }
# wait for our own leftovers from an interrupted load
for i in $(seq 1 120); do
  mine=$(for h in $HOSTS; do ssh -o BatchMode=yes $h "pgrep -f '[t]pcbench_$NAME.*(dbgen|dsdgen)'"; done)
  [ -z "$mine" ] && break; [ $i = 1 ] && log "waiting for leftover generators of this cluster"; sleep 5
done
# gpfdist ports: stock proteus uses <digit>4660/<digit>5880 + rank, the same ports as every other proteus user on the
# host -> pick a base whose range is free on every host (patch 4 makes proteus honour it)
NSEGH=$(python3 -c "import json;print(json.load(open('$C/cluster.json'))['segs_per_host'])")
for base in $(seq 27000 100 29900); do
  busy=$(for h in $HOSTS; do ssh -n -o BatchMode=yes $h "ss -ltnH | awk '{print \$4}' | grep -oE '[0-9]+\$'"; done \
         | awk -v lo=$base -v hi=$((base + NSEGH + 1)) '$1>=lo && $1<=hi' | head -1)
  [ -z "$busy" ] && { export TPCBENCH_GPFDIST_PORT=$base; break; }
done
[ -n "${TPCBENCH_GPFDIST_PORT:-}" ] || { log "ABORT: no free gpfdist port range in 27000-29999"; exit 3; }
log "gpfdist ports $TPCBENCH_GPFDIST_PORT+1..+$NSEGH on every host"
# tpc-ds generate_data.sh copies every generated flat file into <first of /data/nvme0|/data/nvme1>/tpcds_cache/scale_N/
# parallel_P/ (USE_CACHE defaults to true): a second full copy of the raw data on a disk we don't own -- at 1TB it
# filled 56's /data/nvme0 (330GB) and killed the store_sales load (2026-11-12). Never cache.
export USE_CACHE=false
CFG=$(python3 $B/mkconfig.py $W $NAME $S $SCALE load "$@") || exit 2
OUT=$C/loads/$S.sf$SCALE.$(date +%Y%m%d_%H%M%S); mkdir -p $OUT
log "proteus CONFIG=$CFG (log $OUT/proteus.out)"
t0=$(date +%s)
( cd $P && PRESERVE_SYSTEM_CACHE=true DROP_GOPHER_CACHE=false COLLECT_SYSTEM_CONFIGS=false COLLECT_DB_LOG=false \
  SKIP_REPORT=true ENV=$C/proteus_env.conf ./proteus.sh CONFIG=$CFG TEST_SETS=$TS ) > $OUT/proteus.out 2>&1
rc=$?
st=$(cat $P/results/default_stream/$CFG/logs/$TS/status 2>/dev/null || echo MISSING)
cp -a $P/results/default_stream/$CFG/logs $OUT/ 2>/dev/null
log "proteus rc=$rc status=$st ($(( $(date +%s) - t0 ))s)"
[ "$st" = SUCCESS ] || { tail -20 $OUT/proteus.out; exit 4; }
schema=$(. $P/configs/$CFG/test.conf; echo ${SCHEMA_NAME_PREFIX}$S)
DIST=$(. $P/configs/$CFG/test.conf; [ "$RANDOM_DISTRIBUTION" = true ] && echo random || echo hash)
log "ANALYZE $schema"
psql -Atc "select format('ANALYZE %I.%I;', schemaname, tablename) from pg_tables where schemaname='$schema'" \
  | xargs -P 8 -I{} psql -q -c "{}" > $OUT/analyze.out 2>&1
psql -Atc "select relname, reltuples::bigint from pg_class c join pg_namespace n on n.oid=c.relnamespace
           where nspname='$schema' and relkind in ('r','p') order by 1" > $OUT/rowcounts.txt
DJ=$C/data_${S}_$(. $P/configs/$CFG/test.conf; echo ${SCHEMA_NAME_PREFIX%_tpc}).json
python3 - $DJ "$schema" "$SCALE" "$(cat $C/build.cur)" $OUT/rowcounts.txt "$DIST" <<'PY'
import json, sys, time
out, schema, scale, build, rc, dist = sys.argv[1:]
rows = dict(l.strip().split("|") for l in open(rc) if "|" in l)
json.dump(dict(schema=schema, scale=int(scale), distribution=dist, loaded_build=build, loaded_at=time.strftime("%F %T"),
               analyzed=True, tables={k: int(v) for k, v in rows.items()}), open(out, "w"), indent=1)
PY
# flat files: <segment datadir>/hbenchmark (tpc-h) or the tpc-ds equivalent, inside this cluster only
for row in $(psql -Atc "select hostname||':'||datadir from gp_segment_configuration where content>=0"); do
  h=${row%%:*}; d=${row#*:}
  ssh -o BatchMode=yes $h "for x in $d/hbenchmark $d/dsbenchmark; do [ -d \$x ] && rm -rf \$x; done; true"
done
log "OK $(wc -l < $OUT/rowcounts.txt) tables, $(awk -F'|' '{s+=$2} END{print s}' $OUT/rowcounts.txt) rows"
