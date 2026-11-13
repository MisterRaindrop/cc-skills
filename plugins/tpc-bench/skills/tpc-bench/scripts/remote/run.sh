#!/bin/bash
# run.sh <workdir> <cluster> <run_id> <sets: h,ds> <scale> <upload true|false> <tags> [mkconfig options...]
# (gpadmin, coordinator host; start with nohup). One timed proteus run per test set, plus:
#   preflight snapshot (version, release-info, show all, host/busy, libarrow layout), collectors (sysmon 5s, qmon 1s),
#   crash handling (cluster down -> collect evidence -> restart -> continue), EXPLAIN pass after the timed run,
#   finalize.py (run.json/summary.txt per set) and, if upload=true, report DB + log upload (fallback analyzer
#   when proteus itself did not upload). A trap guarantees finalize/upload runs on any exit.
# Fault injection for flow tests: INJECT_CANCEL=<query file id, e.g. 105> cancels that query 2s after it starts.
set -uo pipefail
W=$1; NAME=$2; RID=$3; SETS=$4; SCALE=$5; UPLOAD=$6; TAGS=$7; shift 7; EXTRA=("$@")
C=$W/clusters/$NAME; B=$W/bin; P=$W/proteus; R=$C/runs/$RID
set +u; source $C/cluster.env; set -u
export TERM=xterm
mkdir -p $R; exec >> $R/run.log 2>&1
log(){ echo "[$(date '+%F %T')] $*"; }
state(){ python3 $B/state.py $R/state.json "$@"; }
COLL_PIDS=()
ME=$(hostname -s)
# other hosts of the cluster (multi-host): they get the same collectors; files come back as qmon.<host>.jsonl etc.
OTHERS=$(python3 -c "import json;print(' '.join(h for h in json.load(open('$C/cluster.json'))['hosts'] if h.split('.')[0] != '$ME'))")
rssh(){ ssh -o BatchMode=yes "$@"; }
start_collectors(){
  psql -Atc "select port from gp_segment_configuration where hostname='$ME' or address='$ME'" > $R/qmon.jsonl.ports
  rm -f $R/sysmon.tsv.stop $R/qmon.jsonl.stop
  nice -n 10 python3 $B/sysmon.py $R/sysmon.tsv 5 & COLL_PIDS+=($!)
  nice -n 10 python3 $B/qmon.py $R/qmon.jsonl x 1 & COLL_PIDS+=($!)
  for h in $OTHERS; do
    # keep the data files (collectors append, like on the coordinator): wiping them per test set made the fetched
    # qmon.<host>.jsonl hold only the last set, so an earlier set could not be re-finalized with remote QEs
    rssh $h "mkdir -p $R && rm -f $R/sysmon.tsv.stop $R/qmon.jsonl.stop $R/sysmon.tsv.pid $R/qmon.jsonl.pid"
    psql -Atc "select port from gp_segment_configuration where hostname='$h' or address='$h'" | rssh $h "cat > $R/qmon.jsonl.ports"
    rssh $h "cd $R && (nohup nice -n 10 python3 $B/sysmon.py $R/sysmon.tsv 5 >/dev/null 2>&1 &) && (nohup nice -n 10 python3 $B/qmon.py $R/qmon.jsonl x 1 >/dev/null 2>&1 &)"
  done
  COLL_REMOTE=1
}
stop_collectors(){
  # record our collectors' own CPU (utime+stime) first: run.json shows they do not disturb the timing
  if [ -n "${O:-}" ] && [ ${#COLL_PIDS[@]} -eq 2 ]; then
    local n=(sysmon qmon) i=0 hz; hz=$(getconf CLK_TCK)
    : > $O/collectors_cpu.txt
    for p in "${COLL_PIDS[@]}"; do
      awk -v n=${n[$i]} -v hz=$hz '{sub(/.*\) /,""); print n, ($12+$13)/hz}' /proc/$p/stat >> $O/collectors_cpu.txt 2>/dev/null
      i=$((i+1))
    done
  fi
  for h in $OTHERS; do   # remote collectors: own CPU, stop, fetch
    rssh $h "hz=\$(getconf CLK_TCK); for n in sysmon.tsv qmon.jsonl; do p=\$(cat $R/\$n.pid 2>/dev/null); [ -n \"\$p\" ] && awk -v n=\${n%%.*}@$h -v hz=\$hz '{sub(/.*\\) /,\"\"); print n, (\$12+\$13)/hz}' /proc/\$p/stat; done; touch $R/sysmon.tsv.stop $R/qmon.jsonl.stop" \
      >> ${O:-$R}/collectors_cpu.txt 2>/dev/null; true
  done
  touch $R/sysmon.tsv.stop $R/qmon.jsonl.stop; sleep 6; kill "${COLL_PIDS[@]}" 2>/dev/null; COLL_PIDS=()
  for h in $OTHERS; do
    rssh $h "for n in sysmon.tsv qmon.jsonl; do p=\$(cat $R/\$n.pid 2>/dev/null); [ -n \"\$p\" ] && kill \$p 2>/dev/null; done; true"
    scp -q -o BatchMode=yes $h:$R/qmon.jsonl $R/qmon.$h.jsonl 2>/dev/null
    scp -q -o BatchMode=yes $h:$R/sysmon.tsv $R/sysmon.$h.tsv 2>/dev/null
  done
}
cluster_up(){ psql -d gpadmin -Atc "select count(*) from gp_segment_configuration where status='d'" 2>/dev/null; }
finish(){
  rc=$?
  [ ${#COLL_PIDS[@]} -gt 0 ] && stop_collectors
  for s in ${SETS//,/ }; do
    [ -d $R/$s ] || continue
    [ -f $R/$s/run.json ] || python3 $B/finalize.py $R $s || log "finalize $s failed"
    if [ "$UPLOAD" = true ] && [ ! -f $R/$s/uploaded ]; then $B/upload.sh $W $NAME $RID $s || log "upload $s failed"; fi
  done
  state set phase done exit_code $rc finished_at "$(date '+%F %T')"
  log "run.sh exit rc=$rc"
}
trap finish EXIT
trap 'log "signal received"; exit 130' INT TERM

state set phase preflight run_id $RID cluster $NAME sets $SETS scale $SCALE upload $UPLOAD started_at "$(date '+%F %T')"
log "run $RID cluster=$NAME build=$TPCBENCH_BUILD sets=$SETS scale=$SCALE upload=$UPLOAD tags='$TAGS'"
if [ "$(cluster_up)" != 0 ]; then log "cluster not healthy -> start"; $B/cluster.sh $W $NAME start; fi
postgres --gp-version > $R/version.txt
cp $W/pkgs/$TPCBENCH_BUILD/release-info.yaml $W/pkgs/$TPCBENCH_BUILD/build.json $R/ 2>/dev/null
cp $C/cluster.json $R/
psql -Atc "show all" > $R/show_all.txt
python3 $B/discover.py > $R/host_before.json 2>/dev/null
for h in $OTHERS; do rssh $h "python3 $B/discover.py" > $R/host_before.$h.json 2>/dev/null; done
$B/layout.sh > $R/layout.txt 2>&1

for s in ${SETS//,/ }; do
  TS=tpc-$s; O=$R/$s; mkdir -p $O
  CFG=$(python3 $B/mkconfig.py $W $NAME $s $SCALE run --tags "$TAGS" --upload $UPLOAD "${EXTRA[@]}") || { echo CONFIG_FAILED > $O/status; continue; }
  echo $CFG > $O/config_name
  DJ=$C/data_${s}_$(. $P/configs/$CFG/test.conf; echo ${SCHEMA_NAME_PREFIX%_tpc}).json   # sf10pax (hash) / sf10paxrand
  if [ ! -f $DJ ]; then log "$TS: no data $(basename $DJ) -> skipped"; echo NO_DATA > $O/status; continue; fi
  cp $DJ $O/data.json
  state set phase "run:$s" config $CFG
  rm -rf $P/results/default_stream/$CFG
  if grep -q 'RUN_MULTI_USER="true"' $P/configs/$CFG/test.conf; then
    # proteus git ships x86 qgen/dsqgen in 07_multi_user (our rsync puts them back every run); the copies that the
    # compile step built for this host's arch are in 05_sql -> use those for the concurrent streams
    cp -f $P/testsets/tpc-h/05_sql/queries/qgen $P/testsets/tpc-h/07_multi_user/queries/qgen 2>/dev/null
    cp -f $P/testsets/tpc-ds/05_sql/dsqgen $P/testsets/tpc-ds/07_multi_user/dsqgen 2>/dev/null
  fi
  start_collectors
  inj=""
  if [ -n "${INJECT_CANCEL:-}" ]; then $B/inject_cancel.sh $P/results/default_stream/$CFG/logs/$TS/run.log "$INJECT_CANCEL" > $O/inject.log 2>&1 & inj=$!; fi
  log "$TS: proteus CONFIG=$CFG"
  t0=$(date +%s)
  ( cd $P && PRESERVE_SYSTEM_CACHE=true DROP_GOPHER_CACHE=false COLLECT_SYSTEM_CONFIGS=false COLLECT_DB_LOG=false \
    ENV=$C/proteus_env.conf ./proteus.sh CONFIG=$CFG TEST_SETS=$TS ) > $O/proteus.out 2>&1
  prc=$?; t1=$(date +%s)
  [ -n "$inj" ] && kill $inj 2>/dev/null
  echo "$t0 $t1 $prc" > $O/window.txt
  stop_collectors
  $B/layout.sh > $O/layout.txt 2>&1   # proteus restarted the cluster (gpstop -air for guc.conf): layout of the postmasters that ran the queries
  cp -a $P/results/default_stream/$CFG $O/proteus_results 2>/dev/null
  # archive exactly the query files this run executed: 05_sql/ also holds other scales' files (proteus only
  # replaces files of the same bench role), which would give wrong plans / wrong SQL for deep-dives
  mkdir -p $O/queries
  for f in $O/proteus_results/logs/$TS/*.single.result.out; do
    [ -f "$f" ] && cp $P/testsets/$TS/05_sql/$(basename $f .single.result.out) $O/queries/ 2>/dev/null
  done
  # concurrent streams (07_multi_user): every stream's query files (<stream_id>/<session>/*.sql)
  if ls $O/proteus_results/logs/$TS/rollout_testing_*.log >/dev/null 2>&1; then
    for d in $P/testsets/$TS/07_multi_user/*/; do [ -d $d/1 ] && cp -r $d $O/queries_streams; done
    [ -d $O/queries_streams ] && echo streams > $O/mode
  fi
  [ -n "$(ls $O/queries)" ] || [ -f $O/mode ] || log "$TS: WARNING no query files archived"
  st=$(cat $O/proteus_results/logs/$TS/status 2>/dev/null || echo MISSING); echo $st > $O/status
  log "$TS: proteus rc=$prc status=$st $((t1 - t0))s report_id=$(cat $O/proteus_results/logs/report_id.log 2>/dev/null)"
  down=$(cluster_up)
  if [ "$down" != 0 ]; then
    log "$TS: cluster unhealthy after run (down=$down) -> collect evidence + restart"
    $B/crash_evidence.sh $W $NAME $t0 > $O/crash_evidence.txt 2>&1
    $B/cluster.sh $W $NAME restart
  fi
  state set phase "explain:$s"
  [ -f $O/mode ] || $B/explain_pass.sh $O > $O/explain_pass.log 2>&1   # streams: plans are those of the single-stream run
  python3 $B/finalize.py $R $s || log "finalize $s failed"
  if [ "$UPLOAD" = true ]; then $B/upload.sh $W $NAME $RID $s || log "upload $s failed"; fi
done
